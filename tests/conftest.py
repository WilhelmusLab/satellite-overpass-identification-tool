"""Shared test fixtures for rate-limited Space-Track access."""

import time
from collections import deque

import pytest

import satellite_overpass_identification_tool.app as app_module


def _get_data_rate_limited(
    get_data_func,
    credentials,
    start_date,
    end_date,
    domain,
    request_timestamps,
    max_requests_per_minute=15,
    rate_limit_error_state=None,
):
    """Call get_Data while limiting estimated API requests to max_requests_per_minute.

    app_module.get_Data performs one login request and one combined request for both
    satellites, so we reserve 2 request slots for each call.
    """
    if rate_limit_error_state is not None and rate_limit_error_state["message"] is not None:
        raise RuntimeError(rate_limit_error_state["message"])

    requests_per_get_data_call = 2
    window_seconds = 60

    while True:
        now = time.monotonic()
        while request_timestamps and now - request_timestamps[0] >= window_seconds:
            request_timestamps.popleft()

        if len(request_timestamps) + requests_per_get_data_call <= max_requests_per_minute:
            break

        sleep_seconds = window_seconds - (now - request_timestamps[0])
        time.sleep(max(0.01, sleep_seconds))

    try:
        satellite_data = get_data_func(
            credentials=credentials,
            start_date=start_date,
            end_date=end_date,
            domain=domain,
        )
    except Exception as exc:
        message = str(exc)
        if rate_limit_error_state is not None and "rate limit" in message.lower():
            rate_limit_error_state["message"] = message
        raise

    request_timestamps.extend([time.monotonic()] * requests_per_get_data_call)
    return satellite_data


@pytest.fixture(scope="session")
def rate_limited_get_data():
    """Provide a shared rate-limited get_Data wrapper for integration tests."""
    request_timestamps = deque()
    rate_limit_error_state = {"message": None}
    original_get_data = app_module.get_Data

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
    """Route app.get_Data through the shared rate-limited wrapper for tests that request this fixture."""
    monkeypatch.setattr(app_module, "get_Data", rate_limited_get_data)


@pytest.fixture(scope="session")
def domain():
    """Domain to use for testing get_credentials and get_Data."""
    return "for-testing-only.space-track.org"


@pytest.fixture(scope="session")
def credentials(domain):
    """Get space-track.org credentials or skip tests."""
    username, password = app_module.get_credentials(domain, args=None)
    if username is None or password is None:
        pytest.skip(f"{domain} credentials not available")
    return username, password
