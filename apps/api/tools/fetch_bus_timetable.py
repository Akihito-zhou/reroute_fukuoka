#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch bus timetables by iterating line-stop sequences and calling
/v1/json/bus/timetable with (from, to) stop codes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests
from dotenv import load_dotenv
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
DEFAULT_EDGES_CSV = DATA_DIR / "line_stop_edges.csv"
CACHE_DIR = BASE_DIR / ".cache_ttb"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

API_URL = "https://mixway.ekispert.jp/v1/json/bus/timetable"


def cache_path(line_id: str, direction: str, date: str, frm: str, to: str) -> Path:
    name = f"ttb_{line_id}_{direction}_{frm}_{to}_{date}.json"
    return CACHE_DIR / name


def http_get_with_retry(
    params: dict, retry: int = 3, backoff: float = 0.8
) -> requests.Response:
    for attempt in range(retry):
        response = requests.get(API_URL, params=params, timeout=30)
        if response.status_code == 200:
            return response
        if response.status_code in {429, 500, 502, 503, 504}:
            time.sleep(backoff * (2**attempt))
            continue
        return response
    return response


def fetch_timetable(
    key: str,
    line_id: str,
    direction: str,
    service_date: str,
    from_code: str,
    to_code: str,
) -> dict | None:
    cpath = cache_path(line_id, direction, service_date, from_code, to_code)
    if cpath.exists():
        return json.loads(cpath.read_text(encoding="utf-8"))

    params = {
        "key": key,
        "from": from_code,
        "to": to_code,
        "date": service_date,
    }
    response = http_get_with_retry(params)
    payload = (
        response.json()
        if response.headers.get("Content-Type", "").startswith("application/json")
        else {"ResultSet": {}, "status": response.status_code, "text": response.text}
    )
    cpath.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if response.status_code != 200:
        return None
    return payload


def extract_rows(
    payload: dict,
    line_id: str,
    direction: str,
    service_date: str,
    from_code: str,
    to_code: str,
) -> List[List[str]]:
    if not payload:
        return []
    timetable = payload.get("ResultSet", {}).get("TimeTable") or {}
    origin_name = timetable.get("Station", {}).get("Name") or from_code
    items = timetable.get("Line") or []
    if isinstance(items, dict):
        items = [items]
    rows: List[List[str]] = []
    for idx, item in enumerate(items, start=1):
        trip_id = str(item.get("trainID") or idx)
        dep = (item.get("DepartureState") or {}).get("Datetime", {}).get("text") or ""
        arr = (item.get("ArrivalState") or {}).get("Datetime", {}).get("text") or ""
        dest_station = (item.get("Destination") or {}).get("Station") or {}
        dest_code = dest_station.get("code") or to_code
        dest_name = dest_station.get("Name") or dest_code
        rows.append(
            [
                line_id,
                direction,
                service_date,
                trip_id,
                1,
                from_code,
                origin_name,
                "",
                dep,
            ]
        )
        rows.append(
            [
                line_id,
                direction,
                service_date,
                trip_id,
                2,
                dest_code,
                dest_name,
                arr,
                "",
            ]
        )
    return rows


def load_line_edges(path: Path) -> Dict[str, List[str]]:
    if not path.exists():
        print(f"❌ missing line-stop edges file: {path}", file=sys.stderr)
        sys.exit(1)
    df = pd.read_csv(path, dtype=str)
    required = {"line_id", "station_code"}
    if not required.issubset(df.columns):
        print(
            "❌ line_stop_edges.csv must contain columns line_id, station_code",
            file=sys.stderr,
        )
        sys.exit(1)
    grouped = df.groupby("line_id", sort=False)["station_code"].apply(list)
    return grouped.to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch bus timetable via from/to stop pairs."
    )
    parser.add_argument("--date", required=True, help="Service date YYYYMMDD")
    parser.add_argument("--edges_csv", default=str(DEFAULT_EDGES_CSV))
    args = parser.parse_args()

    load_dotenv()
    key = os.getenv("MIXWAY_API_KEY")
    if not key:
        print("❌ MIXWAY_API_KEY is missing. Add it to .env.", file=sys.stderr)
        sys.exit(1)

    line_edges = load_line_edges(Path(args.edges_csv))
    out_rows: List[List[str]] = []

    for line_id, stops in tqdm(line_edges.items(), desc="bus/timetable"):
        stops = [s for s in stops if isinstance(s, str)]
        if len(stops) < 2:
            continue
        pairs = [
            ("Up", stops[0], stops[-1]),
            ("Down", stops[-1], stops[0]),
        ]
        for direction, frm, to in pairs:
            payload = fetch_timetable(key, line_id, direction, args.date, frm, to)
            rows = extract_rows(payload, line_id, direction, args.date, frm, to)
            out_rows.extend(rows)
            time.sleep(0.2)

    df = pd.DataFrame(
        out_rows,
        columns=[
            "operationLineCode",
            "direction",
            "service_date",
            "trip_id",
            "stop_seq",
            "station_code",
            "station_name",
            "arr",
            "dep",
        ],
    )
    out_path = DATA_DIR / f"timetable_{args.date}.csv"
    df.to_csv(out_path, index=False)
    print(f"✅ timetable → {out_path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
