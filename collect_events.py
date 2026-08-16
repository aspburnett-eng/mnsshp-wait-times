import csv
import os
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MAGIC_KINGDOM_ID = "75ea578a-adc8-4116-a54d-dccb60765ef9"

API_URL = (
    f"https://api.themeparks.wiki/v1/entity/"
    f"{MAGIC_KINGDOM_ID}/live"
)

DATA_FILE = Path("data/party_events.csv")

EASTERN = ZoneInfo("America/New_York")

COLLECTION_DATES = {
    "2026-08-15",  # TEST NIGHT - remove after testing
    "2026-08-18",
    "2026-08-21",
    "2026-08-23",
    "2026-08-25",
    "2026-08-28",
    "2026-08-30",
    "2026-09-01",
}

FIELDNAMES = [
    "snapshot_time",
    "party_date",
    "event_id",
    "event_name",
    "event_type",
    "status",
    "show_start_time",
    "show_end_time",
    "source_last_updated",
]


def should_collect(now):
    date_string = now.strftime("%Y-%m-%d")

    if date_string not in COLLECTION_DATES:
        print(f"{date_string} is not an event collection date.")
        return False

    return True


def normalize_time(value):
    if not value:
        return None

    return value


def collect_events():
    now = datetime.now(EASTERN)

    if not should_collect(now):
        return

    print(
        f"Collecting Magic Kingdom entertainment schedule "
        f"at {now.isoformat()}"
    )

    response = requests.get(
        API_URL,
        timeout=30,
        headers={
            "User-Agent": "MNSSHP-Wait-Tracker/1.0"
        },
    )

    response.raise_for_status()

    payload = response.json()

    live_data = payload.get("liveData", [])

    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    rows = []

    for item in live_data:

        entity_type = item.get("entityType")

        # ThemeParks.wiki generally identifies entertainment
        # offerings as SHOW entities.
        if entity_type != "SHOW":
            continue

        event_id = item.get("id")
        event_name = item.get("name")
        status = item.get("status")
        last_updated = item.get("lastUpdated")

        showtimes = item.get("showtimes", [])

        # Some SHOW entities may exist without listed times.
        if not showtimes:
            rows.append({
                "snapshot_time": now.isoformat(),
                "party_date": now.strftime("%Y-%m-%d"),
                "event_id": event_id,
                "event_name": event_name,
                "event_type": entity_type,
                "status": status,
                "show_start_time": None,
                "show_end_time": None,
                "source_last_updated": last_updated,
            })

            continue

        for showtime in showtimes:

            rows.append({
                "snapshot_time": now.isoformat(),
                "party_date": now.strftime("%Y-%m-%d"),
                "event_id": event_id,
                "event_name": event_name,
                "event_type": entity_type,
                "status": status,
                "show_start_time": normalize_time(
                    showtime.get("startTime")
                ),
                "show_end_time": normalize_time(
                    showtime.get("endTime")
                ),
                "source_last_updated": last_updated,
            })

    if not rows:
        print(
            "WARNING: No SHOW entities were returned. "
            "The API may not currently expose entertainment "
            "showtimes in the expected format."
        )
        return

    file_exists = DATA_FILE.exists()

    with DATA_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as csvfile:

        writer = csv.DictWriter(
            csvfile,
            fieldnames=FIELDNAMES,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)

    print(
        f"SUCCESS: Saved {len(rows)} entertainment records "
        f"to {DATA_FILE}"
    )


if __name__ == "__main__":
    collect_events()
