
# Code developed by Simon Hatcher (2022)
# Adapted for use in a Cylc pipeline for IceFloeTracker by Timothy Divoll (2023)

# ACTION REQUIRED FROM YOU:
# 1. Update the following parameters in the `flow.cylc` file:

# startdate = YYYY-MM-DD
# enddate = YYYY-MM-DD
#
# centroid-x = DD.DDDD
# centoid-y = DD.DDDD

# Centroid is the approximate point in the middle of your bounding box area of interest
# Your www.space-track.org credentials (https://www.space-track.org/auth/createAccount for free account) need to be set as environment variables in .bash_profile or .zshrc or add to ENV VARS in Windows
# NOTE: PASSWORD FIELD IS NOT SECURE. DO NOT USE USER/PASSWORD DIRECTLY IN CONFIG FILES.

# 2. A stable internet connection is also required.

# Package imports.
import requests
import json
import datetime
from skyfield.api import wgs84, load, EarthSatellite
import numpy as np
import csv
import math
import argparse
import os
import pathlib
import netrc

# Domain constants for Space-Track.
SPACETRACK_BASE_DOMAIN = "space-track.org"
SPACETRACK_DEFAULT_DOMAIN = f"www.{SPACETRACK_BASE_DOMAIN}"

# Satellite configurations: NORAD catalog IDs and orbit direction for pass filtering
SATELLITES = {
    "aqua": {"norad_id": 27424, "ascending": True},
    "terra": {"norad_id": 25994, "ascending": False},
}
netrc_message = f"""
{SPACETRACK_BASE_DOMAIN} SPACEUSER and SPACEPSWD can be set:
- on the command line,
- as environment variables,
- or in a .netrc file.

Add the following lines to a file named .netrc in your home directory, 
replacing USERNAME and PASSWORD with your {SPACETRACK_BASE_DOMAIN} credentials:

machine {SPACETRACK_BASE_DOMAIN}
        login USERNAME
        password PASSWORD

Ensure the file has the correct permissions, 
e.g., `chmod 600 ~/.netrc` on Unix systems
to keep your credentials secure.
"""

# Define error.
class MyError(Exception):
    def __init___(self, args):
        Exception.__init__(
            self, "my exception was raised with arguments {0}".format(args)
        )
        self.args = args


def _parsedate(date):
    return datetime.datetime.strptime(date, "%Y-%m-%d").strftime("%m-%d-%Y").split("-")


def get_passtimes(start_date, end_date, csvoutpath, lat, lon, SPACEUSER, SPACEPSWD, domain=SPACETRACK_DEFAULT_DOMAIN):
    siteCred = {"identity": SPACEUSER, "password": SPACEPSWD}
    print(f"Outpath {csvoutpath}")
    print(f"Timeframe starts on {start_date}, and ends on {end_date}")
    print(f"Coordinates (x, y): ({lat}, {lon})")

    end_date_next = getNextDay(end_date)

    satellite_data = get_Data(siteCred, start_date, end_date_next, domain)

    # Load in orbital mechanics tool timescale.
    ts = load.timescale()

    # Specify area of interest.
    aoi = wgs84.latlon(lat, lon)

    # Define today and tomorrow.
    today = start_date
    tomorrow = getNextDay(start_date)

    # Collect rows in unfolded format: [date, satellite, overpass_time]
    rows = []

    # Loop through each day until the end date of interest is reached.
    while not np.array_equiv(today, end_date_next):
        # Get UTC time values of the start of today and the start of tomorrow.
        t0 = to_utc(today)
        t1 = to_utc(tomorrow)

        date_str = "-".join(today)
        m, d, y = map(int, date_str.split("-"))
        date_iso = str(datetime.date(y, m, d))

        # Process each satellite
        for sat_name, sat_config in SATELLITES.items():
            data = satellite_data.get(sat_name, [])
            if not data:
                continue

            min_diff_index, _ = getclosestepoch(t0, data)
            tle_line1, tle_line2 = get_tli_lines(data[min_diff_index])
            satellite = EarthSatellite(tle_line1, tle_line2, sat_name.upper(), ts)

            closest_time = get_closest_pass_for_satellite(
                satellite, aoi, t0, t1, ascending=sat_config["ascending"]
            )
            if closest_time:
                rows.append([date_iso, sat_name, f"{date_iso}T{closest_time}Z"])

        today = getNextDay(today)
        tomorrow = getNextDay(today)

    fields = ["date", "satellite", "overpass time"]
    csvwrite(start_date, end_date_next, lat, lon, rows, csvoutpath, fields=fields)

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
        
        new_rows.append([f"{date_yyyy_mm_dd}", "aqua", f"{date_yyyy_mm_dd}T{aqua_time}Z"])
        new_rows.append([f"{date_yyyy_mm_dd}", "terra", f"{date_yyyy_mm_dd}T{terra_time}Z"])
    
    return new_fields, new_rows


