"""Shared test fixtures for rate-limited Space-Track access."""

import time
from collections import deque

import pytest

import satellite_overpass_identification_tool.app as app_module


def _get_data_rate_limited(get_data_func, credentials, start_date, end_date, request_timestamps, max_requests_per_minute=15):
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

    satellite_data = get_data_func(
        credentials=credentials,
        start_date=start_date,
        end_date=end_date,
    )

    request_timestamps.extend([time.monotonic()] * requests_per_get_data_call)
    return satellite_data


@pytest.fixture(scope="session")
def rate_limited_get_data():
    """Provide a shared rate-limited get_Data wrapper for integration tests."""
    request_timestamps = deque()
    original_get_data = app_module.get_Data

    def _wrapper(credentials, start_date, end_date):
        return _get_data_rate_limited(
            get_data_func=original_get_data,
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
            request_timestamps=request_timestamps,
            max_requests_per_minute=15,
        )

    return _wrapper


@pytest.fixture(autouse=True)
def use_rate_limited_get_data(monkeypatch, rate_limited_get_data):
    """Route app.get_Data through the shared rate-limited wrapper for all tests."""
    monkeypatch.setattr(app_module, "get_Data", rate_limited_get_data)