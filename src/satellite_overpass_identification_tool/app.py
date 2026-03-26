"""Satellite overpass identification tool.

Authors:
- Simon Hatcher (2022)
- Timothy Divoll (2023)
- John Gerrard Holland (2026)

This module fetches Two-Line Element (TLE) history from space-track.org and computes closest
Aqua/Terra overpass times for a target location and date range.

Centroid is the approximate point in the middle of your bounding box area of interest
Your www.space-track.org credentials (https://www.space-track.org/auth/createAccount for free account)
need to be:
- provided via --SPACEUSER and --SPACEPSWD command line arguments, or
- set as environment variables SPACEUSER and SPACEPSWD, or
- added to your ~/.netrc file in the format:
  machine www.space-track.org
      login your_username
      password your_password

"""

import argparse
import csv
import datetime
import json
import math
import pathlib
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import cast

import numpy as np

# Package imports.
import requests
from skyfield.api import Angle, EarthSatellite, Time, load, utc, wgs84

from .credentials import get_credentials, netrc_message


class Direction(Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"


class PassEvent(IntEnum):
    RISE = 0
    OVERPASS = 1
    SET = 2


@dataclass
class Satellite:
    name: str
    norad_id: str
    direction: Direction


SATELLITES = [
    Satellite(name="aqua", norad_id="27424", direction=Direction.ASCENDING),
    Satellite(name="terra", norad_id="25994", direction=Direction.DESCENDING),
]

SATELLITES_FROM_NAME = {sat.name: sat for sat in SATELLITES}
SATELLITES_FROM_NORAD_ID = {sat.norad_id: sat for sat in SATELLITES}

PASS_TIMES_DTYPE = np.dtype(
    [
        ("date", "U10"),
        ("satellite", "U10"),
        ("overpass_time", "U20"),
    ]
)


def _rows_to_structured_array(rows):
    if not rows:
        return np.array([], dtype=PASS_TIMES_DTYPE)
    structured_array = np.array([tuple(row) for row in rows], dtype=PASS_TIMES_DTYPE)
    return structured_array


def get_passtimes(start_date, end_date, lat, lon, SPACEUSER, SPACEPSWD, domain):
    siteCred = {"identity": SPACEUSER, "password": SPACEPSWD}
    print(f"Timeframe starts on {start_date}, and ends on {end_date}")
    print(f"Coordinates (x, y): ({lat}, {lon})")

    end_date_next = end_date + datetime.timedelta(days=1)

    satellite_data = get_data(siteCred, start_date, end_date_next, domain)

    # Load in orbital mechanics tool timescale.
    ts = load.timescale()

    # Specify area of interest.
    aoi = wgs84.latlon(lat, lon)

    # Define today and tomorrow.
    today = start_date
    tomorrow = start_date + datetime.timedelta(days=1)

    # Collect rows in unfolded format: [date, satellite, overpass_time]
    rows = []

    # Loop through each day until the end date of interest is reached.
    while today != end_date_next:
        # Get UTC time values of the start of today and the start of tomorrow.
        t0 = ts.utc(today)
        t1 = ts.utc(tomorrow)

        date_iso = str(today)

        # Process each satellite
        for sat in SATELLITES:
            data = satellite_data.get(sat.name, [])
            if not data:
                continue

            min_diff_index, _ = getclosestepoch(t0, data)
            tle_line1, tle_line2 = get_tli_lines(data[min_diff_index])
            satellite = EarthSatellite(tle_line1, tle_line2, sat.name.upper(), ts)

            closest_time = get_closest_pass_for_satellite(
                satellite, aoi, t0, t1, direction=sat.direction
            )
            if closest_time:
                rows.append([date_iso, sat.name, f"{date_iso}T{closest_time}Z"])

        today = today + datetime.timedelta(days=1)
        tomorrow = today + datetime.timedelta(days=1)

    structured_array = _rows_to_structured_array(rows)
    return structured_array


def write_passtimes_csv(passtimes, outpath, start_date, end_date, lat, lon):
    """Write a pass times structured array to a CSV file.

    Args:
        passtimes: Numpy structured array returned by :func:`get_passtimes`.
        outpath: Path to the output CSV file, or a directory in which to create
            one with an auto-generated name.
        start_date: Start date as ``[MM, DD, YYYY]`` (same value passed to
            :func:`get_passtimes`).
        end_date: End date as ``[MM, DD, YYYY]`` (same value passed to
            :func:`get_passtimes`).
        lat: Latitude of the area of interest.
        lon: Longitude of the area of interest.
    """
    source_fields = ["date", "satellite", "overpass_time"]
    output_fields = ["date", "satellite", "overpass time"]
    rows = [tuple(row[f] for f in source_fields) for row in passtimes]
    end_date_next = end_date + datetime.timedelta(days=1)
    csvwrite(start_date, end_date_next, lat, lon, rows, outpath, fields=output_fields)
    return None


def convert_fields_mdy_folded_to_iso8601_unfolded(rows):
    """Convert a row from [MM-DD-YYYY, UTC time (aqua), UTC time (terra)] to [YYYY-MM-DD, Satellite, ISO8601 datetime] format.

    Examples:
        >>> convert_fields_mdy_folded_to_iso8601_unfolded([("03-31-2013", "11:50:20", "14:45:05"),])  # doctest: +NORMALIZE_WHITESPACE
        (['date', 'satellite', 'overpass time'],
         [['2013-03-31', 'aqua',  '2013-03-31T11:50:20Z'],
          ['2013-03-31', 'terra', '2013-03-31T14:45:05Z']])

        >>> convert_fields_mdy_folded_to_iso8601_unfolded([("12-01-2609", "23:59:01", "00:00:00"),])  # doctest: +NORMALIZE_WHITESPACE
        (['date', 'satellite', 'overpass time'],
         [['2609-12-01', 'aqua',  '2609-12-01T23:59:01Z'],
          ['2609-12-01', 'terra', '2609-12-01T00:00:00Z']])


        >>> convert_fields_mdy_folded_to_iso8601_unfolded([
        ...     ("03-31-2013", "11:50:20", "14:45:05"),
        ...     ("04-01-2013", "11:52:20", "14:43:05"),
        ... ])  # doctest: +NORMALIZE_WHITESPACE
        (['date', 'satellite', 'overpass time'],
         [['2013-03-31', 'aqua',  '2013-03-31T11:50:20Z'],
          ['2013-03-31', 'terra', '2013-03-31T14:45:05Z'],
          ['2013-04-01', 'aqua',  '2013-04-01T11:52:20Z'],
          ['2013-04-01', 'terra', '2013-04-01T14:43:05Z']])


    """
    new_fields = ["date", "satellite", "overpass time"]
    new_rows = []
    for row in rows:
        date_mm_dd_yyyy, aqua_time, terra_time = row
        m, d, y = map(int, date_mm_dd_yyyy.split("-"))
        date_yyyy_mm_dd = datetime.date(y, m, d)

        new_rows.append(
            [f"{date_yyyy_mm_dd}", "aqua", f"{date_yyyy_mm_dd}T{aqua_time}Z"]
        )
        new_rows.append(
            [f"{date_yyyy_mm_dd}", "terra", f"{date_yyyy_mm_dd}T{terra_time}Z"]
        )

    return new_fields, new_rows


# Write CSV of all pass information.
def csvwrite(
    startdate,
    enddate,
    lat,
    lon,
    rows,
    outpath,
    fields=["Date", "Aqua pass time", "Terra pass time"],
):

    outpath_ = pathlib.Path(outpath)

    if outpath_.is_dir():
        csv_name = f"passtimes_lat{lat}_lon{lon}_{startdate.strftime('%m%d%Y')}_{enddate.strftime('%m%d%Y')}.csv"
        filename = outpath_ / pathlib.Path(csv_name)
    elif outpath_.suffix == ".csv":
        filename = outpath_
    else:
        msg = "Output path neither a directory nor a .csv file: %s" % outpath
        raise IOError(msg)

    with open(filename, "w", newline="") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(fields)
        csvwriter.writerows(rows)


def get_epochs(dataset):
    return [timestamp_to_utc(item["EPOCH"]) for item in dataset]


def getclosestepoch(t0, dataset):
    epochs = get_epochs(dataset)

    # sequentially compute the absolute difference between the epoch and t0
    # keeping track of the index and value of the minimum difference
    min_diff = float("inf")
    min_diff_index = 0
    for i, epoch in enumerate(epochs):
        diff = abs(t0 - epoch)
        if diff < min_diff:
            min_diff = diff
            min_diff_index = i

    return min_diff_index, epochs[min_diff_index]


def get_tli_lines(tle):
    line1, line2 = tle["TLE_LINE1"], tle["TLE_LINE2"]
    return line1, line2


def timestamp_to_utc(timestamp):
    ts = load.timescale()
    datetime_obj = datetime.datetime.fromisoformat(timestamp)
    datetime_obj_utc = datetime_obj.replace(tzinfo=utc)
    ts_utc_object = ts.utc(datetime_obj_utc)
    return ts_utc_object


def _extract_spacetrack_error(payload):
    """Return Space-Track error text when payload contains an error entry."""
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])

    if isinstance(payload, list) and payload:
        first_item = payload[0]
        if isinstance(first_item, dict) and "error" in first_item:
            return str(first_item["error"])

    return None


