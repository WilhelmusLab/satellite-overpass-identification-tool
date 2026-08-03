"""Tests for CLI entry point behavior."""

import pytest

import satellite_overpass_identification_tool.app as app_module


def test_no_args_prints_help_and_exits(monkeypatch, capsys):
    """Invoking main() with no CLI arguments prints help text and exits with status 0."""
    monkeypatch.setattr("sys.argv", ["satellite-overpass-identification-tool"])

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out


@pytest.mark.parametrize(
    "argv,error_text",
    [
        (
            [
                "satellite-overpass-identification-tool",
                "--startdate",
                "2026-03-20",
                "--enddate",
                "2026-03-21",
                "--lat",
                "41.0",
                "--lon",
                "-71.0",
                "--csvoutpath",
                "out.csv",
                "--unknown-option",
            ],
            "unrecognized arguments: --unknown-option",
        ),
        (
            [
                "satellite-overpass-identification-tool",
                "--startdate",
            ],
            "argument --startdate: expected one argument",
        ),
        (
            [
                "satellite-overpass-identification-tool",
                "--startdate",
                "03-26-2026",
            ],
            "invalid fromisoformat value",
        ),
        (
            [
                "satellite-overpass-identification-tool",
                "--lat",
                "north",
            ],
            "argument --centroid-lat/--lat: invalid float value",
        ),
    ],
)
def test_invalid_cli_arguments_exit_with_parser_error(
    monkeypatch, capsys, argv, error_text
):
    """Invalid CLI arguments should trigger argparse usage errors and exit code 2."""
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert error_text in captured.err


def test_missing_csvoutpath_exits_with_clear_error(monkeypatch, capsys):
    """Parsed arguments without --csvoutpath should exit before any API calls."""
    monkeypatch.setattr(
        app_module,
        "get_credentials",
        lambda _domain, args=None: ("user", "pass"),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "satellite-overpass-identification-tool",
            "--startdate",
            "2026-03-20",
            "--enddate",
            "2026-03-21",
            "--lat",
            "41.0",
            "--lon",
            "-71.0",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "--csvoutpath" in captured.err


def test_default_historical_db_bypasses_credential_lookup(monkeypatch, tmp_path):
    """Default historical DB path should run without calling get_credentials."""
    output_path = tmp_path / "out.csv"

    def _unexpected_credentials_call(_domain, args=None):
        raise AssertionError("get_credentials should not be called")

    monkeypatch.setattr(
        app_module,
        "get_credentials",
        _unexpected_credentials_call,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "satellite-overpass-identification-tool",
            "--startdate",
            "2026-03-20",
            "--enddate",
            "2026-03-21",
            "--lat",
            "41.0",
            "--lon",
            "-71.0",
            "--csvoutpath",
            str(output_path),
        ],
    )

    app_module.main()
    assert output_path.is_file()