# Write CSV of all pass information.
def csvwrite(startdate, enddate, lat, lon, rows, outpath, fields=["Date", "Aqua pass time", "Terra pass time"]):
    
    outpath_ = pathlib.Path(outpath)
    
    if outpath_.is_dir():
        csv_name = f"passtimes_lat{lat}_lon{lon}_{''.join(startdate)}_{''.join(enddate)}.csv"
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


# Returns the date after a given date.
def getNextDay(date):
    month = int(date[0])
    year = int(date[2])
    day = int(date[1])
    monthDays = daysInMonth(month, year)

    nextmonth = month
    nextday = day
    nextyear = year

    if day == monthDays:
        nextday = 1
        nextmonth += 1
    else:
        nextday += 1
    if month == 12 and day == 31:
        nextyear += 1
        nextmonth = 1

    nextyearstr = str(nextyear)

    if nextday < 10:
        nextdaystr = "0" + str(nextday)
    else:
        nextdaystr = str(nextday)
    if nextmonth < 10:
        nextmonthstr = "0" + str(nextmonth)
    else:
        nextmonthstr = str(nextmonth)

    return [nextmonthstr, nextdaystr, nextyearstr]


# Returns the number of days in a certain month.
def daysInMonth(month, year):
    if month in {1, 3, 5, 7, 8, 10, 12}:
        return 31
    if month == 2:
        if year % 4 == 0:
            return 29
        return 28
    return 30


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
    # Split the timestamp into date and time components
    date_part, time_part = timestamp.split("T")

    # Split the date part into year, month, and day
    year, month, day = map(int, date_part.split("-"))

    # Split the time part into hour, minute, and second
    hour, minute, second = map(float, time_part.split(":"))

    # Pass the parsed components to ts.utc
    return ts.utc(year, month, day, hour, minute, second)


def to_utc(t):
    ts = load.timescale()
    return ts.utc(int(t[2]), int(t[0]), int(t[1]))


def get_Data(credentials: dict, start_date, end_date, domain=SPACETRACK_DEFAULT_DOMAIN):
    """Fetch TLE data for all configured satellites.
    
    Returns:
        dict: Mapping of satellite name to TLE data list. Empty list if no data available.
    """
    uriBase = f"https://{domain}"
    requestLogin = "/ajaxauth/login"
    
    epoch_range = f"{start_date[2]}-{start_date[0]}-{start_date[1]}--{end_date[2]}-{end_date[0]}-{end_date[1]}"

    with requests.Session() as session:
        # Log in with username and password.
        resp = session.post(uriBase + requestLogin, data=credentials)
        if resp.status_code != 200:
            raise MyError(
                resp, "POST fail on login. Your username/password may be incorrect. Check the ~/.netrc file or environment variables and try again."
            )

        satellite_data = {}
        for sat_name, sat_config in SATELLITES.items():
            norad_id = sat_config["norad_id"]
            resp = session.get(
                f"{uriBase}/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{norad_id}/orderby/TLE_LINE1%20ASC/EPOCH/{epoch_range}/format/json"
            )
            if resp.status_code != 200:
                print(f"Warning: Failed to fetch TLE data for {sat_name} (NORAD {norad_id}): {resp}")
                satellite_data[sat_name] = []
            else:
                satellite_data[sat_name] = json.loads(resp.text)

    return satellite_data


