"""Shared test fixtures for rate-limited Space-Track access."""

from collections import deque

import pytest

import satellite_overpass_identification_tool.app as app_module
from satellite_overpass_identification_tool.download import \
    _get_data_rate_limited


@pytest.fixture(scope="session")
def rate_limited_get_data():
    """Provide a shared rate-limited get_data wrapper for integration tests."""
    request_timestamps = deque()
    rate_limit_error_state = {"message": None}
    original_get_data = app_module.get_data

    def _wrapper(credentials, start_date, end_date, domain):
        return _get_data_rate_limited(
            get_data_func=original_get_data,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
            domain=domain,
            request_timestamps=request_timestamps,
            max_requests_per_minute=15,
            rate_limit_error_state=rate_limit_error_state,
        )

    return _wrapper


@pytest.fixture()
def use_rate_limited_get_data(monkeypatch, rate_limited_get_data):
    """Route app.get_data through the shared rate-limited wrapper for tests that request this fixture."""
    monkeypatch.setattr(app_module, "get_data", rate_limited_get_data)


@pytest.fixture(scope="session")
def domain():
    """Domain to use for testing get_credentials and get_data."""
    return "for-testing-only.space-track.org"


@pytest.fixture(scope="session")
def credentials(domain):
    """Get space-track.org credentials or skip tests."""
    username, password = app_module.get_credentials(domain, args=None)
    if username is None or password is None:
        pytest.skip(f"{domain} credentials not available")
    return username, password
