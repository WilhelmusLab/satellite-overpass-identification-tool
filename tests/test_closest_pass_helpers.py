"""Integration tests for extracted closest-pass helpers."""

import datetime as dt
import re

import pytest
from skyfield.api import EarthSatellite, load, utc, wgs84

from satellite_overpass_identification_tool.app import (
    Direction,
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
        "distance" in pass_dict
        and "time" in pass_dict
        and "over_lat" in pass_dict
        and pass_dict.get("orbit_direction") in {Direction.ASCENDING, Direction.DESCENDING}
        for pass_dict in passes
    )

    # Validate expected direction around known Terra overpass windows.
    expected_windows = {
        Direction.DESCENDING: ["18:30", "20:09", "21:46", "23:25"],
        Direction.ASCENDING: ["00:22", "02:01", "03:39", "05:16"],
    }
    tolerance_minutes = 20

    def _minutes_since_midnight(clock_time: str) -> int:
        parsed = dt.datetime.strptime(clock_time, "%H:%M")
        return parsed.hour * 60 + parsed.minute

    def _pass_minutes(pass_dict: dict) -> int:
        time_token = pass_dict["time"].split(" ")[3]  # HH:MM:SS
        parsed = dt.datetime.strptime(time_token, "%H:%M:%S")
        return parsed.hour * 60 + parsed.minute

    def _circular_diff_minutes(a: int, b: int) -> int:
        diff = abs(a - b)
        return min(diff, 1440 - diff)

    for expected_direction, windows in expected_windows.items():
        direction_passes = [
            pass_dict
            for pass_dict in passes
            if pass_dict.get("orbit_direction") == expected_direction
        ]
        assert direction_passes, f"No passes found for {expected_direction.value} direction"

        for window in windows:
            target_minutes = _minutes_since_midnight(window)
            nearest_pass = min(
                direction_passes,
                key=lambda pass_dict: _circular_diff_minutes(target_minutes, _pass_minutes(pass_dict)),
            )
            nearest_delta = _circular_diff_minutes(target_minutes, _pass_minutes(nearest_pass))

            assert nearest_delta <= tolerance_minutes, (
                f"No {expected_direction.value} overpass found within {tolerance_minutes} minutes of {window}"
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

    closest_time = find_closest_pass(passes, direction=Direction.DESCENDING)
    assert closest_time
    assert re.fullmatch(r"\d{2}:\d{2}:\d{2}", closest_time)

    wrapper_time = get_closest_pass_for_satellite(
        satellite=terra_20250515_events["satellite"],
        aoi=terra_20250515_events["aoi"],
        t0=terra_20250515_events["t0"],
        t1=terra_20250515_events["t1"],
        direction=Direction.DESCENDING,
    )
    assert closest_time == wrapper_time
