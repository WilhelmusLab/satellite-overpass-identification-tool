"""Integration tests for extracted closest-pass helpers."""

import datetime as dt
import re

import pytest
from skyfield.api import EarthSatellite, load, utc, wgs84

from satellite_overpass_identification_tool.app import (
    find_closest_pass,
    get_closest_pass_for_satellite,
    get_tli_lines,
    getclosestepoch,
    process_passes,
)


@pytest.fixture(scope="module")
def terra_20250515_events(rate_limited_get_data, credentials):
    """Build representative Terra events for 2025-05-15 at 80N, -120E."""
    username, password = credentials

    start_date = dt.date(2025, 5, 15)
    end_date = start_date + dt.timedelta(days=1)

    satellite_data = rate_limited_get_data(
        credentials={"identity": username, "password": password},
        start_date=start_date,
        end_date=end_date,
    )

    terra_data = satellite_data.get("terra", [])
    if not terra_data or "EPOCH" not in terra_data[0]:
        pytest.skip("terra TLE data unavailable (likely query throttled by space-track.org)")

    ts = load.timescale()
    aoi = wgs84.latlon(80, -120)
    t0 = ts.from_datetime(dt.datetime.combine(start_date, dt.time.min, tzinfo=utc))
    t1 = ts.from_datetime(dt.datetime.combine(end_date, dt.time.min, tzinfo=utc))

    min_diff_index, _ = getclosestepoch(t0, terra_data)
    tle_line1, tle_line2 = get_tli_lines(terra_data[min_diff_index])
    satellite = EarthSatellite(tle_line1, tle_line2, "TERRA", ts)

    times, events = satellite.find_events(aoi, t0, t1, altitude_degrees=30)
    if len(events) == 0:
        pytest.skip("No Terra events found for representative timeframe and location")

    return {
        "satellite": satellite,
        "aoi": aoi,
        "t0": t0,
        "t1": t1,
        "times": times,
        "events": events,
    }


@pytest.mark.integration
def test_process_passes_with_representative_terra_events(terra_20250515_events):
    """process_passes should return parsed overpass dictionaries for representative Terra events."""
    passes = process_passes(
        satellite=terra_20250515_events["satellite"],
        aoi=terra_20250515_events["aoi"],
        events=terra_20250515_events["events"],
        times=terra_20250515_events["times"],
    )

    assert isinstance(passes, list)
    assert passes
    assert any(
        "distance" in pass_dict and "time" in pass_dict and "over_lat" in pass_dict
        for pass_dict in passes
    )


@pytest.mark.integration
def test_find_closest_pass_with_representative_terra_events(terra_20250515_events):
    """find_closest_pass should return a Terra descending pass time for representative data."""
    passes = process_passes(
        satellite=terra_20250515_events["satellite"],
        aoi=terra_20250515_events["aoi"],
        events=terra_20250515_events["events"],
        times=terra_20250515_events["times"],
    )

    closest_time = find_closest_pass(passes, ascending=False)
    assert closest_time
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", closest_time)

    wrapper_time = get_closest_pass_for_satellite(
        satellite=terra_20250515_events["satellite"],
        aoi=terra_20250515_events["aoi"],
        t0=terra_20250515_events["t0"],
        t1=terra_20250515_events["t1"],
        ascending=False,
    )
    assert closest_time == wrapper_time