def get_closest_pass_for_satellite(satellite, aoi, t0, t1, ascending=True, altitude_degrees=30):
    """Find the closest pass time for a single satellite.
    
    Args:
        satellite: EarthSatellite object
        aoi: Area of interest (wgs84.latlon)
        t0: Start time
        t1: End time
        ascending: Whether to filter for ascending (True) or descending (False) passes
        altitude_degrees: Minimum altitude for pass detection
    
    Returns:
        str: Time of closest pass in HH:MM:SS format, or empty string if no pass found
    """
    def process_passes(satellite, events, times):
        passes = []
        pass_dict = {}

        for i, (event, ti) in enumerate(zip(events, times)):
            geocentric = satellite.at(ti)
            difference = satellite - aoi
            topocentric = difference.at(ti)

            if event == 0:  # Rise
                pass_dict = {}
                riselat, riselon = wgs84.latlon_of(geocentric)
                pass_dict["rise_lat"] = riselat.degrees
                pass_dict["rise_lon"] = riselon.degrees

            elif event == 1:  # Overpass
                alt, az, distance = topocentric.altaz()
                pass_dict["distance"] = distance.km
                pass_dict["time"] = ti.utc_strftime("%Y %b %d %H:%M:%S")
                overlat, overlon = wgs84.latlon_of(geocentric)
                pass_dict["over_lat"] = overlat.degrees
                pass_dict["over_lon"] = overlon.degrees

                # Handle edge case for first overpass without prior rise
                if i == 0:
                    pass_dict["rise_lat"] = float("nan")
                    pass_dict["rise_lon"] = float("nan")
                # Handle edge case for last overpass without subsequent set
                if i == len(events) - 1:
                    pass_dict["set_lat"] = float("nan")
                    pass_dict["set_lon"] = float("nan")
                    passes.append(pass_dict)

            else:  # Set
                setlat, setlon = wgs84.latlon_of(geocentric)
                pass_dict["set_lat"] = setlat.degrees
                pass_dict["set_lon"] = setlon.degrees
                passes.append(pass_dict)

        return passes

    def find_closest_pass(passes, ascending=True):
        least_distance = math.inf
        closest_time = ""

        for pass_dict in passes:
            # Skip incomplete passes (no overpass data)
            if "distance" not in pass_dict or "over_lat" not in pass_dict:
                continue
            
            if "rise_lat" in pass_dict and not np.isnan(pass_dict["rise_lat"]):
                is_ascending = (
                    (pass_dict["rise_lat"] < pass_dict["over_lat"])
                    if ascending
                    else (pass_dict["rise_lat"] > pass_dict["over_lat"])
                )
                if is_ascending and pass_dict["distance"] < least_distance:
                    least_distance = pass_dict["distance"]
                    closest_time = pass_dict["time"]
            elif "set_lat" in pass_dict:
                is_ascending = (
                    (pass_dict["set_lat"] > pass_dict["over_lat"])
                    if ascending
                    else (pass_dict["set_lat"] < pass_dict["over_lat"])
                )
                if is_ascending and pass_dict["distance"] < least_distance:
                    least_distance = pass_dict["distance"]
                    closest_time = pass_dict["time"]

        result = closest_time.split(" ")[3] if closest_time else ""
        return result

    times, events = satellite.find_events(aoi, t0, t1, altitude_degrees=altitude_degrees)
    passes = process_passes(satellite, events, times)
    closest_pass = find_closest_pass(passes, ascending=ascending)
    return closest_pass


def get_credentials(domain, args=None):
    """Get username and password from args, environment variables, or .netrc file.

    Checks for credentials in the following order:
    1. The ``args`` namespace (SPACEUSER and SPACEPSWD attributes)
    2. Environment variables ``SPACEUSER`` and ``SPACEPSWD``
    3. The ``~/.netrc`` file

    Args:
        domain: The domain name to look up credentials for.
        args: Optional argparse namespace with SPACEUSER and SPACEPSWD attributes.

    Returns:
        A tuple of (username, password). Either value may be None if not found.

    Examples:
        >>> import argparse
        >>> ns = argparse.Namespace(SPACEUSER="user1", SPACEPSWD="pass1")
        >>> get_credentials("example.com", args=ns)
        ('user1', 'pass1')

        When there aren't any environment variables or .netrc file, both username and password are None:
        >>> from unittest import mock
        >>> with mock.patch.dict(os.environ, clear=True):
        ...     get_credentials("example.com", args=None)
        (None, None)

    """
    username = None
    password = None

    # 1. Check args
    if args is not None:
        username = getattr(args, "SPACEUSER", None)
        password = getattr(args, "SPACEPSWD", None)

    # 2. Check environment variables
    if username is None:
        username = os.environ.get("SPACEUSER")
    if password is None:
        password = os.environ.get("SPACEPSWD")

    # 3. Check .netrc file
    if username is None or password is None:
        try:
            netrc_file = netrc.netrc()
            netrc_creds = netrc_file.authenticators(domain)
            # If no exact match found, fall back to the parent domain for
            # subdomains of space-track.org (e.g. www.space-track.org or
            # for-testing-only.space-track.org).
            if netrc_creds is None and domain.endswith(f".{SPACETRACK_BASE_DOMAIN}"):
                netrc_creds = netrc_file.authenticators(SPACETRACK_BASE_DOMAIN)
            if netrc_creds is not None:
                login, _, netrc_password = netrc_creds
                if username is None:
                    username = login
                if password is None:
                    password = netrc_password
        except (FileNotFoundError, netrc.NetrcParseError):
            pass

    return username, password


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
        type=_parsedate,
        dest="start_date",
        help="Start date in format YYYY-MM-DD",
    )
    parser.add_argument(
        "--enddate",
        type=_parsedate,
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
        type=str,
        default=SPACETRACK_DEFAULT_DOMAIN,
        help="Base domain for Space-Track API (default: %(default)s)",
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

    get_passtimes(**vars(args))


if __name__ == "__main__":
    main()
