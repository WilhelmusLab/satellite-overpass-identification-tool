"""Integration tests for satellite overpass time retrieval."""

import csv
import os
import tempfile
import time
from collections import deque
from datetime import datetime

import pytest

import satellite_overpass_identification_tool.app as app_module
from satellite_overpass_identification_tool.app import get_passtimes, get_credentials, domain, _parsedate


def _get_data_rate_limited(username, password, start_date, end_date, request_timestamps, max_requests_per_minute=15):
    """Call get_Data while limiting estimated API requests to max_requests_per_minute.

    app_module.get_Data performs one login request and one request per satellite,
    so we reserve 3 request slots for each call.
    """
    requests_per_get_data_call = 3
    window_seconds = 60

    while True:
        now = time.monotonic()
        while request_timestamps and now - request_timestamps[0] >= window_seconds:
            request_timestamps.popleft()

        if len(request_timestamps) + requests_per_get_data_call <= max_requests_per_minute:
            break

        sleep_seconds = window_seconds - (now - request_timestamps[0])
        time.sleep(max(0.01, sleep_seconds))

    satellite_data = app_module.get_Data(
        credentials={"identity": username, "password": password},
        start_date=start_date,
        end_date=end_date,
    )

    request_timestamps.extend([time.monotonic()] * requests_per_get_data_call)
    return satellite_data


# Skip if credentials are not available
@pytest.fixture
def credentials():
    """Get space-track.org credentials or skip the test."""
    username, password = get_credentials(domain, args=None)
    if username is None or password is None:
        pytest.skip("space-track.org credentials not available")
    return username, password


@pytest.mark.integration
@pytest.mark.parametrize(
    "region,start_date,end_date,lat,lon,expected_rows",
    [
        pytest.param("beaufort_sea", "2001-01-01", "2001-01-31", 71, -129, 31, id="beaufort_sea: 2001-01 (terra only)"),
        pytest.param("beaufort_sea", "2002-02-01", "2002-02-28", 71, -129, 28, id="beaufort_sea: 2002-02 (terra only)"),
        pytest.param("beaufort_sea", "2005-05-01", "2005-05-31", 71, -129, 62, id="beaufort_sea: 2005-05"),
        pytest.param("beaufort_sea", "2019-03-20", "2019-03-25", 71, -129, 12, id="beaufort_sea: 2019-03"),
        pytest.param("beaufort_sea", "2025-03-01", "2025-03-31", 71, -129, 62, id="beaufort_sea: 2025-03"),
        pytest.param("hudson_bay", "2010-07-01", "2010-07-31", 60, -83, 62, id="hudson_bay: 2010-07"),
        pytest.param("hudson_bay", "2018-08-15", "2018-08-21", 60, -83, 14, id="hudson_bay: 2018-08"),
        pytest.param("barents_sea", "2012-01-01", "2012-01-15", 75, 40, 30, id="barents_sea: 2012-01"),
        pytest.param("barents_sea", "2022-06-01", "2022-06-30", 75, 40, 60, id="barents_sea: 2022-06"),
        pytest.param("kara_sea", "2015-09-01", "2015-09-14", 77, 77, 28, id="kara_sea: 2015-09"),
        pytest.param("kara_sea", "2023-12-01", "2023-12-31", 77, 77, 62, id="kara_sea: 2023-12"),
    ],
)
def test_get_passtimes(credentials, region, start_date, end_date, lat, lon, expected_rows):
    """Load overpass times for given date range and coordinates."""
    username, password = credentials
    
    with tempfile.TemporaryDirectory() as tmpdir:
        csvoutpath = os.path.join(tmpdir, "overpass_times.csv")
        
        get_passtimes(
            start_date=_parsedate(start_date),
            end_date=_parsedate(end_date),
            csvoutpath=csvoutpath,
            lat=lat,
            lon=lon,
            SPACEUSER=username,
            SPACEPSWD=password,
        )
        
        # Verify output file was created
        assert os.path.exists(csvoutpath)
        
        # Verify the file has content (header + data rows)
        with open(csvoutpath) as f:
            lines = f.readlines()
        
        # Should have header + expected data rows
        assert len(lines) == expected_rows + 1, f"Expected {expected_rows} data rows + header, got {len(lines)} lines"
        
        # Verify header
        header = lines[0].strip()
        assert "date" in header.lower() or "satellite" in header.lower()


