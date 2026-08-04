"""Satellite overpass identification tool.

Authors:
- Simon Hatcher (2022)
- Timothy Divoll (2023)
- Carlos Paniagua (2024/2026)
- John Gerrard Holland (2026)

This module computes closest Aqua/Terra overpass times for a target location and
date range.

Supported TLE sources:
- Historical SQLite database (preferred), supplied as a local path, ``file://`` URI,
    or HTTP(S) URL.
- Space-Track ``gp_history`` API (fallback when no historical DB is provided).

Remote historical DBs are downloaded once and cached locally for repeat runs, with
an option to refresh the cache.

Credential behavior:
- Credentials are required for Space-Track API access and can be provided via
    ``--SPACEUSER``/``--SPACEPSWD``, environment variables, or ``~/.netrc``.

Centroid is the approximate point in the middle of your bounding-box area of
interest.
"""

import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from enum import Enum, IntEnum
from urllib.parse import unquote, urlparse

import numpy as np
import requests
from skyfield.api import Angle, EarthSatellite, Time, load, utc, wgs84

from .credentials import get_credentials, netrc_message

SECONDS_PER_DAY = 86400.0


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

    return np.array([tuple(row) for row in rows], dtype=PASS_TIMES_DTYPE)


def get_passtimes(
    start_date,
    end_date,
    lat,
    lon,
    SPACEUSER=None,
    SPACEPSWD=None,
    domain="www.space-track.org",
    historical_tle_db=None,
):
    """Compute closest Aqua and Terra overpass times for each day in a date range.

    A local historical SQLite TLE database takes precedence over the selected
    remote data source.

    Args:
        start_date: First date to process, inclusive.
        end_date: Final date to process, inclusive.
        lat: Area-of-interest latitude in degrees.
        lon: Area-of-interest longitude in degrees.
        SPACEUSER: Space-Track username, when using the Space-Track source.
        SPACEPSWD: Space-Track password, when using the Space-Track source.
        domain: Space-Track API domain.
        historical_tle_db: Optional SQLite historical TLE database path.

    Returns:
        A NumPy structured array with date, satellite, and overpass_time fields.
    """
    print(f"Timeframe starts on {start_date}, and ends on {end_date}")
    print(f"Coordinates (x, y): ({lat}, {lon})")

    end_date_next = end_date + datetime.timedelta(days=1)
    satellite_data = None

    # A local database takes precedence over either remote source.
    if historical_tle_db is not None:
        print(f"Using historical TLE database: {historical_tle_db}")

    else:
        site_credentials = {"identity": SPACEUSER, "password": SPACEPSWD}
        satellite_data = get_data(
            site_credentials,
            start_date,
            end_date_next,
            domain,
        )

    ts = load.timescale()
    aoi = wgs84.latlon(lat, lon)

    today = start_date
    tomorrow = start_date + datetime.timedelta(days=1)

    # Unfolded rows: [date, satellite, ISO8601 overpass time].
    rows = []

    while today != end_date_next:
        t0 = ts.utc(today)
        t1 = ts.utc(tomorrow)
        date_iso = str(today)

        for sat in SATELLITES:
            if historical_tle_db is not None:
                # Use the newest TLE whose epoch is at or before 00:00 UTC
                # at the beginning of this day.
                requested_datetime = datetime.datetime.combine(
                    today,
                    datetime.time.min,
                    tzinfo=utc,
                )

                try:
                    tle_epoch, tle_line1, tle_line2 = get_historical_tle(
                        historical_tle_db,
                        sat.norad_id,
                        requested_datetime,
                    )
                except LookupError as exc:
                    print(f"Warning: {exc}")
                    continue

                print(f"Using {sat.name} historical TLE from {tle_epoch} for {today}")

            else:
                data = satellite_data.get(sat.name, [])

                if not data:
                    print(f"Warning: no TLE data found for {sat.name}")
                    continue

                min_diff_index, _ = getclosestepoch(t0, data, ts=ts, sat_name=sat.name)
                tle_line1, tle_line2 = get_tli_lines(data[min_diff_index])

            satellite = EarthSatellite(
                tle_line1,
                tle_line2,
                sat.name.upper(),
                ts,
            )

            closest_time = get_closest_pass_for_satellite(
                satellite,
                aoi,
                t0,
                t1,
                direction=sat.direction,
            )

            if closest_time:
                rows.append([date_iso, sat.name, f"{date_iso}T{closest_time}Z"])

        today += datetime.timedelta(days=1)
        tomorrow = today + datetime.timedelta(days=1)

    return _rows_to_structured_array(rows)


