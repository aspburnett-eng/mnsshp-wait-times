#!/usr/bin/env python3
"""MNSSHP location-aware strategy engine.

Reads wait snapshots, party entertainment, and static location reference data.
Writes data/location_strategy.json with best-next-ride rankings by parade viewing zone.
"""

from __future__ import annotations

import csv
import heapq
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
WAITS = DATA / "magic_kingdom_waits.csv"
EVENTS = DATA / "party_events.csv"
LOC = DATA / "location_reference.json"
OUT = DATA / "location_strategy.json"
PARADE_NAME_MATCH = "boo-to-you"
WAIT_LOOKUP_TOLERANCE_MIN = 20


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def graph_from_location(loc):
    graph = defaultdict(list)
    for edge in loc["movement_edges"]:
        a, b, w = edge["from"], edge["to"], float(edge["base_walk_min"])
        graph[a].append((b, w))
        graph[b].append((a, w))
    return graph


def shortest_walk(graph, start, end):
    if start == end:
        return 0.0
    pq = [(0.0, start)]
    seen = {}
    while pq:
        cost, node = heapq.heappop(pq)
        if node in seen:
            continue
        seen[node] = cost
        if node == end:
            return cost
        for nxt, weight in graph.get(node, []):
            if nxt not in seen:
                heapq.heappush(pq, (cost + weight, nxt))
    return None


def nearest_wait(rows, ride_name, target_dt, max_minutes=WAIT_LOOKUP_TOLERANCE_MIN):
    candidates = []
    for row in rows:
        if row.get("ride_name") != ride_name or not row.get("posted_wait_minutes"):
            continue
        if row.get("status") and row.get("status") != "OPERATING":
            continue
        try:
            dt = parse_iso(row["snapshot_time"])
            wait = float(row["posted_wait_minutes"])
        except Exception:
            continue
        delta = abs((dt - target_dt).total_seconds()) / 60.0
        if delta <= max_minutes:
            candidates.append((delta, dt, wait))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    delta, dt, wait = candidates[0]
    return {
        "snapshot_time": dt.isoformat(),
        "posted_wait_min": wait,
        "snapshot_delta_min": round(delta, 1),
    }


def parade_starts(events, party_date):
    """Return unique parade show times for a party date.

    party_events.csv repeats the same show schedule on multiple snapshots,
    so deduplication is required before strategy generation.
    """
    starts = set()
    for event in events:
        name = (event.get("event_name") or "").lower()
        if (
            event.get("party_date") == party_date
            and PARADE_NAME_MATCH in name
            and event.get("show_start_time")
        ):
            starts.add(parse_iso(event["show_start_time"]))
    return sorted(starts)


def build():
    waits = load_csv(WAITS)
    events = load_csv(EVENTS)
    loc = load_json(LOC)

    parade_cfg = loc["parades"]["Mickey's Boo-To-You Halloween Parade"]
    parade_duration = float(parade_cfg["duration_min"])
    passage_offsets = {k: float(v) for k, v in parade_cfg["passage_offset_min"].items()}

    graph = graph_from_location(loc)
    attraction_zone = {a["name"]: a["zone"] for a in loc["attractions"]}
    viewing_zones = [z["id"] for z in loc["zones"] if z["type"] == "viewing_zone"]

    party_dates = sorted(
        {
            row["party_date"]
            for row in waits
            if row.get("party_date") and row["party_date"] >= "2026-08-18"
        }
    )

    result = {
        "model_version": 2,
        "generated_from": [
            str(WAITS.relative_to(ROOT)),
            str(EVENTS.relative_to(ROOT)),
            str(LOC.relative_to(ROOT)),
        ],
        "assumptions": {
            "parade_duration_min": parade_duration,
            "passage_offsets_min": passage_offsets,
            "wait_lookup_tolerance_min": WAIT_LOOKUP_TOLERANCE_MIN,
            "effective_cost_formula": "walk_min + posted_wait_min",
            "note": "Walking times and intermediate parade passage offsets remain planning estimates pending calibration.",
        },
        "parties": [],
    }

    for party_date in party_dates:
        day_rows = [r for r in waits if r.get("party_date") == party_date]
        party_out = {"party_date": party_date, "parades": []}

        for start in parade_starts(events, party_date):
            parade_out = {"start_time": start.isoformat(), "viewing_zones": []}

            for view_zone in viewing_zones:
                if view_zone not in passage_offsets:
                    continue

                arrival = start + timedelta(minutes=passage_offsets[view_zone])
                clear = arrival + timedelta(minutes=parade_duration)
                options = []

                for ride, ride_zone in attraction_zone.items():
                    walk = shortest_walk(graph, view_zone, ride_zone)
                    if walk is None:
                        continue

                    ride_arrival = clear + timedelta(minutes=walk)
                    wait = nearest_wait(day_rows, ride, ride_arrival)
                    if not wait:
                        continue

                    effective = walk + wait["posted_wait_min"]
                    options.append(
                        {
                            "ride": ride,
                            "ride_zone": ride_zone,
                            "walk_min": round(walk, 1),
                            "estimated_ride_arrival": ride_arrival.isoformat(),
                            "wait_snapshot_time": wait["snapshot_time"],
                            "wait_snapshot_delta_min": wait["snapshot_delta_min"],
                            "posted_wait_min": wait["posted_wait_min"],
                            "effective_cost_min": round(effective, 1),
                        }
                    )

                options.sort(
                    key=lambda x: (
                        x["effective_cost_min"],
                        x["posted_wait_min"],
                        x["walk_min"],
                    )
                )
                parade_out["viewing_zones"].append(
                    {
                        "viewing_zone": view_zone,
                        "estimated_parade_arrival": arrival.isoformat(),
                        "estimated_parade_clear": clear.isoformat(),
                        "best_next_rides": options[:8],
                    }
                )

            parade_out["viewing_zones"].sort(
                key=lambda x: passage_offsets[x["viewing_zone"]]
            )
            party_out["parades"].append(parade_out)

        result["parties"].append(party_out)

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
