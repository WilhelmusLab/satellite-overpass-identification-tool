"""Tests for CLI entry point behavior."""

import pytest

from satellite_overpass_identification_tool.app import main


def test_no_args_prints_help_and_exits(monkeypatch, capsys):
    """Invoking main() with no CLI arguments prints help text and exits with status 0."""
    monkeypatch.setattr("sys.argv", ["satellite-overpass-identification-tool"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out
