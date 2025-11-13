#!/usr/bin/env python3
import argparse
import csv
import os
import sys

import requests
from dotenv import load_dotenv
from tqdm import trange


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pref", type=int, default=40, help="prefectureCode (default: 40 福岡県)"
    )
    ap.add_argument("--outfile", default="stations_nishitetsu_fukuoka.csv")
    ap.add_argument("--include-community", action="store_true")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--max", type=int, default=8000, help="max offset upper bound")
    args = ap.parse_args()

    load_dotenv()
    key = os.getenv("MIXWAY_API_KEY")
    if not key:
        print("❌ MIXWAY_API_KEY missing", file=sys.stderr)
        sys.exit(1)

    rows, seen = [], set()
    community = "contain" if args.include_community else "except"

    for off in trange(1, args.max + 1, args.limit, desc="paging /station"):
        params = dict(
            key=key,
            type="bus.local",
            prefectureCode=args.pref,
            communityBus=community,
            limit=args.limit,
            offset=off,
        )
        r = requests.get(
            "https://mixway.ekispert.jp/v1/json/station", params=params, timeout=30
        )
        r.raise_for_status()
        pts = (r.json().get("ResultSet") or {}).get("Point") or []
        if not pts:
            break
        for p in pts:
            s = (p or {}).get("Station") or {}
            name = (s.get("Name") or "").strip()
            if not name.endswith("／西鉄バス"):  # 仅西鉄
                continue
            code = s.get("code")
            gp = p.get("GeoPoint") or {}  # 注意：GeoPoint 在 Point 层
            lat, lon = gp.get("lati_d"), gp.get("longi_d")
            if code and code not in seen:
                seen.add(code)
                rows.append([code, name, lat, lon])

    out = "apps/api/data/stations.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ekispert_station_code", "name", "lat", "lon"])
        w.writerows(rows)
    print(f"✅ Saved {len(rows)} rows → {out}")


if __name__ == "__main__":
    main()