@pytest.mark.integration
@pytest.mark.parametrize(
    "region,date,lat,lon,expected_aqua,expected_terra",
    [
        # beaufort_sea tests (terra only - pre-Aqua)
        pytest.param("beaufort_sea", "2001-01-01", 71, -129, None, "2001-01-01T20:45:27Z", id="beaufort_sea: 2001-01-01 (terra only)"),
        pytest.param("beaufort_sea", "2002-02-01", 71, -129, None, "2002-02-01T20:59:37Z", id="beaufort_sea: 2002-02-01 (terra only)"),
        # beaufort_sea tests (both satellites)
        pytest.param("beaufort_sea", "2005-05-01", 71, -129, "2005-05-01T20:17:04Z", "2005-05-01T20:01:54Z", id="beaufort_sea: 2005-05-01"),
        pytest.param("beaufort_sea", "2019-03-23", 71, -129, "2019-03-23T20:08:47Z", "2019-03-23T21:28:12Z", id="beaufort_sea: 2019-03-23"),
        pytest.param("beaufort_sea", "2025-03-01", 71, -129, "2025-03-01T21:37:30Z", "2025-03-01T19:51:12Z", id="beaufort_sea: 2025-03-01"),
        # hudson_bay tests
        pytest.param("hudson_bay", "2005-06-07", 60, -83, "2005-06-07T18:53:00Z", "2005-06-07T17:05:01Z", id="hudson_bay: 2005-06-07"),
        pytest.param("hudson_bay", "2010-07-01", 60, -83, "2010-07-01T17:56:26Z", "2010-07-01T17:42:28Z", id="hudson_bay: 2010-07-01"),
        pytest.param("hudson_bay", "2018-08-15", 60, -83, "2018-08-15T18:02:11Z", "2018-08-15T17:49:58Z", id="hudson_bay: 2018-08-15"),
        # barents_sea tests
        pytest.param("barents_sea", "2012-01-01", 75, 40, "2012-01-01T08:24:42Z", "2012-01-01T09:42:43Z", id="barents_sea: 2012-01-01"),
        pytest.param("barents_sea", "2015-03-08", 75, 40, "2015-03-08T09:02:30Z", "2015-03-08T10:19:39Z", id="barents_sea: 2015-03-08"),
        pytest.param("barents_sea", "2022-06-01", 75, 40, "2022-06-01T08:40:00Z", "2022-06-01T09:56:23Z", id="barents_sea: 2022-06-01"),
        # kara_sea tests
        pytest.param("kara_sea", "2015-09-01", 77, 77, "2015-09-01T06:27:45Z", "2015-09-01T07:45:32Z", id="kara_sea: 2015-09-01"),
        pytest.param("kara_sea", "2020-12-25", 77, 77, "2020-12-25T05:50:55Z", "2020-12-25T08:45:21Z", id="kara_sea: 2020-12-25"),
        pytest.param("kara_sea", "2023-12-01", 77, 77, "2023-12-01T06:48:37Z", "2023-12-01T07:05:39Z", id="kara_sea: 2023-12-01"),
    ],
)
def test_get_passtimes_specific(credentials, region, date, lat, lon, expected_aqua, expected_terra):
    """Verify specific overpass times for a given date and coordinates."""
    username, password = credentials
    
    with tempfile.TemporaryDirectory() as tmpdir:
        csvoutpath = os.path.join(tmpdir, "overpass_times.csv")
        
        get_passtimes(
            start_date=_parsedate(date),
            end_date=_parsedate(date),
            csvoutpath=csvoutpath,
            lat=lat,
            lon=lon,
            SPACEUSER=username,
            SPACEPSWD=password,
        )
        
        with open(csvoutpath) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Extract rows by satellite
        aqua_rows = [r for r in rows if r["satellite"] == "aqua"]
        terra_rows = [r for r in rows if r["satellite"] == "terra"]
        
        # Verify expected row counts
        expected_rows = sum(x is not None for x in (expected_aqua, expected_terra))
        assert len(rows) == expected_rows, f"Expected {expected_rows} rows, got {len(rows)}"
        
        # Verify each satellite
        for expected, sat_rows, name in [
            (expected_aqua, aqua_rows, "aqua"),
            (expected_terra, terra_rows, "terra"),
        ]:
            if expected is not None:
                assert len(sat_rows) == 1, f"Expected 1 {name} overpass"
                assert sat_rows[0]["date"] == date
                assert sat_rows[0]["overpass time"] == expected, f"{name} time unexpected: {sat_rows[0]['overpass time']}"


