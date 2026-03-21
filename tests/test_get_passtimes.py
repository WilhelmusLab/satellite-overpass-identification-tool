"""Integration tests for satellite overpass time retrieval."""

import csv
import os
import tempfile

import pytest

from satellite_overpass_identification_tool.app import get_passtimes, get_credentials, _parsedate


# Skip if credentials are not available
@pytest.fixture
def credentials(domain):
    """Get space-track.org credentials or skip the test."""
    username, password = get_credentials(domain, args=None)
    if username is None or password is None:
        pytest.skip(f"{domain} credentials not available")
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
def test_get_passtimes(credentials, domain, region, start_date, end_date, lat, lon, expected_rows):
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
            domain=domain,
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
def test_get_passtimes_specific(credentials, domain, region, date, lat, lon, expected_aqua, expected_terra):
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
            domain=domain,
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