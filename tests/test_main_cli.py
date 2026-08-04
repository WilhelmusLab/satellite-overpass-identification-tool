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


@pytest.mark.parametrize("domain_arg", ["--domain", "-d"])
def test_explicit_domain_rejects_refresh_flag(monkeypatch, domain_arg):
    """Explicit domain and refresh flag are incompatible."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "satellite-overpass-identification-tool",
            domain_arg,
            "mock.space-track.test",
            "--refresh-historical-tle-db",
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
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        app_module.main()

    assert str(exc_info.value) == (
        "Error: --refresh-historical-tle-db cannot be used when --domain/-d "
        "is explicitly provided."
    )


@pytest.mark.parametrize("domain_arg", ["--domain", "-d"])
def test_explicit_domain_forces_credential_lookup(monkeypatch, tmp_path, domain_arg):
    """Explicit domain should force API mode."""
    output_path = tmp_path / "out.csv"
    saw_credentials_call = {"value": False}
    expected_domain = "mock.space-track.test"

    def _credentials_called(domain, args=None):
        assert domain == expected_domain
        saw_credentials_call["value"] = True
        return ("user", "pass")

    def _resolver_must_not_run(*_args, **_kwargs):
        raise AssertionError("resolve_historical_tle_db should not be called")

    def _fake_get_passtimes(**kwargs):
        assert kwargs["historical_tle_db"] is None
        assert kwargs["SPACEUSER"] == "user"
        assert kwargs["SPACEPSWD"] == "pass"
        assert kwargs["domain"] == expected_domain
        return app_module.np.array([], dtype=app_module.PASS_TIMES_DTYPE)

    monkeypatch.setattr(app_module, "get_credentials", _credentials_called)
    monkeypatch.setattr(
        app_module,
        "resolve_historical_tle_db",
        _resolver_must_not_run,
    )
    monkeypatch.setattr(app_module, "get_passtimes", _fake_get_passtimes)
    monkeypatch.setattr(app_module, "write_passtimes_csv", lambda **_kwargs: None)

    monkeypatch.setattr(
        "sys.argv",
        [
            "satellite-overpass-identification-tool",
            domain_arg,
            expected_domain,
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
    assert saw_credentials_call["value"] is True


def test_resolve_historical_tle_db_rejects_file_uri_scheme():
    """file:// URIs are intentionally unsupported for historical DB input."""
    with pytest.raises(ValueError) as exc_info:
        app_module.resolve_historical_tle_db("file:///tmp/historical.sqlite")

    assert str(exc_info.value) == "Unsupported historical TLE database URI scheme: file"