def get_data(credentials: dict, start_date, end_date, domain):
    """Fetch TLE data for all configured satellites.

    Returns:
        dict: Mapping of satellite name to TLE data list. Empty list if no data available.
    """
    epoch_range = f"{start_date.strftime('%Y-%m-%d')}--{end_date.strftime('%Y-%m-%d')}"
    norad_ids = ",".join([sat.norad_id for sat in SATELLITES])
    sat_names = ",".join([sat.name for sat in SATELLITES])
    login_url = f"https://{domain}/ajaxauth/login"
    data_url = f"https://{domain}/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{norad_ids}/orderby/TLE_LINE1%20ASC/EPOCH/{epoch_range}/format/json"

    satellite_data = {sat.name: [] for sat in SATELLITES}

    with requests.Session() as session:
        # Log in with username and password.
        resp = session.post(login_url, data=credentials)
        if resp.status_code != 200:
            raise requests.HTTPError(
                "Login failed for %s with status code: %s %s\n%s"
                % (resp.url, resp.status_code, resp.reason, resp.text),
                response=resp,
            )
        print(
            f"Fetching TLE data for {sat_names} (NORAD {norad_ids}) for epoch range {epoch_range} from {domain}..."
        )
        resp = session.get(data_url)
        if resp.status_code != 200:
            raise requests.HTTPError(
                "Data fetch failed for %s with status code: %s %s\n%s"
                % (resp.url, resp.status_code, resp.reason, resp.text),
                response=resp,
            )
        payload = json.loads(resp.text)
        error_message = _extract_spacetrack_error(payload)
        if error_message is not None:
            raise RuntimeError(
                f"Space-Track API error for {sat_names} (NORAD {norad_ids}): {error_message}"
            )

    for item in payload:
        norad_id = item.get("NORAD_CAT_ID")
        sat = SATELLITES_FROM_NORAD_ID[norad_id]
        satellite_data[sat.name].append(item)

    return satellite_data


