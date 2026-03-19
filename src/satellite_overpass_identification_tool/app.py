
"""Satellite overpass identification tool.

Authors:
- Simon Hatcher (2022)
- Timothy Divoll (2023)
- John Gerrard Holland (2026)

This module fetches Two-Line Element (TLE) history from space-track.org and computes closest
Aqua/Terra overpass times for a target location and date range.

Requirements:
- A stable internet connection
- space-track.org credentials provided via CLI arguments, environment
    variables, or ~/.netrc
"""

# Package imports.
import requests
import json
import datetime
from skyfield.api import wgs84, load, EarthSatellite, utc, Time
import numpy as np
import csv
import math
import argparse
import pathlib
from enum import Enum, IntEnum
from typing import cast
from satellite_overpass_identification_tool.credentials import get_credentials


class Direction(Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"

class PassEvent(IntEnum):
    RISE = 0
    OVERPASS = 1
    SET = 2


# Satellite configurations: NORAD catalog IDs and orbit direction for pass filtering
SATELLITES = {
    "aqua": {"norad_id": "27424", "direction": Direction.ASCENDING},
    "terra": {"norad_id": "25994", "direction": Direction.DESCENDING},
}
ID_SATELLITE_MAPPING = {config["norad_id"]: name for name, config in SATELLITES.items()}

netrc_message = f"""
[for-testing-only.]space-track.org SPACEUSER and SPACEPSWD can be set:
- on the command line,
- as environment variables,
- or in a .netrc file.

Add the following lines to a file named .netrc in your home directory, 
replacing USERNAME and PASSWORD with your space-track.org credentials:

machine space-track.org
        login USERNAME
        password PASSWORD

machine for-testing-only.space-track.org
        login USERNAME
        password PASSWORD


Ensure the file has the correct permissions, 
e.g., `chmod 600 ~/.netrc` on Unix systems
to keep your credentials secure.
"""

PASS_TIMES_DTYPE = np.dtype([
    ("date", "U10"),
    ("satellite", "U10"),
    ("overpass_time", "U20"),
])


def _rows_to_structured_array(rows):
    if not rows:
        return np.array([], dtype=PASS_TIMES_DTYPE)
    return np.array([tuple(row) for row in rows], dtype=PASS_TIMES_DTYPE)


def get_passtimes(start_date, end_date, lat, lon, SPACEUSER, SPACEPSWD, domain):
    siteCred = {"identity": SPACEUSER, "password": SPACEPSWD}
    print(f"Timeframe starts on {start_date}, and ends on {end_date}")
    print(f"Coordinates (x, y): ({lat}, {lon})")

    end_date_next = end_date + datetime.timedelta(days=1)

    satellite_data = get_Data(siteCred, start_date, end_date_next, domain)

    # Load in orbital mechanics tool timescale.
    ts = load.timescale()

    # Specify area of interest.
    aoi = wgs84.latlon(lat, lon)

    # Iterate from start_date through end_date, one day at a time.
    today = start_date

    # Collect rows in unfolded format: [date, satellite, overpass_time]
    rows = []

    # Loop through each day until the end date of interest is reached.
    while today < end_date_next:
        print(today)
        tomorrow = today + datetime.timedelta(days=1)

        # Get UTC time values of the start of today and the start of tomorrow.
        t0 = ts.from_datetime(datetime.datetime.combine(today, datetime.datetime.min.time(), tzinfo=utc))
        t1 = ts.from_datetime(datetime.datetime.combine(tomorrow, datetime.datetime.min.time(), tzinfo=utc))

        date_iso = today.isoformat()

        # Process each satellite
        for sat_name, sat_config in SATELLITES.items():
            data = satellite_data.get(sat_name, [])
            if not data:
                continue

            min_diff_index, _ = getclosestepoch(t0, data)
            tle_line1, tle_line2 = get_tli_lines(data[min_diff_index])
            satellite = EarthSatellite(tle_line1, tle_line2, sat_name.upper(), ts)

            closest_time = get_closest_pass_for_satellite(
                satellite, aoi, t0, t1, direction=sat_config["direction"]
            )
            if closest_time:
                rows.append([date_iso, sat_name, f"{date_iso}T{closest_time}Z"])

        today = tomorrow

    structured_array = _rows_to_structured_array(rows)
    return structured_array


# Write CSV of all pass information.
def csvwrite(startdate, enddate, lat, lon, rows, outpath, fields=["Date", "Aqua pass time", "Terra pass time"]):
    
    outpath_ = pathlib.Path(outpath)
    
    if outpath_.is_dir():
        csv_name = f"passtimes_lat{lat}_lon{lon}_{startdate.strftime('%Y%m%d')}_{enddate.strftime('%Y%m%d')}.csv"
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

def get_epochs(dataset) -> list[Time]:
    ts = load.timescale()
    times = []
    for item in dataset:
        dt = datetime.datetime.fromisoformat(item["EPOCH"]).replace(tzinfo=utc)
        time = ts.from_datetime(dt)
        times.append(time)
    return times


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




def _extract_spacetrack_error(payload):
    """Return Space-Track error text when payload contains an error entry."""
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])

    if isinstance(payload, list) and payload:
        first_item = payload[0]
        if isinstance(first_item, dict) and "error" in first_item:
            return str(first_item["error"])

    return None


