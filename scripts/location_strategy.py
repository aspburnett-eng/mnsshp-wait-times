#!/usr/bin/env python3
"""First-pass MNSSHP location-aware strategy engine.

Reads:
  data/magic_kingdom_waits.csv
  data/party_events.csv
  data/location_reference.json

Writes:
  data/location_strategy.json

The model intentionally separates sourced facts from planning estimates.
Parade zone passage offsets and walking times are configurable in the
location reference file and should be calibrated as better data becomes
available.
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
DEFAULT_PARADE_DURATION_MIN = 20

# First-pass zone timing offsets. Frontierland is the anchor.
# Main Street is anchored near +10 min by recent published guidance.
# Intermediate offsets are explicitly planning estimates.
DEFAULT_PASSAGE_OFFSETS = {
    "frontierland_west": 0,
    "frontierland_east": 2,
    "liberty_square": 5,
    "hub": 8,
    "main_street": 10,
    "town_square": 13,
}


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
        for nxt, w in graph.get(node, []):
            if nxt not in seen:
                heapq.heappush(pq, (cost + w, nxt))
    return None


def nearest_wait(rows, ride_name, target_dt, max_minutes=20):
    candidates = []
    for r in rows:
        if r.get("ride_name") != ride_name or not r.get("posted_wait_minutes"):
            continue
        try:
            dt = parse_iso(r["snapshot_time"])
            wait = float(r["posted_wait_minutes"])
        except Exception:
            continue
        delta = abs((dt - target_dt).total_seconds()) / 60.0
        if delta <= max_minutes:
            candidates.append((delta, dt, wait, r.get("status")))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    _, dt, wait, status = candidates[0]
    return {"snapshot_time": dt.isoformat(), "posted_wait_min": wait, "status": status}


def parade_starts(events, party_date):
    starts = []
    for e in events:
        name = (e.get("event_name") or "").lower()
        if e.get("party_date") == party_date and PARADE_NAME_MATCH in name and e.get("show_start_time"):
            starts.append(parse_iso(e["show_start_time"]))
    return sorted(starts)


def build():
    waits = load_csv(WAITS)
    events = load_csv(EVENTS)
    loc = load_json(LOC)
    graph = graph_from_location(loc)
    attraction_zone = {a["name"]: a["zone"] for a in loc["attractions"]}
    viewing_zones = [z["id"] for z in loc["zones"] if z["type"] == "viewing_zone"]

    party_dates = sorted({r["party_date"] for r in waits if r.get("party_date") and r["party_date"] >= "2026-08-18"})
    result = {
        "model_version": 1,
        "generated_from": [str(WAITS.relative_to(ROOT)), str(EVENTS.relative_to(ROOT)), str(LOC.relative_to(ROOT))],
        "assumptions": {
            "parade_duration_min": DEFAULT_PARADE_DURATION_MIN,
            "passage_offsets_min": DEFAULT_PASSAGE_OFFSETS,
            "wait_lookup_tolerance_min": 20,
            "effective_cost_formula": "walk_min + posted_wait_min",
            "note": "Walking times and intermediate parade passage offsets are planning estimates pending calibration."
        },
        "parties": []
    }

    for date in party_dates:
        day_rows = [r for r in waits if r.get("party_date") == date]
        starts = parade_starts(events, date)
        party_out = {"party_date": date, "parades": []}
        for start in starts:
            parade_out = {"start_time": start.isoformat(), "viewing_zones": []}
            for view_zone in viewing_zones:
                if view_zone not in DEFAULT_PASSAGE_OFFSETS:
                    continue
                arrival = start + timedelta(minutes=DEFAULT_PASSAGE_OFFSETS[view_zone])
                clear = arrival + timedelta(minutes=DEFAULT_PARADE_DURATION_MIN)
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
                    options.append({
                        "ride": ride,
                        "ride_zone": ride_zone,
                        "walk_min": round(walk, 1),
                        "estimated_ride_arrival": ride_arrival.isoformat(),
                        "wait_snapshot_time": wait["snapshot_time"],
                        "posted_wait_min": wait["posted_wait_min"],
                        "effective_cost_min": round(effective, 1)
                    })
                options.sort(key=lambda x: (x["effective_cost_min"], x["posted_wait_min"], x["walk_min"]))
                parade_out["viewing_zones"].append({
                    "viewing_zone": view_zone,
                    "estimated_parade_arrival": arrival.isoformat(),
                    "estimated_parade_clear": clear.isoformat(),
                    "best_next_rides": options[:8]
                })
            parade_out["viewing_zones"].sort(key=lambda x: DEFAULT_PASSAGE_OFFSETS[x["viewing_zone"]])
            party_out["parades"].append(parade_out)
        result["parties"].append(party_out)

    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
