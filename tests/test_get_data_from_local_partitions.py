import datetime as dt
import json

from satellite_overpass_identification_tool.app import get_data_from_gcs


def _write_partition(root, norad, year, month, rows):
    partition_dir = root / f"norad={norad}" / f"year={year:04d}" / f"month={month:02d}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    partition_path = partition_dir / "tle.jsonl"
    with open(partition_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_get_data_from_local_partition_path(tmp_path):
    start = dt.date(2025, 5, 1)
    end = dt.date(2025, 5, 31)

    _write_partition(
        tmp_path,
        "27424",
        2025,
        5,
        [
            {
                "NORAD_CAT_ID": "27424",
                "TLE_LINE1": "1 25544U 98067A   25135.50000000  .00010000  00000+0  10000-3 0  9990",
                "TLE_LINE2": "2 25544  51.6400 110.0000 0005000 120.0000 240.0000 15.50000000000000",
            },
            {
                "NORAD_CAT_ID": "99999",
                "TLE_LINE1": "1 25544U 98067A   25135.50000000  .00010000  00000+0  10000-3 0  9990",
                "TLE_LINE2": "2 25544  51.6400 110.0000 0005000 120.0000 240.0000 15.50000000000000",
            },
        ],
    )
    _write_partition(
        tmp_path,
        "25994",
        2025,
        5,
        [
            {
                "NORAD_CAT_ID": "25994",
                "TLE_LINE1": "1 25544U 98067A   25135.60000000  .00010000  00000+0  10000-3 0  9991",
                "TLE_LINE2": "2 25544  51.6400 111.0000 0005000 120.0000 240.0000 15.50000000000001",
            }
        ],
    )

    satellite_data = get_data_from_gcs(start, end, str(tmp_path))

    assert set(satellite_data) == {"aqua", "terra"}
    assert len(satellite_data["aqua"]) == 1
    assert len(satellite_data["terra"]) == 1
    assert satellite_data["aqua"][0]["NORAD_CAT_ID"] == "27424"
    assert satellite_data["terra"][0]["NORAD_CAT_ID"] == "25994"


def test_get_data_from_local_partition_file_url(tmp_path):
    start = dt.date(2025, 5, 1)
    end = dt.date(2025, 5, 31)

    _write_partition(
        tmp_path,
        "27424",
        2025,
        5,
        [
            {
                "NORAD_CAT_ID": "27424",
                "TLE_LINE1": "1 25544U 98067A   25135.50000000  .00010000  00000+0  10000-3 0  9990",
                "TLE_LINE2": "2 25544  51.6400 110.0000 0005000 120.0000 240.0000 15.50000000000000",
            }
        ],
    )

    satellite_data = get_data_from_gcs(start, end, tmp_path.as_uri())

    assert len(satellite_data["aqua"]) == 1