def get_Data(credentials: dict, start_date, end_date, domain):
    """Fetch TLE data for all configured satellites.
    
    Returns:
        dict: Mapping of satellite name to TLE data list. Empty list if no data available.
    """
    
    norad_ids = ",".join([str(sat_config["norad_id"]) for sat_config in SATELLITES.values()])
    sat_names = ",".join(SATELLITES.keys())
    epoch_range = f"{start_date.isoformat()}--{end_date.isoformat()}"
    
    login_url = f"https://{domain}/ajaxauth/login"
    data_url = f"https://{domain}/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{norad_ids}/orderby/TLE_LINE1%20ASC/EPOCH/{epoch_range}/format/json"
    
    satellite_data = {sat_name: [] for sat_name in SATELLITES.keys()}

    with requests.Session() as session:
        # Log in with username and password.
        resp = session.post(login_url, data=credentials)
        if resp.status_code != 200:
            raise requests.HTTPError(
                "POST fail on login (status %s). Your username/password may be incorrect. "
                "Check the ~/.netrc file or environment variables and try again."
                % resp.status_code,
                response=resp,
            )
        resp = session.get(data_url)
        if resp.status_code != 200:
            print(f"Warning: Failed to fetch TLE data for {sat_names} (NORAD {norad_ids}): {resp}")
        
        payload = json.loads(resp.text)
        error_message = _extract_spacetrack_error(payload)
        if error_message is not None:
            raise RuntimeError(
                f"Space-Track API error for {sat_names} (NORAD {norad_ids}): {error_message}"
            )
        
    for item in payload:
        norad_id = item.get("NORAD_CAT_ID")
        sat_name = ID_SATELLITE_MAPPING[norad_id]
        satellite_data[sat_name].append(item)

    return satellite_data


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
            raise ValueError(f"Unexpected event type in block starting at index {i}: {list(raw_block)}") from exc

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
            {
                "rise_lat": riselat.degrees,
                "rise_lon": riselon.degrees,
                "distance": distance.km,
                "time": overpass_t,
                "over_lat": overlat.degrees,
                "over_lon": overlon.degrees,
                "set_lat": setlat.degrees,
                "set_lon": setlon.degrees,
                "orbit_direction": direction,
            }
        )
        i += 3

    return passes


def find_orbit_direction(satellite, overpass_t):
    delta_seconds = 30.
    seconds_per_day = 86400.
    delta_days = delta_seconds / seconds_per_day
    ts = overpass_t.ts
    before_overpass = ts.tt_jd(overpass_t.tt - delta_days)
    after_overpass = ts.tt_jd(overpass_t.tt + delta_days)
    before_lat, _ = wgs84.latlon_of(satellite.at(before_overpass))
    after_lat, _ = wgs84.latlon_of(satellite.at(after_overpass))
    before_lat_deg = cast(float, before_lat.degrees)
    after_lat_deg = cast(float, after_lat.degrees)
    direction = (
        Direction.ASCENDING
        if after_lat_deg > before_lat_deg
        else Direction.DESCENDING
    )
    return direction

def find_closest_pass(passes, direction=Direction.ASCENDING):
    """Return HH:MM:SS for the closest ascending/descending pass."""
    least_distance = math.inf
    closest_time = None
    target_direction = direction
    filtered_passes = [pass_dict for pass_dict in passes if pass_dict["orbit_direction"] == target_direction]

    for pass_dict in filtered_passes:
        if pass_dict["distance"] < least_distance:
            least_distance = pass_dict["distance"]
            closest_time = pass_dict["time"]
    closest_time_str = closest_time.utc_strftime("%H:%M:%S") if closest_time is not None else ""
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
    times, events = satellite.find_events(aoi, t0, t1, altitude_degrees=altitude_degrees)
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
             "This is intended for testing with a mock server and should not be changed for normal use."
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

    fields = ["date", "satellite", "overpass time"]
    rows = [[row["date"], row["satellite"], row["overpass_time"]] for row in passtimes]
    end_date_next = args.end_date + datetime.timedelta(days=1)
    csvwrite(args.start_date, end_date_next, args.lat, args.lon, rows, args.csvoutpath, fields=fields)


if __name__ == "__main__":
    main()
