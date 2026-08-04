"""Integration test for the default historical TLE DB CLI workflow."""

import csv
import shutil
import sys
from pathlib import Path

import pytest

import satellite_overpass_identification_tool.app as app_module


def _historical_db_cache_dir():
    cache_home = app_module.os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "soit"
    return Path.home() / ".cache" / "soit"


def _use_tmp_cache_home(monkeypatch, tmp_path):
    cache_home = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    return cache_home / "soit"


def _run_historical_db_flow(
    monkeypatch,
    tmp_path,
    output_filename,
    historical_tle_db=None,
    refresh_historical_tle_db=False,
):
    output_path = tmp_path / output_filename

    argv = [
        "satellite-overpass-identification-tool",
        "--startdate",
        "2024-01-01",
        "--enddate",
        "2024-01-05",
        "--lat",
        "40.7128",
        "--lon",
        "-74.0060",
        "--csvoutpath",
        str(output_path),
    ]

    if historical_tle_db is not None:
        argv.extend(["--historical-tle-db", str(historical_tle_db)])

    if refresh_historical_tle_db:
        argv.append("--refresh-historical-tle-db")

    monkeypatch.setattr(
        sys,
        "argv",
        argv,
    )

    app_module.main()

    with output_path.open("r", newline="") as csvfile:
        rows = list(csv.DictReader(csvfile))

    # One row per satellite (aqua/terra) per day in the requested range.
    assert len(rows) == 10
    assert {row["satellite"] for row in rows} == {"aqua", "terra"}
    assert rows[0]["date"] == "2024-01-01"
    assert rows[-1]["date"] == "2024-01-05"

    return output_path


@pytest.mark.integration
def test_main_http_historical_db_cold_then_warm_cache(monkeypatch, tmp_path):
    """HTTP default: first run populates cache, second run reuses cached DB."""
    _use_tmp_cache_home(monkeypatch, tmp_path)
    cache_dir = _historical_db_cache_dir()
    shutil.rmtree(cache_dir, ignore_errors=True)

    _run_historical_db_flow(monkeypatch, tmp_path, "overpasses_first.csv")

    cached_files = list(cache_dir.glob("*.sqlite"))
    assert len(cached_files) == 1
    first_cached_db = cached_files[0]
    assert first_cached_db.is_file()
    first_size = first_cached_db.stat().st_size
    first_mtime_ns = first_cached_db.stat().st_mtime_ns
    assert first_size > 0

    def _download_must_not_run(*_args, **_kwargs):
        raise AssertionError("Download function was called during warm-cache run")

    monkeypatch.setattr(app_module, "_download_http_object", _download_must_not_run)

    _run_historical_db_flow(monkeypatch, tmp_path, "overpasses_second.csv")

    cached_files_after = list(cache_dir.glob("*.sqlite"))
    assert cached_files_after == [first_cached_db]
    second_size = first_cached_db.stat().st_size
    second_mtime_ns = first_cached_db.stat().st_mtime_ns

    # No re-download should happen; cached artifact remains the same file bytes.
    assert second_size == first_size
    assert second_mtime_ns == first_mtime_ns


@pytest.mark.integration
def test_main_local_historical_db_path_skips_http_download(monkeypatch, tmp_path):
    """Explicit local DB path must bypass HTTP download logic."""
    _use_tmp_cache_home(monkeypatch, tmp_path)
    cache_dir = _historical_db_cache_dir()
    shutil.rmtree(cache_dir, ignore_errors=True)

    _run_historical_db_flow(monkeypatch, tmp_path, "overpasses_seed_cache.csv")

    cached_files = list(cache_dir.glob("*.sqlite"))
    assert len(cached_files) == 1
    local_db_path = cached_files[0]
    assert local_db_path.is_file()

    def _download_must_not_run(*_args, **_kwargs):
        raise AssertionError("HTTP download function was called for local DB path")

    monkeypatch.setattr(app_module, "_download_http_object", _download_must_not_run)

    _run_historical_db_flow(
        monkeypatch,
        tmp_path,
        "overpasses_local_path.csv",
        historical_tle_db=local_db_path,
    )