def write_passtimes_csv(passtimes, outpath, start_date, end_date, lat, lon):
    """Write a pass-times structured array to a CSV file."""
    source_fields = ["date", "satellite", "overpass_time"]
    output_fields = ["date", "satellite", "overpass time"]

    rows = [tuple(row[field] for field in source_fields) for row in passtimes]

    # csvwrite historically treats enddate as exclusive for filename purposes.
    end_date_next = end_date + datetime.timedelta(days=1)

    csvwrite(
        start_date,
        end_date_next,
        lat,
        lon,
        rows,
        outpath,
        fields=output_fields,
    )


def convert_fields_mdy_folded_to_iso8601_unfolded(rows):
    """Convert folded legacy rows to unfolded ISO8601 rows.

    Examples:
        >>> convert_fields_mdy_folded_to_iso8601_unfolded([("03-31-2013", "11:50:20", "14:45:05"),])  # doctest: +NORMALIZE_WHITESPACE
        (['date', 'satellite', 'overpass time'],
         [['2013-03-31', 'aqua',  '2013-03-31T11:50:20Z'],
          ['2013-03-31', 'terra', '2013-03-31T14:45:05Z']])
    """
    new_fields = ["date", "satellite", "overpass time"]
    new_rows = []

    for row in rows:
        date_mm_dd_yyyy, aqua_time, terra_time = row
        month, day, year = map(int, date_mm_dd_yyyy.split("-"))
        date_yyyy_mm_dd = datetime.date(year, month, day)

        new_rows.append(
            [f"{date_yyyy_mm_dd}", "aqua", f"{date_yyyy_mm_dd}T{aqua_time}Z"]
        )
        new_rows.append(
            [f"{date_yyyy_mm_dd}", "terra", f"{date_yyyy_mm_dd}T{terra_time}Z"]
        )

    return new_fields, new_rows


def csvwrite(
    startdate,
    enddate,
    lat,
    lon,
    rows,
    outpath,
    fields=None,
):
    """Write rows to a CSV file."""
    if fields is None:
        fields = ["Date", "Aqua pass time", "Terra pass time"]

    outpath_path = pathlib.Path(outpath)

    if outpath_path.is_dir():
        csv_name = (
            f"passtimes_lat{lat}_lon{lon}_"
            f"{startdate.strftime('%m%d%Y')}_{enddate.strftime('%m%d%Y')}.csv"
        )
        filename = outpath_path / csv_name

    elif outpath_path.suffix.lower() == ".csv":
        filename = outpath_path

    else:
        raise IOError(f"Output path neither a directory nor a .csv file: {outpath}")

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerow(fields)
        csvwriter.writerows(rows)


def getclosestepoch(t0, dataset, ts=None, sat_name="satellite"):
    """Return the index and epoch of the TLE closest to ``t0``."""
    ts = ts or load.timescale()

    min_diff = float("inf")
    min_diff_index = 0
    min_diff_epoch = None

    for index, item in enumerate(dataset):
        line1, line2 = get_tli_lines(item)
        satellite = EarthSatellite(line1, line2, sat_name.upper(), ts)
        epoch = satellite.epoch
        diff = abs(t0 - epoch)

        if diff < min_diff:
            min_diff = diff
            min_diff_index = index
            min_diff_epoch = epoch

    return min_diff_index, min_diff_epoch


