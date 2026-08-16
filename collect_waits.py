import csv
import os
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ============================================================
# MNSSHP MAGIC KINGDOM WAIT-TIME + WEATHER TRACKER
# ============================================================

MAGIC_KINGDOM_ID = "75ea578a-adc8-4116-a54d-dccb60765ef9"

WAIT_API_URL = (
    f"https://api.themeparks.wiki/v1/entity/"
    f"{MAGIC_KINGDOM_ID}/live"
)

# Approximate Magic Kingdom coordinates
MAGIC_KINGDOM_LAT = 28.4177
MAGIC_KINGDOM_LON = -81.5812

WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"

DATA_FILE = Path("data/magic_kingdom_waits.csv")

EASTERN = ZoneInfo("America/New_York")


# ------------------------------------------------------------
# MNSSHP NIGHTS WE ARE COLLECTING BEFORE SEPTEMBER 4
# August 15 remains a TEST NIGHT only.
# ------------------------------------------------------------

MNSSHP_DATES = {
    "2026-08-15",  # TEST NIGHT - exclude from MNSSHP analysis
    "2026-08-18",
    "2026-08-21",
    "2026-08-23",
    "2026-08-25",
    "2026-08-28",
    "2026-08-30",
    "2026-09-01",
}


# ------------------------------------------------------------
# FINAL CSV COLUMNS
# ------------------------------------------------------------

FIELDNAMES = [
    "snapshot_time",
    "party_date",
    "period",
    "ride_id",
    "ride_name",
    "status",
    "posted_wait_minutes",
    "source_last_updated",

    # Weather
    "weather_observed_time",
    "temperature_f",
    "feels_like_f",
    "humidity_pct",
    "precip_probability_pct",
    "precipitation_in",
    "rain_in",
    "showers_in",
    "weather_code",
    "wind_mph",
    "wind_gust_mph",
]


def should_collect(now):
    """
    Only collect:
      - On one of our selected dates
      - Between 4:00 PM and midnight Eastern
    """

    date_string = now.strftime("%Y-%m-%d")

    if date_string not in MNSSHP_DATES:
        print(f"{date_string} is not a collection date.")
        return False

    if now.hour < 16:
        print("Before 4:00 PM Eastern. No collection needed.")
        return False

    return True


def determine_period(now):
    """
    PRE_PARTY  = 4:00 PM - 5:59 PM
    TRANSITION = 6:00 PM - 6:59 PM
    PARTY      = 7:00 PM - midnight
    """

    if now.hour < 18:
        return "PRE_PARTY"

    if now.hour < 19:
        return "TRANSITION"

    return "PARTY"


def get_posted_wait(live_item):
    """
    Extract standby posted wait.
    """

    queue = live_item.get("queue")

    if not queue:
        return None

    standby = queue.get("STANDBY")

    if not standby:
        return None

    return standby.get("waitTime")


