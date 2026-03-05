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
def test_get_passtimes_january_2001(credentials):
    """Load overpass times for January 2001 at lat=71, lon=-129."""
    username, password = credentials
    
    start_date = _parsedate("2001-01-01")
    end_date = _parsedate("2001-01-31")
    lat = 71
    lon = -129
    
    with tempfile.TemporaryDirectory() as tmpdir:
        csvoutpath = os.path.join(tmpdir, "overpass_times.csv")
        
        get_passtimes(
            start_date=start_date,
            end_date=end_date,
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
