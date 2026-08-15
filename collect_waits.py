import csv
import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# MNSSHP MAGIC KINGDOM WAIT-TIME TRACKER
# ============================================================

MAGIC_KINGDOM_ID = "75ea578a-adc8-4116-a54d-dccb60765ef9"

API_URL = (
    f"https://api.themeparks.wiki/v1/entity/"
    f"{MAGIC_KINGDOM_ID}/live"
)

DATA_FILE = "data/magic_kingdom_waits.csv"

EASTERN = ZoneInfo("America/New_York")


# ------------------------------------------------------------
# MNSSHP NIGHTS TO COLLECT
# These are the remaining parties before our Sept. 4 visit.
# ------------------------------------------------------------

MNSSHP_DATES = {
    "2026-08-18",
    "2026-08-21",
    "2026-08-23",
    "2026-08-25",
    "2026-08-28",
    "2026-08-30",
    "2026-09-01",
}


def should_collect(now):
    """
    Collect only:
      - On one of our selected MNSSHP dates
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


def get_posted_wait(live_item):
    """
    Extract the standby posted wait from ThemeParks.wiki.

    Returns None if:
      - no queue information exists
      - standby isn't being reported
      - the attraction is closed
    """

    queue = live_item.get("queue")

    if not queue:
        return None

    standby = queue.get("STANDBY")

    if not standby:
        return None

    return standby.get("waitTime")


def determine_period(now):
    """
    Label each observation based on time of day.

    PRE_PARTY:
        4:00 PM - 5:59 PM

    TRANSITION:
        6:00 PM - 6:59 PM

    PARTY:
        7:00 PM - Midnight
    """

    if now.hour < 18:
        return "PRE_PARTY"

    if now.hour < 19:
        return "TRANSITION"

    return "PARTY"


def collect_waits():

    now = datetime.now(EASTERN)

    if not should_collect(now):
        return

    period = determine_period(now)

    print(
        f"Collecting Magic Kingdom waits at "
        f"{now.isoformat()} [{period}]"
    )

    # --------------------------------------------------------
    # Request current Magic Kingdom live data
    # --------------------------------------------------------

    response = requests.get(
        API_URL,
        timeout=30,
        headers={
            "User-Agent": "MNSSHP-Wait-Tracker/1.0"
        }
    )

    response.raise_for_status()

    payload = response.json()

    live_data = payload.get("liveData", [])

    # --------------------------------------------------------
    # Prepare CSV
    # --------------------------------------------------------

    os.makedirs("data", exist_ok=True)

    file_exists = os.path.isfile(DATA_FILE)

    fieldnames = [
        "snapshot_time",
        "party_date",
        "period",
        "ride_id",
        "ride_name",
        "status",
        "posted_wait_minutes",
        "source_last_updated",
    ]

    rows = []

    # --------------------------------------------------------
    # Process every attraction
    # --------------------------------------------------------

    for item in live_data:

        if item.get("entityType") != "ATTRACTION":
            continue

        wait_time = get_posted_wait(item)

        row = {
            "snapshot_time": now.isoformat(),
            "party_date": now.strftime("%Y-%m-%d"),
            "period": period,
            "ride_id": item.get("id"),
            "ride_name": item.get("name"),
            "status": item.get("status"),
            "posted_wait_minutes": wait_time,
            "source_last_updated": item.get("lastUpdated"),
        }

        rows.append(row)

    # --------------------------------------------------------
    # Write snapshot to CSV
    # --------------------------------------------------------

    with open(
        DATA_FILE,
        "a",
        newline="",
        encoding="utf-8",
    ) as csvfile:

        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)

    print(
        f"SUCCESS: Saved {len(rows)} attraction records "
        f"to {DATA_FILE}"
    )


if __name__ == "__main__":
    collect_waits()