@pytest.fixture(scope="module")
def validated_grid_data():
    """Fetch and cache one day of TLE data for the validated overpass grid."""
    username, password = get_credentials(domain, args=None)
    if username is None or password is None:
        pytest.skip("space-track.org credentials not available")

    date = "2025-05-15"
    start_date = _parsedate(date)
    end_date = _parsedate(date)
    end_date_next = app_module.getNextDay(end_date)

    request_timestamps = deque()
    satellite_data = _get_data_rate_limited(
        username=username,
        password=password,
        start_date=start_date,
        end_date=end_date_next,
        request_timestamps=request_timestamps,
        max_requests_per_minute=15,
    )

    for satellite_name in ("aqua", "terra"):
        sat_data = satellite_data.get(satellite_name, [])
        if not sat_data or "EPOCH" not in sat_data[0]:
            pytest.skip(
                f"{satellite_name} TLE data unavailable "
                "(likely query throttled by space-track.org)"
            )

    return {
        "username": username,
        "password": password,
        "satellite_data": satellite_data,
    }


OVERPASS_VALIDATION_CASES = [
    (
        "2025-05-15",
        80,
        -180.0,
        "aqua",
        "2025-05-15T23:02:58Z",
        "2025-05-15T23:02:28Z",
        "2025-05-15T23:03:28Z",
    ),
    (
        "2025-05-15",
        80,
        -180.0,
        "terra",
        "2025-05-15T00:24:44Z",
        "2025-05-15T00:24:14Z",
        "2025-05-15T00:25:14Z",
    ),
    (
        "2025-05-15",
        80,
        -165.0,
        "aqua",
        "2025-05-15T21:24:46Z",
        "2025-05-15T21:24:16Z",
        "2025-05-15T21:25:16Z",
    ),
    (
        "2025-05-15",
        80,
        -165.0,
        "terra",
        "2025-05-15T00:24:10Z",
        "2025-05-15T00:23:40Z",
        "2025-05-15T00:24:40Z",
    ),
    (
        "2025-05-15",
        80,
        -150.0,
        "aqua",
        "2025-05-15T21:24:10Z",
        "2025-05-15T21:23:40Z",
        "2025-05-15T21:24:40Z",
    ),
    (
        "2025-05-15",
        80,
        -150.0,
        "terra",
        "2025-05-15T23:25:09Z",
        "2025-05-15T23:24:39Z",
        "2025-05-15T23:25:39Z",
    ),
    (
        "2025-05-15",
        80,
        -135.0,
        "aqua",
        "2025-05-15T19:45:56Z",
        "2025-05-15T19:45:26Z",
        "2025-05-15T19:46:26Z",
    ),
    (
        "2025-05-15",
        80,
        -135.0,
        "terra",
        "2025-05-15T21:46:53Z",
        "2025-05-15T21:46:23Z",
        "2025-05-15T21:47:23Z",
    ),
    (
        "2025-05-15",
        80,
        -120.0,
        "aqua",
        "2025-05-15T18:07:44Z",
        "2025-05-15T18:07:14Z",
        "2025-05-15T18:08:14Z",
    ),
    (
        "2025-05-15",
        80,
        -120.0,
        "terra",
        "2025-05-15T20:08:35Z",
        "2025-05-15T20:08:05Z",
        "2025-05-15T20:09:05Z",
    ),
    (
        "2025-05-15",
        80,
        -105.0,
        "aqua",
        "2025-05-15T18:07:07Z",
        "2025-05-15T18:06:37Z",
        "2025-05-15T18:07:37Z",
    ),
    (
        "2025-05-15",
        80,
        -105.0,
        "terra",
        "2025-05-15T20:08:03Z",
        "2025-05-15T20:07:33Z",
        "2025-05-15T20:08:33Z",
    ),
    (
        "2025-05-15",
        80,
        -90.0,
        "aqua",
        "2025-05-15T16:28:54Z",
        "2025-05-15T16:28:24Z",
        "2025-05-15T16:29:24Z",
    ),
    (
        "2025-05-15",
        80,
        -90.0,
        "terra",
        "2025-05-15T18:29:46Z",
        "2025-05-15T18:29:16Z",
        "2025-05-15T18:30:16Z",
    ),
    (
        "2025-05-15",
        80,
        -75.0,
        "aqua",
        "2025-05-15T16:28:19Z",
        "2025-05-15T16:27:49Z",
        "2025-05-15T16:28:49Z",
    ),
    (
        "2025-05-15",
        80,
        -75.0,
        "terra",
        "2025-05-15T18:29:11Z",
        "2025-05-15T18:28:41Z",
        "2025-05-15T18:29:41Z",
    ),
    (
        "2025-05-15",
        80,
        -60.0,
        "aqua",
        "2025-05-15T14:50:05Z",
        "2025-05-15T14:49:35Z",
        "2025-05-15T14:50:35Z",
    ),
    (
        "2025-05-15",
        80,
        -60.0,
        "terra",
        "2025-05-15T16:50:55Z",
        "2025-05-15T16:50:25Z",
        "2025-05-15T16:51:25Z",
    ),
    (
        "2025-05-15",
        80,
        -45.0,
        "aqua",
        "2025-05-15T13:11:53Z",
        "2025-05-15T13:11:23Z",
        "2025-05-15T13:12:23Z",
    ),
    (
        "2025-05-15",
        80,
        -45.0,
        "terra",
        "2025-05-15T15:12:37Z",
        "2025-05-15T15:12:07Z",
        "2025-05-15T15:13:07Z",
    ),
    (
        "2025-05-15",
        80,
        -30.0,
        "aqua",
        "2025-05-15T13:11:16Z",
        "2025-05-15T13:10:46Z",
        "2025-05-15T13:11:46Z",
    ),
    (
        "2025-05-15",
        80,
        -30.0,
        "terra",
        "2025-05-15T15:12:04Z",
        "2025-05-15T15:11:34Z",
        "2025-05-15T15:12:34Z",
    ),
    (
        "2025-05-15",
        80,
        -15.0,
        "aqua",
        "2025-05-15T11:33:03Z",
        "2025-05-15T11:32:33Z",
        "2025-05-15T11:33:33Z",
    ),
    (
        "2025-05-15",
        80,
        -15.0,
        "terra",
        "2025-05-15T13:33:48Z",
        "2025-05-15T13:33:18Z",
        "2025-05-15T13:34:18Z",
    ),
    (
        "2025-05-15",
        80,
        0.0,
        "aqua",
        "2025-05-15T11:32:28Z",
        "2025-05-15T11:31:58Z",
        "2025-05-15T11:32:58Z",
    ),
    (
        "2025-05-15",
        80,
        0.0,
        "terra",
        "2025-05-15T13:33:13Z",
        "2025-05-15T13:32:43Z",
        "2025-05-15T13:33:43Z",
    ),
    (
        "2025-05-15",
        80,
        15.0,
        "aqua",
        "2025-05-15T09:54:13Z",
        "2025-05-15T09:53:43Z",
        "2025-05-15T09:54:43Z",
    ),
    (
        "2025-05-15",
        80,
        15.0,
        "terra",
        "2025-05-15T11:54:57Z",
        "2025-05-15T11:54:27Z",
        "2025-05-15T11:55:27Z",
    ),
    (
        "2025-05-15",
        80,
        30.0,
        "aqua",
        "2025-05-15T05:01:04Z",
        "2025-05-15T05:00:34Z",
        "2025-05-15T05:01:34Z",
    ),
    (
        "2025-05-15",
        80,
        30.0,
        "terra",
        "2025-05-15T10:16:39Z",
        "2025-05-15T10:16:09Z",
        "2025-05-15T10:17:09Z",
    ),
    (
        "2025-05-15",
        80,
        45.0,
        "aqua",
        "2025-05-15T08:15:25Z",
        "2025-05-15T08:14:55Z",
        "2025-05-15T08:15:55Z",
    ),
    (
        "2025-05-15",
        80,
        45.0,
        "terra",
        "2025-05-15T10:16:06Z",
        "2025-05-15T10:15:36Z",
        "2025-05-15T10:16:36Z",
    ),
    (
        "2025-05-15",
        80,
        60.0,
        "aqua",
        "2025-05-15T06:37:11Z",
        "2025-05-15T06:36:41Z",
        "2025-05-15T06:37:41Z",
    ),
    (
        "2025-05-15",
        80,
        60.0,
        "terra",
        "2025-05-15T08:37:50Z",
        "2025-05-15T08:37:20Z",
        "2025-05-15T08:38:20Z",
    ),
    (
        "2025-05-15",
        80,
        75.0,
        "aqua",
        "2025-05-15T04:59:00Z",
        "2025-05-15T04:58:30Z",
        "2025-05-15T04:59:30Z",
    ),
    (
        "2025-05-15",
        80,
        75.0,
        "terra",
        "2025-05-15T08:37:14Z",
        "2025-05-15T08:36:44Z",
        "2025-05-15T08:37:44Z",
    ),
    (
        "2025-05-15",
        80,
        90.0,
        "aqua",
        "2025-05-15T04:58:22Z",
        "2025-05-15T04:57:52Z",
        "2025-05-15T04:58:52Z",
    ),
    (
        "2025-05-15",
        80,
        90.0,
        "terra",
        "2025-05-15T06:58:59Z",
        "2025-05-15T06:58:29Z",
        "2025-05-15T06:59:29Z",
    ),
    (
        "2025-05-15",
        80,
        105.0,
        "aqua",
        "2025-05-15T03:20:10Z",
        "2025-05-15T03:19:40Z",
        "2025-05-15T03:20:40Z",
    ),
    (
        "2025-05-15",
        80,
        105.0,
        "terra",
        "2025-05-15T05:20:41Z",
        "2025-05-15T05:20:11Z",
        "2025-05-15T05:21:11Z",
    ),
    (
        "2025-05-15",
        80,
        120.0,
        "aqua",
        "2025-05-15T03:19:34Z",
        "2025-05-15T03:19:04Z",
        "2025-05-15T03:20:04Z",
    ),
    (
        "2025-05-15",
        80,
        120.0,
        "terra",
        "2025-05-15T05:20:08Z",
        "2025-05-15T05:19:38Z",
        "2025-05-15T05:20:38Z",
    ),
    (
        "2025-05-15",
        80,
        135.0,
        "aqua",
        "2025-05-15T01:41:20Z",
        "2025-05-15T01:40:50Z",
        "2025-05-15T01:41:50Z",
    ),
    (
        "2025-05-15",
        80,
        135.0,
        "terra",
        "2025-05-15T03:41:52Z",
        "2025-05-15T03:41:22Z",
        "2025-05-15T03:42:22Z",
    ),
    (
        "2025-05-15",
        80,
        150.0,
        "aqua",
        "2025-05-15T00:03:08Z",
        "2025-05-15T00:02:38Z",
        "2025-05-15T00:03:38Z",
    ),
    (
        "2025-05-15",
        80,
        150.0,
        "terra",
        "2025-05-15T03:41:16Z",
        "2025-05-15T03:40:46Z",
        "2025-05-15T03:41:46Z",
    ),
    (
        "2025-05-15",
        80,
        165.0,
        "aqua",
        "2025-05-15T00:02:31Z",
        "2025-05-15T00:02:01Z",
        "2025-05-15T00:03:01Z",
    ),
    (
        "2025-05-15",
        80,
        165.0,
        "terra",
        "2025-05-15T02:03:01Z",
        "2025-05-15T02:02:31Z",
        "2025-05-15T02:03:31Z",
    ),
    (
        "2025-05-15",
        80,
        180.0,
        "aqua",
        "2025-05-15T23:02:58Z",
        "2025-05-15T23:02:28Z",
        "2025-05-15T23:03:28Z",
    ),
    (
        "2025-05-15",
        80,
        180.0,
        "terra",
        "2025-05-15T00:24:44Z",
        "2025-05-15T00:24:14Z",
        "2025-05-15T00:25:14Z",
    ),
    (
        "2025-05-15",
        80,
        -175.3,
        "aqua",
        "2025-05-15T23:02:48Z",
        "2025-05-15T23:02:18Z",
        "2025-05-15T23:03:18Z",
    ),
    (
        "2025-05-15",
        80,
        -175.3,
        "terra",
        "2025-05-15T00:24:34Z",
        "2025-05-15T00:24:04Z",
        "2025-05-15T00:25:04Z",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "date,lat,lon,satellite,expected_time,earliest_time,latest_time",
    OVERPASS_VALIDATION_CASES,
)
def test_get_passtimes_validated_longitude_grid_parametrized(
    validated_grid_data,
    monkeypatch,
    date,
    lat,
    lon,
    satellite,
    expected_time,
    earliest_time,
    latest_time,
):
    """Validate each satellite overpass against expected and per-case time bounds."""
    username = validated_grid_data["username"]
    password = validated_grid_data["password"]
    satellite_data = validated_grid_data["satellite_data"]

    monkeypatch.setattr(app_module, "get_Data", lambda credentials, start_date, end_date: satellite_data)

    with tempfile.TemporaryDirectory() as tmpdir:
        filename = f"overpass_{satellite}_{str(lon).replace('-', 'm').replace('.', '_')}.csv"
        csvoutpath = os.path.join(tmpdir, filename)

        get_passtimes(
            start_date=_parsedate(date),
            end_date=_parsedate(date),
            csvoutpath=csvoutpath,
            lat=lat,
            lon=lon,
            SPACEUSER=username,
            SPACEPSWD=password,
        )

        with open(csvoutpath) as f:
            rows = list(csv.DictReader(f))

    sat_rows = [r for r in rows if r["satellite"] == satellite]
    assert len(sat_rows) == 1, f"Expected 1 {satellite} overpass for lon={lon}"
    assert sat_rows[0]["date"] == date
    assert sat_rows[0]["overpass time"] == expected_time

    earliest_dt = datetime.fromisoformat(earliest_time.replace("Z", "+00:00"))
    latest_dt = datetime.fromisoformat(latest_time.replace("Z", "+00:00"))
    observed_dt = datetime.fromisoformat(sat_rows[0]["overpass time"].replace("Z", "+00:00"))

    assert earliest_dt < latest_dt
    assert earliest_dt <= observed_dt <= latest_dt