@dataclass
class OverpassInfo:
    rise_lat: Angle
    rise_lon: Angle
    distance: float
    time: Time
    over_lat: Angle
    over_lon: Angle
    set_lat: Angle
    set_lon: Angle
    direction: Direction


def process_passes(satellite, aoi, events, times):
    """Build pass dictionaries from Skyfield event streams.

    Passes are parsed from consecutive RISE/OVERPASS/SET triplets.
    """
    passes = []
    difference = satellite - aoi
    i = 0
    expected_block = (PassEvent.RISE, PassEvent.OVERPASS, PassEvent.SET)

    while i + 2 < len(events):
        raw_block = events[i : i + 3]
        try:
            event_block = tuple(PassEvent(int(event)) for event in raw_block)
        except ValueError as exc:
            raise ValueError(
                f"Unexpected event type in block starting at index {i}: {list(raw_block)}"
            ) from exc

        # If the stream starts/ends mid-pass, advance one event until we re-sync.
        if event_block != expected_block:
            i += 1
            continue

        rise_t, overpass_t, set_t = times[i : i + 3]

        rise_geocentric = satellite.at(rise_t)
        overpass_geocentric = satellite.at(overpass_t)
        overpass_topocentric = difference.at(overpass_t)
        set_geocentric = satellite.at(set_t)

        riselat, riselon = wgs84.latlon_of(rise_geocentric)
        overlat, overlon = wgs84.latlon_of(overpass_geocentric)
        setlat, setlon = wgs84.latlon_of(set_geocentric)
        _, _, distance = overpass_topocentric.altaz()

        direction = find_orbit_direction(satellite, overpass_t)

        passes.append(
            OverpassInfo(
                rise_lat=riselat,
                rise_lon=riselon,
                distance=distance.km,
                time=overpass_t,
                over_lat=overlat,
                over_lon=overlon,
                set_lat=setlat,
                set_lon=setlon,
                direction=direction,
            )
        )
        i += 3

    return passes


