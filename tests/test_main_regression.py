"""Regression tests for CLI main entrypoint output."""

import csv
import sys

import pytest

import satellite_overpass_identification_tool.app as app_module


EXPECTED_ROWS_80N_105W_2025_05_15 = [
    {
        "date": "2025-05-15",
        "satellite": "aqua",
        "overpass_time": "2025-05-15T18:07:07Z",
    },
    {
        "date": "2025-05-15",
        "satellite": "terra",
        "overpass_time": "2025-05-15T20:08:03Z",
    },
]


@pytest.fixture
def credentials():
    """Get space-track.org credentials or skip the test."""
    username, password = app_module.get_credentials(app_module.domain, args=None)
    if username is None or password is None:
        pytest.skip("space-track.org credentials not available")
    return username, password


@pytest.mark.integration
def test_main_regression_2025_05_15_80n_105w(credentials, monkeypatch, tmp_path):
    """main() should emit the known CSV rows for 2025-05-15 at 80N, -105E."""
    username, password = credentials
    output_path = tmp_path / "overpass_regression.csv"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "satellite-overpass-identification-tool",
            "--SPACEUSER",
            username,
            "--SPACEPSWD",
            password,
            "--startdate",
            "2025-05-15",
            "--enddate",
            "2025-05-15",
            "--lat",
            "80",
            "--lon",
            "-105",
            "--csvoutpath",
            str(output_path),
        ],
    )

    app_module.main()

    with output_path.open("r", newline="") as csvfile:
        rows = list(csv.DictReader(csvfile))

    assert rows == EXPECTED_ROWS_80N_105W_2025_05_15


@pytest.mark.integration
def test_main_regression_directory_output_2025_05_15_80n_105w(credentials, monkeypatch, tmp_path):
    """main() should create the expected csv filename and contents when csvoutpath is a directory."""
    username, password = credentials
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "satellite-overpass-identification-tool",
            "--SPACEUSER",
            username,
            "--SPACEPSWD",
            password,
            "--startdate",
            "2025-05-15",
            "--enddate",
            "2025-05-15",
            "--lat",
            "80",
            "--lon",
            "-105",
            "--csvoutpath",
            str(output_dir),
        ],
    )

    app_module.main()

    csv_files = list(output_dir.glob("*.csv"))
    assert len(csv_files) == 1
    assert csv_files[0].name == "passtimes_lat80.0_lon-105.0_05152025_05162025.csv"

    with csv_files[0].open("r", newline="") as csvfile:
        rows = list(csv.DictReader(csvfile))

    assert rows == EXPECTED_ROWS_80N_105W_2025_05_15
