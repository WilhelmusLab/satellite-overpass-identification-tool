"""Unit tests for API error handling around get_Data and rate-limited wrappers."""

from collections import deque

import pytest
import datetime as dt

import conftest as test_conftest
import satellite_overpass_identification_tool.app as app_module


def test_get_data_raises_when_payload_contains_error(monkeypatch, domain):
    """get_Data should raise with the API message when response payload starts with error."""

    class _Response:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, data):
            return _Response(200, "{}")

        def get(self, url):
            return _Response(200, '[{"error": "You\'ve violated your query rate limit."}]')

    monkeypatch.setattr(app_module.requests, "Session", lambda: _Session())

    with pytest.raises(RuntimeError, match="rate limit"):
        app_module.get_Data(
            credentials={"identity": "user", "password": "pass"},
            start_date=dt.date(2025, 5, 15),
            end_date=dt.date(2025, 5, 16),
            domain=domain
        )


def test_rate_limited_helper_short_circuits_after_rate_limit_error(domain):
    """After a rate-limit error, helper should raise immediately without new API calls."""
    call_count = {"value": 0}

    def _always_rate_limited(**kwargs):
        call_count["value"] += 1
        raise RuntimeError("query rate limit exceeded")

    error_state = {"message": None}
    request_timestamps = deque()

    with pytest.raises(RuntimeError, match="rate limit"):
        test_conftest._get_data_rate_limited(
            get_data_func=_always_rate_limited,
            credentials={"identity": "user", "password": "pass"},
            start_date=dt.date(2025, 5, 15),
            end_date=dt.date(2025, 5, 16),
            domain=domain,
            request_timestamps=request_timestamps,
            max_requests_per_minute=15,
            rate_limit_error_state=error_state,
        )

    assert call_count["value"] == 1
    assert error_state["message"] is not None

    with pytest.raises(RuntimeError, match="rate limit"):
        test_conftest._get_data_rate_limited(
            get_data_func=_always_rate_limited,
            credentials={"identity": "user", "password": "pass"},
            start_date=dt.date(2025, 5, 15),
            end_date=dt.date(2025, 5, 16),
            domain=domain,
            request_timestamps=request_timestamps,
            max_requests_per_minute=15,
            rate_limit_error_state=error_state,
        )

    assert call_count["value"] == 1
