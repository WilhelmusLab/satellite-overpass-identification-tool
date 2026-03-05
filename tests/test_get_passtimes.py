"""Integration tests for satellite overpass time retrieval."""

import os
import tempfile

import pytest

from satellite_overpass_identification_tool.app import get_passtimes, get_credentials, domain, _parsedate


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
    "start_date,end_date,lat,lon",
    [
        ("2001-01-01", "2001-01-31", 71, -129),
        ("2019-03-20", "2019-03-25", 71, -129),
    ],
    ids=["beaufort_sea: 2001-01", "beaufort_sea: 2019-03"],
)
def test_get_passtimes(credentials, start_date, end_date, lat, lon):
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
        
        # Should have header + at least some data rows (2 per day for aqua/terra)
        assert len(lines) > 1, "CSV should have header and data rows"
        
        # Verify header
        header = lines[0].strip()
        assert "date" in header.lower() or "satellite" in header.lower()