def find_orbit_direction(satellite, overpass_t):
    delta_seconds = 30.0
    seconds_per_day = 86400.0
    delta_days = delta_seconds / seconds_per_day
    ts = overpass_t.ts
    before_overpass = ts.tt_jd(overpass_t.tt - delta_days)
    after_overpass = ts.tt_jd(overpass_t.tt + delta_days)
    before_lat, _ = wgs84.latlon_of(satellite.at(before_overpass))
    after_lat, _ = wgs84.latlon_of(satellite.at(after_overpass))
    before_lat_deg = cast(float, before_lat.degrees)
    after_lat_deg = cast(float, after_lat.degrees)
    direction = (
        Direction.ASCENDING if after_lat_deg > before_lat_deg else Direction.DESCENDING
    )
    return direction


def find_closest_pass(passes, direction=Direction.ASCENDING):
    """Return HH:MM:SS for the closest ascending/descending pass."""
    closest_pass = min(
        (p for p in passes if p.direction == direction),
        key=lambda p: p.distance,
        default=None,
    )
    closest_time = closest_pass.time if closest_pass is not None else None
    closest_time_str = (
        closest_time.utc_strftime("%H:%M:%S") if closest_time is not None else ""
    )
    return closest_time_str


def get_closest_pass_for_satellite(
    satellite,
    aoi,
    t0,
    t1,
    direction=Direction.ASCENDING,
    altitude_degrees=30,
):
    """Find the closest pass time for a single satellite.

    Args:
        satellite: EarthSatellite object
        aoi: Area of interest (wgs84.latlon)
        t0: Start time
        t1: End time
        direction: Whether to filter for ascending or descending passes
        altitude_degrees: Minimum altitude for pass detection

    Returns:
        str: Time of closest pass in HH:MM:SS format, or empty string if no pass found
    """
    times, events = satellite.find_events(
        aoi, t0, t1, altitude_degrees=altitude_degrees
    )
    passes = process_passes(satellite=satellite, aoi=aoi, events=events, times=times)
    closest_pass = find_closest_pass(passes, direction=direction)
    return closest_pass


def main():
    parser = argparse.ArgumentParser(
        description="Aqua and Terra Satellite Overpass time tool",
        epilog=netrc_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--SPACEUSER",
        "-u",
        type=str,
        help="space-track.org username",
    )
    parser.add_argument(
        "--SPACEPSWD",
        "-p",
        type=str,
        help="space-track.org password",
    )
    parser.add_argument(
        "--startdate",
        type=datetime.date.fromisoformat,
        dest="start_date",
        help="Start date in format YYYY-MM-DD",
    )
    parser.add_argument(
        "--enddate",
        type=datetime.date.fromisoformat,
        dest="end_date",
        help="End date in format YYYY-MM-DD",
    )
    parser.add_argument(
        "--centroid-lat",
        "--lat",
        metavar="lat",
        dest="lat",
        type=float,
        help="latitude of bounding box centroid",
    )
    parser.add_argument(
        "--centroid-lon",
        "--lon",
        metavar="lon",
        dest="lon",
        type=float,
        help="longitude of bounding box centroid",
    )
    parser.add_argument(
        "--csvoutpath",
        type=str,
        help="Path to output CSV file, or a directory, where the output should be written",
    )
    parser.add_argument(
        "--domain",
        "-d",
        type=str,
        default="www.space-track.org",
        help="Base domain for Space-Track API (default: %(default)s). "
        "This is intended for testing with a mock server and should not be changed for normal use.",
    )

    args = parser.parse_args()

    args.SPACEUSER, args.SPACEPSWD = get_credentials(args.domain, args=args)

    if args.SPACEUSER is None or args.SPACEPSWD is None:
        print(netrc_message)
        raise SystemExit(
            f"Error: No credentials found for {args.domain}. "
            "Provide --SPACEUSER and --SPACEPSWD, set SPACEUSER and SPACEPSWD "
            "environment variables, or add credentials to your ~/.netrc file."
        )

    if args.csvoutpath is None:
        raise SystemExit("Error: --csvoutpath is required")

    passtimes = get_passtimes(
        start_date=args.start_date,
        end_date=args.end_date,
        lat=args.lat,
        lon=args.lon,
        SPACEUSER=args.SPACEUSER,
        SPACEPSWD=args.SPACEPSWD,
        domain=args.domain,
    )

    write_passtimes_csv(
        passtimes=passtimes,
        outpath=args.csvoutpath,
        start_date=args.start_date,
        end_date=args.end_date,
        lat=args.lat,
        lon=args.lon,
    )

    return None


if __name__ == "__main__":
    main()
