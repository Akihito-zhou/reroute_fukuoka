#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch bus timetable segments (edge-based) by calling /v1/json/bus/timetable
for every adjacent stop pair in line_stop_edges.csv.

The output CSV contains one row per ride segment:
  line_id, direction, service_date, segment_id,
  from_code, from_name, to_code, to_name, depart, arrive

Planner can consume these segments directly to build a time-expanded graph
without reconstructing full trip stop sequences.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
CACHE_DIR = BASE_DIR / ".cache_ttb"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EDGES = DATA_DIR / "line_stop_edges.csv"
DEFAULT_STATIONS = DATA_DIR / "stations.csv"
API_URL = "https://mixway.ekispert.jp/v1/json/bus/timetable"


def cache_path(
    line_id: str, direction: str, service_date: str, frm: str, to: str
) -> Path:
    name = f"ttb_{line_id}_{direction}_{frm}_{to}_{service_date}.json"
    return CACHE_DIR / name


def http_get(params: dict, retry: int = 3, backoff: float = 0.7) -> requests.Response:
    for attempt in range(retry):
        resp = requests.get(API_URL, params=params, timeout=30)
        if resp.status_code == 200:
            return resp
        if resp.status_code in {429, 500, 502, 503, 504}:
            time.sleep(backoff * (2**attempt))
            continue
        return resp
    return resp


def fetch_pair(
    key: str,
    line_id: str,
    direction: str,
    service_date: str,
    frm: str,
    to: str,
) -> dict | None:
    cpath = cache_path(line_id, direction, service_date, frm, to)
    if cpath.exists():
        return json.loads(cpath.read_text(encoding="utf-8"))

    params = {"key": key, "from": frm, "to": to, "date": service_date}
    resp = http_get(params)
    if resp.headers.get("Content-Type", "").startswith("application/json"):
        payload = resp.json()
    else:
        payload = {"ResultSet": {}, "status": resp.status_code, "text": resp.text[:500]}
    cpath.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if resp.status_code != 200:
        return None
    return payload


def parse_segments(
    payload: dict,
) -> List[Tuple[str, str, str]]:
    """
    Return list of (trip_id, depart, arrive) for one from→to request.
    """
    if not payload:
        return []
    timetable = payload.get("ResultSet", {}).get("TimeTable") or {}
    lines = timetable.get("Line") or []
    if isinstance(lines, dict):
        lines = [lines]
    segments: List[Tuple[str, str, str]] = []
    for idx, item in enumerate(lines):
        trip_id = str(item.get("trainID") or idx)
        dep = (item.get("DepartureState") or {}).get("Datetime", {}).get("text") or ""
        arr = (item.get("ArrivalState") or {}).get("Datetime", {}).get("text") or ""
        segments.append((trip_id, dep, arr))
    return segments


def load_line_edges(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        print(f"❌ missing line_stop_edges: {path}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(path, dtype=str)
    required = {"line_id", "station_code"}
    if not required.issubset(df.columns):
        print(
            "❌ line_stop_edges.csv must contain line_id, station_code", file=sys.stderr
        )
        sys.exit(1)
    return df.groupby("line_id", sort=False)["station_code"].apply(list).to_dict()


def load_station_names(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"ekispert_station_code": str, "name": str})
    return {
        str(row["ekispert_station_code"]): row["name"]
        for _, row in df.iterrows()
        if str(row["ekispert_station_code"])
    }


def within_window(time_text: str, window: Tuple[str, str] | None) -> bool:
    if not window or not time_text:
        return True
    hhmm = time_text[:5]
    start, end = window
    if start <= end:
        return start <= hhmm <= end
    # overnight window (e.g., 22:00-03:00)
    return hhmm >= start or hhmm <= end


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch bus timetable segments.")
    parser.add_argument("--date", required=True, help="Service date (YYYYMMDD)")
    parser.add_argument("--edges_csv", default=str(DEFAULT_EDGES))
    parser.add_argument("--stations_csv", default=str(DEFAULT_STATIONS))
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of lines for offline batch (0 = all, default 10)",
    )
    parser.add_argument(
        "--line_ids",
        help="Comma-separated line_ids for incremental fetch (overrides --limit).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.25,
        help="Delay (seconds) between API calls.",
    )
    parser.add_argument(
        "--window",
        nargs=2,
        metavar=("HH:MM", "HH:MM"),
        help="Optional time window to keep segments (e.g., 05:00 12:00).",
    )
    args = parser.parse_args()

    load_dotenv()
    key = os.getenv("MIXWAY_API_KEY")
    if not key:
        print("❌ MIXWAY_API_KEY missing. Add it to .env.", file=sys.stderr)
        sys.exit(1)

    station_names = load_station_names(Path(args.stations_csv))
    line_edges = load_line_edges(Path(args.edges_csv))

    if args.line_ids:
        target_ids = {lid.strip() for lid in args.line_ids.split(",") if lid.strip()}
        selected = {
            lid: stops for lid, stops in line_edges.items() if lid in target_ids
        }
    else:
        selected = line_edges

    window = tuple(args.window) if args.window else None
    records: List[List[str]] = []
    processed = 0

    for line_id, stops in tqdm(selected.items(), desc="bus/timetable"):
        if not args.line_ids and args.limit and processed >= args.limit:
            break
        ordered = [str(s) for s in stops if isinstance(s, str)]
        if len(ordered) < 2:
            continue

        for direction, sequence in (("Up", ordered), ("Down", list(reversed(ordered)))):
            for idx in range(len(sequence) - 1):
                frm = sequence[idx]
                to = sequence[idx + 1]
                payload = fetch_pair(key, line_id, direction, args.date, frm, to)
                segments = parse_segments(payload)
                if not segments:
                    continue
                from_name = station_names.get(frm, frm)
                to_name = station_names.get(to, to)
                for seg_idx, (trip_id, dep, arr) in enumerate(segments):
                    if dep and not within_window(dep, window):
                        continue
                    segment_id = f"{trip_id}:{idx}"
                    records.append(
                        [
                            line_id,
                            direction,
                            args.date,
                            segment_id,
                            frm,
                            from_name,
                            to,
                            to_name,
                            dep,
                            arr,
                        ]
                    )
                time.sleep(args.sleep)

        processed += 1

    if not records:
        print("⚠️ No segments fetched. Check API responses.", file=sys.stderr)
        return

    df = pd.DataFrame(
        records,
        columns=[
            "line_id",
            "direction",
            "service_date",
            "segment_id",
            "from_stop",
            "from_name",
            "to_stop",
            "to_name",
            "depart",
            "arrive",
        ],
    )
    out_path = DATA_DIR / f"segments_{args.date}.csv"
    df.to_csv(out_path, index=False)

    if args.line_ids:
        processed_count = processed
    elif args.limit and args.limit > 0:
        processed_count = min(processed, args.limit)
    else:
        processed_count = processed

    print(
        f"✅ segments saved to {out_path} ({len(df)} rows, lines processed: {processed_count})"
    )


if __name__ == "__main__":
    main()