def get_weather():
    """
    Pull current weather conditions for Magic Kingdom.

    Open-Meteo current conditions are based on high-frequency
    weather model data and work well with our 15-minute snapshots.
    """

    params = {
        "latitude": MAGIC_KINGDOM_LAT,
        "longitude": MAGIC_KINGDOM_LON,

        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation_probability",
            "precipitation",
            "rain",
            "showers",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
        ]),

        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "America/New_York",
    }

    response = requests.get(
        WEATHER_API_URL,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "MNSSHP-Wait-Tracker/1.0"
        }
    )

    response.raise_for_status()

    payload = response.json()

    current = payload.get("current", {})

    weather = {
        "weather_observed_time": current.get("time"),
        "temperature_f": current.get("temperature_2m"),
        "feels_like_f": current.get("apparent_temperature"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "precip_probability_pct": current.get(
            "precipitation_probability"
        ),
        "precipitation_in": current.get("precipitation"),
        "rain_in": current.get("rain"),
        "showers_in": current.get("showers"),
        "weather_code": current.get("weather_code"),
        "wind_mph": current.get("wind_speed_10m"),
        "wind_gust_mph": current.get("wind_gusts_10m"),
    }

    return weather


def upgrade_existing_csv():
    """
    Our original CSV did not contain weather columns.

    This automatically upgrades it while preserving all
    previously collected ride data.

    Old rows receive blank weather fields.
    """

    if not DATA_FILE.exists():
        return

    with DATA_FILE.open(
        "r",
        newline="",
        encoding="utf-8"
    ) as infile:

        reader = csv.DictReader(infile)

        existing_fields = reader.fieldnames or []

        # Already upgraded
        if existing_fields == FIELDNAMES:
            return

        old_rows = list(reader)

    print("Upgrading existing CSV to include weather fields.")

    with DATA_FILE.open(
        "w",
        newline="",
        encoding="utf-8"
    ) as outfile:

        writer = csv.DictWriter(
            outfile,
            fieldnames=FIELDNAMES
        )

        writer.writeheader()

        for old_row in old_rows:

            upgraded_row = {}

            for field in FIELDNAMES:
                upgraded_row[field] = old_row.get(field, "")

            writer.writerow(upgraded_row)

    print(
        f"CSV upgrade complete. Preserved "
        f"{len(old_rows)} existing records."
    )


def collect_waits():

    now = datetime.now(EASTERN)

    if not should_collect(now):
        return

    period = determine_period(now)

    print(
        f"Collecting Magic Kingdom data at "
        f"{now.isoformat()} [{period}]"
    )

    # --------------------------------------------------------
    # Pull current weather once per snapshot
    # --------------------------------------------------------

    try:
        weather = get_weather()

        print(
            f"Weather: {weather['temperature_f']} F, "
            f"feels like {weather['feels_like_f']} F, "
            f"precip probability "
            f"{weather['precip_probability_pct']}%"
        )

    except Exception as exc:

        # A weather failure should NOT stop ride collection.
        print(f"WARNING: Weather collection failed: {exc}")

        weather = {
            "weather_observed_time": None,
            "temperature_f": None,
            "feels_like_f": None,
            "humidity_pct": None,
            "precip_probability_pct": None,
            "precipitation_in": None,
            "rain_in": None,
            "showers_in": None,
            "weather_code": None,
            "wind_mph": None,
            "wind_gust_mph": None,
        }

    # --------------------------------------------------------
    # Pull Magic Kingdom attraction data
    # --------------------------------------------------------

    response = requests.get(
        WAIT_API_URL,
        timeout=30,
        headers={
            "User-Agent": "MNSSHP-Wait-Tracker/1.0"
        }
    )

    response.raise_for_status()

    payload = response.json()

    live_data = payload.get("liveData", [])

    # --------------------------------------------------------
    # Prepare data folder / upgrade old CSV
    # --------------------------------------------------------

    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    upgrade_existing_csv()

    file_exists = DATA_FILE.exists()

    rows = []

    # --------------------------------------------------------
    # Build attraction rows
    # --------------------------------------------------------

    for item in live_data:

        if item.get("entityType") != "ATTRACTION":
            continue

        row = {
            "snapshot_time": now.isoformat(),
            "party_date": now.strftime("%Y-%m-%d"),
            "period": period,
            "ride_id": item.get("id"),
            "ride_name": item.get("name"),
            "status": item.get("status"),
            "posted_wait_minutes": get_posted_wait(item),
            "source_last_updated": item.get("lastUpdated"),

            "weather_observed_time":
                weather["weather_observed_time"],

            "temperature_f":
                weather["temperature_f"],

            "feels_like_f":
                weather["feels_like_f"],

            "humidity_pct":
                weather["humidity_pct"],

            "precip_probability_pct":
                weather["precip_probability_pct"],

            "precipitation_in":
                weather["precipitation_in"],

            "rain_in":
                weather["rain_in"],

            "showers_in":
                weather["showers_in"],

            "weather_code":
                weather["weather_code"],

            "wind_mph":
                weather["wind_mph"],

            "wind_gust_mph":
                weather["wind_gust_mph"],
        }

        rows.append(row)

    # --------------------------------------------------------
    # Append snapshot
    # --------------------------------------------------------

    with DATA_FILE.open(
        "a",
        newline="",
        encoding="utf-8"
    ) as csvfile:

        writer = csv.DictWriter(
            csvfile,
            fieldnames=FIELDNAMES
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)

    print(
        f"SUCCESS: Saved {len(rows)} attraction records "
        f"with weather to {DATA_FILE}"
    )


if __name__ == "__main__":
    collect_waits()
