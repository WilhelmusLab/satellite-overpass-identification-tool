import time


def _get_data_rate_limited(
    get_data_func,
    credentials,
    start_date,
    end_date,
    domain,
    request_timestamps,
    max_requests_per_minute=15,
    requests_per_get_data_call=2,
    window_seconds=60,
    rate_limit_error_state=None,
):
    """Call get_data while limiting estimated API requests to max_requests_per_minute.

    app.get_data performs one login request and one combined request for both
    satellites, so we reserve 2 request slots for each call.
    """
    if max_requests_per_minute < requests_per_get_data_call:
        raise ValueError(
            f"max_requests_per_minute ({max_requests_per_minute}) must be >= "
            f"requests_per_get_data_call ({requests_per_get_data_call})"
        )

    if rate_limit_error_state is not None:
        message = rate_limit_error_state.get("message")
        if message is not None:
            raise RuntimeError(message)

    while True:
        now = time.monotonic()
        while request_timestamps and now - request_timestamps[0] >= window_seconds:
            request_timestamps.popleft()

        if (
            len(request_timestamps) + requests_per_get_data_call
            <= max_requests_per_minute
        ):
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