def get_historical_tle(db_path, norad_id, requested_datetime):
    """Return the most recent TLE at or before a requested UTC datetime.

    Args:
        db_path: Path to the historical SQLite TLE database.
        norad_id: NORAD catalog ID as a string or integer.
        requested_datetime: Time for which a TLE is needed.

    Returns:
        Tuple of ``(epoch_utc, line1, line2)``.

    Raises:
        LookupError: If no historical TLE exists before the requested time.
    """
    if requested_datetime.tzinfo is None:
        requested_datetime = requested_datetime.replace(tzinfo=utc)

    requested_iso = requested_datetime.isoformat()

    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT epoch_utc, line1, line2
            FROM tle_history
            WHERE norad_id = ?
              AND epoch_utc <= ?
            ORDER BY epoch_utc DESC
            LIMIT 1
            """,
            (int(norad_id), requested_iso),
        ).fetchone()

    if row is None:
        raise LookupError(
            f"No historical TLE found for NORAD {norad_id} at or before {requested_iso}"
        )

    return row


def _historical_tle_cache_dir():
    """Return the directory used to cache downloaded historical TLE databases."""
    cache_root = os.environ.get("XDG_CACHE_HOME")

    if cache_root:
        return pathlib.Path(cache_root) / "soit"

    return pathlib.Path.home() / ".cache" / "soit"


def _is_remote_tle_database(value):
    """Return True when value is a supported remote database URI."""
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https")


def _cached_database_path(database_uri):
    """Return a stable cache filename for a remote database URI."""
    parsed = urlparse(database_uri)
    uri_hash = hashlib.sha256(database_uri.encode("utf-8")).hexdigest()[:16]

    basename = pathlib.PurePosixPath(parsed.path).name
    basename = basename or "historical_tles.sqlite"

    # Ensure cache file looks like a SQLite DB even if the remote name does not.
    if not basename.endswith(".sqlite"):
        basename = f"{basename}.sqlite"

    return _historical_tle_cache_dir() / f"{uri_hash}_{basename}"


def _download_http_object(database_url, destination):
    """Download a public HTTP(S) database URL to destination."""
    with requests.get(database_url, stream=True, timeout=120) as response:
        response.raise_for_status()

        with open(destination, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)


def resolve_historical_tle_db(database_location, refresh=False):
    """Resolve a local DB path or download/cache a remote historical TLE database.

    Args:
        database_location: Local path or HTTP(S) URL.
        refresh: Download again even if a cached copy already exists.

    Returns:
        pathlib.Path to a local SQLite database file.

    Raises:
        FileNotFoundError: If a specified local database does not exist.
        ValueError: If the URI scheme is unsupported or malformed.
    """
    if database_location is None:
        return None

    database_location = str(database_location)

    # A regular local file path needs no download.
    if not _is_remote_tle_database(database_location):
        local_path = pathlib.Path(database_location).expanduser()

        if not local_path.is_file():
            raise FileNotFoundError(
                f"Historical TLE database does not exist or is not a file: {local_path}"
            )

        return local_path

    parsed = urlparse(database_location)

    # file:///path/to/database.sqlite is also supported.
    if parsed.scheme == "file":
        local_path = pathlib.Path(unquote(parsed.path)).expanduser()

        if not local_path.is_file():
            raise FileNotFoundError(
                f"Historical TLE database does not exist or is not a file: {local_path}"
            )

        return local_path

    cache_path = _cached_database_path(database_location)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.is_file() and cache_path.stat().st_size > 0 and not refresh:
        print(f"Using cached historical TLE database: {cache_path}")
        return cache_path

    print(f"Downloading historical TLE database from: {database_location}")

    # Download to a temporary file, then atomically move it into the cache.
    # This prevents an interrupted download from becoming the cached DB.
    temporary_file = tempfile.NamedTemporaryFile(
        prefix=f"{cache_path.name}.",
        suffix=".download",
        dir=cache_path.parent,
        delete=False,
    )
    temporary_path = pathlib.Path(temporary_file.name)
    temporary_file.close()

    try:
        if parsed.scheme in ("http", "https"):
            _download_http_object(database_location, temporary_path)

        else:
            raise ValueError(
                f"Unsupported historical TLE database URI scheme: {parsed.scheme}"
            )

        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise RuntimeError(
                f"Downloaded historical TLE database is empty: {database_location}"
            )

        os.replace(temporary_path, cache_path)
        cache_path.chmod(0o600)

        print(f"Cached historical TLE database at: {cache_path}")
        return cache_path

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def get_tli_lines(tle):
    """Extract TLE lines from a Space-Track JSON record."""
    return tle["TLE_LINE1"], tle["TLE_LINE2"]


def _extract_spacetrack_error(payload):
    """Return Space-Track error text when payload contains an error entry."""
    if isinstance(payload, dict) and "error" in payload:
        return str(payload["error"])

    if isinstance(payload, list) and payload:
        first_item = payload[0]
        if isinstance(first_item, dict) and "error" in first_item:
            return str(first_item["error"])

    return None


def _month_range(start_date, end_date):
    """Yield (year, month) pairs spanning the supplied date range."""
    start = datetime.date(start_date.year, start_date.month, 1)
    end = datetime.date(end_date.year, end_date.month, 1)

    current = start
    while current <= end:
        yield current.year, current.month

        if current.month == 12:
            current = datetime.date(current.year + 1, 1, 1)
        else:
            current = datetime.date(current.year, current.month + 1, 1)


def get_data(credentials, start_date, end_date, domain):
    """Fetch TLE data for all configured satellites from Space-Track."""
    epoch_range = f"{start_date.strftime('%Y-%m-%d')}--{end_date.strftime('%Y-%m-%d')}"
    norad_ids = ",".join(sat.norad_id for sat in SATELLITES)
    sat_names = ",".join(sat.name for sat in SATELLITES)

    login_url = f"https://{domain}/ajaxauth/login"
    data_url = (
        f"https://{domain}/basicspacedata/query/class/gp_history/"
        f"NORAD_CAT_ID/{norad_ids}/orderby/TLE_LINE1%20ASC/"
        f"EPOCH/{epoch_range}/format/json"
    )

    satellite_data = {sat.name: [] for sat in SATELLITES}

    with requests.Session() as session:
        response = session.post(login_url, data=credentials)

        if response.status_code != 200:
            raise requests.HTTPError(
                "Login failed for %s with status code: %s %s\n%s"
                % (
                    response.url,
                    response.status_code,
                    response.reason,
                    response.text,
                ),
                response=response,
            )

        print(
            f"Fetching TLE data for {sat_names} (NORAD {norad_ids}) "
            f"for epoch range {epoch_range} from {domain}..."
        )

        response = session.get(data_url)

        if response.status_code != 200:
            raise requests.HTTPError(
                "Data fetch failed for %s with status code: %s %s\n%s"
                % (
                    response.url,
                    response.status_code,
                    response.reason,
                    response.text,
                ),
                response=response,
            )

        payload = json.loads(response.text)
        error_message = _extract_spacetrack_error(payload)

        if error_message is not None:
            raise RuntimeError(
                f"Space-Track API error for {sat_names} "
                f"(NORAD {norad_ids}): {error_message}"
            )

    unexpected_norad_ids = set()

    for item in payload:
        norad_id = str(item.get("NORAD_CAT_ID", ""))
        sat = SATELLITES_FROM_NORAD_ID.get(norad_id)

        if sat is None:
            unexpected_norad_ids.add(norad_id or "<missing>")
            continue

        satellite_data[sat.name].append(item)

    if unexpected_norad_ids:
        expected = ", ".join(sorted(SATELLITES_FROM_NORAD_ID.keys()))
        found = ", ".join(sorted(unexpected_norad_ids))
        raise RuntimeError(
            "Space-Track response included unexpected NORAD IDs: "
            f"{found}. Expected only: {expected}."
        )

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
    """Build pass information from Skyfield RISE/OVERPASS/SET event streams."""
    passes = []
    difference = satellite - aoi
    index = 0

    expected_block = (
        PassEvent.RISE,
        PassEvent.OVERPASS,
        PassEvent.SET,
    )

    while index + 2 < len(events):
        raw_block = events[index : index + 3]

        try:
            event_block = tuple(PassEvent(int(event)) for event in raw_block)
        except ValueError as exc:
            raise ValueError(
                f"Unexpected event type in block starting at index {index}: "
                f"{list(raw_block)}"
            ) from exc

        # The time window may begin or end during a pass. Advance until the
        # normal RISE -> OVERPASS -> SET sequence is found.
        if event_block != expected_block:
            index += 1
            continue

        rise_t, overpass_t, set_t = times[index : index + 3]

        rise_geocentric = satellite.at(rise_t)
        overpass_geocentric = satellite.at(overpass_t)
        overpass_topocentric = difference.at(overpass_t)
        set_geocentric = satellite.at(set_t)

        rise_lat, rise_lon = wgs84.latlon_of(rise_geocentric)
        over_lat, over_lon = wgs84.latlon_of(overpass_geocentric)
        set_lat, set_lon = wgs84.latlon_of(set_geocentric)

        _, _, distance = overpass_topocentric.altaz()
        direction = find_orbit_direction(satellite, overpass_t)

        passes.append(
            OverpassInfo(
                rise_lat=rise_lat,
                rise_lon=rise_lon,
                distance=distance.km,
                time=overpass_t,
                over_lat=over_lat,
                over_lon=over_lon,
                set_lat=set_lat,
                set_lon=set_lon,
                direction=direction,
            )
        )

        index += 3

    return passes


def find_orbit_direction(satellite, overpass_t, delta_seconds=30.0):
    """Determine whether the orbit is ascending or descending at overpass time."""
    delta_days = delta_seconds / SECONDS_PER_DAY
    ts = overpass_t.ts

    before_overpass = ts.tt_jd(overpass_t.tt - delta_days)
    after_overpass = ts.tt_jd(overpass_t.tt + delta_days)

    before_lat, _ = wgs84.latlon_of(satellite.at(before_overpass))
    after_lat, _ = wgs84.latlon_of(satellite.at(after_overpass))

    if after_lat.arcminutes() > before_lat.arcminutes():
        return Direction.ASCENDING

    return Direction.DESCENDING


def find_closest_pass(passes, direction=Direction.ASCENDING):
    """Return HH:MM:SS for the closest pass in the requested direction."""
    closest_pass = min(
        (pass_info for pass_info in passes if pass_info.direction == direction),
        key=lambda pass_info: pass_info.distance,
        default=None,
    )

    if closest_pass is None:
        return ""

    return closest_pass.time.utc_strftime("%H:%M:%S")


def get_closest_pass_for_satellite(
    satellite,
    aoi,
    t0,
    t1,
    direction=Direction.ASCENDING,
    altitude_degrees=30,
):
    """Find the closest matching-direction pass for one satellite."""
    times, events = satellite.find_events(
        aoi,
        t0,
        t1,
        altitude_degrees=altitude_degrees,
    )

    passes = process_passes(
        satellite=satellite,
        aoi=aoi,
        events=events,
        times=times,
    )

    return find_closest_pass(passes, direction=direction)


def main():
    parser = argparse.ArgumentParser(
        description="Aqua and Terra Satellite Overpass Time Tool",
        epilog=netrc_message,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--SPACEUSER",
        "-u",
        type=str,
        help="Space-Track username",
    )
    parser.add_argument(
        "--SPACEPSWD",
        "-p",
        type=str,
        help="Space-Track password",
    )
    parser.add_argument(
        "--startdate",
        dest="start_date",
        type=datetime.date.fromisoformat,
        required=True,
        help="Start date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--enddate",
        dest="end_date",
        type=datetime.date.fromisoformat,
        required=True,
        help="End date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--centroid-lat",
        "--lat",
        metavar="lat",
        dest="lat",
        type=float,
        required=True,
        help="Latitude of bounding-box centroid",
    )
    parser.add_argument(
        "--centroid-lon",
        "--lon",
        metavar="lon",
        dest="lon",
        type=float,
        required=True,
        help="Longitude of bounding-box centroid",
    )
    parser.add_argument(
        "--csvoutpath",
        type=str,
        required=True,
        help="Output CSV file path, or directory in which to create one",
    )
    parser.add_argument(
        "--domain",
        "-d",
        type=str,
        default="www.space-track.org",
        help=(
            "Base domain for Space-Track API (default: %(default)s). "
            "Intended for testing with a mock server."
        ),
    )
    parser.add_argument(
        "--historical-tle-db",
        type=str,
        default="https://storage.googleapis.com/tle-db/aqua_terra_historical_tles_2004_2025.sqlite",
        help=(
            "Local SQLite historical TLE database path or an HTTP(S) URL. "
            "Remote databases are downloaded once and "
            "cached locally. Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--refresh-historical-tle-db",
        action="store_true",
        help=(
            "Re-download the historical TLE database even when a cached copy exists."
        ),
    )
    if len(sys.argv) == 1:
        parser.print_help()
        parser.exit(0)

    args = parser.parse_args()

    if args.end_date < args.start_date:
        raise SystemExit("Error: --enddate must be on or after --startdate.")

    if not -90.0 <= args.lat <= 90.0:
        raise SystemExit("Error: latitude must be between -90 and 90 degrees.")

    if not -180.0 <= args.lon <= 180.0:
        raise SystemExit("Error: longitude must be between -180 and 180 degrees.")

    # Local SQLite source overrides remote source selection and requires no
    # Space-Track credentials.
    if args.historical_tle_db is not None:
        try:
            args.historical_tle_db = resolve_historical_tle_db(
                args.historical_tle_db,
                refresh=args.refresh_historical_tle_db,
            )
        except Exception as exc:
            raise SystemExit(
                f"Error: unable to resolve historical TLE database: {exc}"
            ) from exc

        # A local/cached historical DB means Space-Track credentials are unnecessary.
        args.SPACEUSER = None
        args.SPACEPSWD = None

    else:
        args.SPACEUSER, args.SPACEPSWD = get_credentials(args.domain, args=args)

        if args.SPACEUSER is None or args.SPACEPSWD is None:
            print(netrc_message)
            raise SystemExit(
                f"Error: no credentials found for {args.domain}. "
                "Provide --SPACEUSER and --SPACEPSWD, set SPACEUSER and "
                "SPACEPSWD environment variables, or add credentials to ~/.netrc."
            )

    passtimes = get_passtimes(
        start_date=args.start_date,
        end_date=args.end_date,
        lat=args.lat,
        lon=args.lon,
        SPACEUSER=args.SPACEUSER,
        SPACEPSWD=args.SPACEPSWD,
        domain=args.domain,
        historical_tle_db=args.historical_tle_db,
    )

    write_passtimes_csv(
        passtimes=passtimes,
        outpath=args.csvoutpath,
        start_date=args.start_date,
        end_date=args.end_date,
        lat=args.lat,
        lon=args.lon,
    )


if __name__ == "__main__":
    main()
