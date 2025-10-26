#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collect 'bus line' hints (LINE=xxx) by sampling station pairs and calling
/v1/json/search/course/extreme, then extract bus segments' InsideInformation.

Input : apps/api/data/stations.csv  (headers: ekispert_station_code,name,lat,lon)
Output: apps/api/data/lines_from_extreme.csv
        apps/api/data/line_stop_edges.csv

Cache : apps/api/tools/.cache_extreme_pairs.jsonl  (one JSON per request)
Note  : Uses LINE=... from InsideInformation.navigatorTransportation as internal line id.
"""

import os, sys, csv, json, time, math, random
from collections import defaultdict
from typing import List, Dict, Any, Tuple
import requests
from dotenv import load_dotenv
from tqdm import tqdm

# ---------- paths ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
IN_STATIONS = os.path.join(DATA_DIR, "stations.csv")
OUT_LINES = os.path.join(DATA_DIR, "lines_from_extreme.csv")
OUT_EDGES = os.path.join(DATA_DIR, "line_stop_edges.csv")
CACHE_FILE = os.path.join(BASE_DIR, ".cache_extreme_pairs.jsonl")

API_URL = "https://mixway.ekispert.jp/v1/json/search/course/extreme"


# ---------- helpers ----------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def load_stations() -> List[Dict[str, Any]]:
    if not os.path.exists(IN_STATIONS):
        print(f"❌ 未找到输入文件: {IN_STATIONS}", file=sys.stderr)
        sys.exit(1)
    rows = []
    with open(IN_STATIONS, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                row["lat"] = float(row.get("lat") or 0)
                row["lon"] = float(row.get("lon") or 0)
            except:
                row["lat"] = 0.0
                row["lon"] = 0.0
            if row.get("ekispert_station_code"):
                rows.append(row)
    return rows


def nearest_neighbors(stations: List[Dict[str, Any]], k=3) -> Dict[str, List[str]]:
    """Return for each station code, k nearest other station codes."""
    # simple O(n^2) for moderate n; OK for a few thousand with sampling
    coords = [(s["ekispert_station_code"], s["lat"], s["lon"]) for s in stations]
    out = {}
    for code, lat, lon in tqdm(coords, desc="build nearest neighbors"):
        dists = []
        for code2, lat2, lon2 in coords:
            if code2 == code:
                continue
            if lat2 == 0 or lon2 == 0:
                continue
            d = haversine(lat, lon, lat2, lon2)
            dists.append((d, code2))
        dists.sort(key=lambda x: x[0])
        out[code] = [c for _, c in dists[:k]]
    return out


def cached_pair_key(a: str, b: str) -> str:
    return f"{a}:{b}"


def iter_courses_from_cache() -> Dict[str, Any]:
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                key = rec.get("pair")
                payload = rec.get("payload")
                if key and payload:
                    cache[key] = payload
    return cache


def save_cache_entry(pair_key: str, payload: Any):
    with open(CACHE_FILE, "a", encoding="utf-8") as f:
        f.write(
            json.dumps({"pair": pair_key, "payload": payload}, ensure_ascii=False)
            + "\n"
        )


def extract_lines_from_course_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    From /search/course/extreme payload, extract bus segments with LINE=xxx and Stop[].
    Return list of { line_id, corp, name, stop_codes }
    """
    out = []
    try:
        courses = payload.get("ResultSet", {}).get("Course", []) or []
    except AttributeError:
        return out
    for course in courses:
        route = course.get("Route") or {}
        lines = route.get("Line") or []
        for seg in lines:
            t = seg.get("Type", {})
            if (isinstance(t, dict) and t.get("text") == "bus") or (t == "bus"):
                info = seg.get("InsideInformation") or {}
                nav = info.get("navigatorTransportation") or ""
                line_id = None
                # parse LINE=xxx from querystring-like text
                for chunk in nav.split("&"):
                    if chunk.startswith("LINE="):
                        line_id = chunk.split("=", 1)[1]
                        break
                corp = ""
                corp_obj = seg.get("Corporation") or {}
                if isinstance(corp_obj, dict):
                    corp = corp_obj.get("Name") or ""
                name = seg.get("Name") or seg.get("TypicalName") or ""
                # collect stops
                stop_codes = []
                for st in seg.get("Stop") or []:
                    p = st.get("Point") or {}
                    stn = p.get("Station") or {}
                    code = stn.get("code")
                    if code:
                        stop_codes.append(str(code))
                if line_id:
                    out.append(
                        {
                            "line_id": line_id,
                            "corp": corp,
                            "name": name,
                            "stop_codes": stop_codes,
                        }
                    )
    return out


def main():
    load_dotenv()
    key = os.getenv("MIXWAY_API_KEY")
    if not key:
        print("❌ .env 缺少 MIXWAY_API_KEY", file=sys.stderr)
        sys.exit(1)

    stations = load_stations()
    print(f"📍 站点数: {len(stations)}")

    # 只采样“市中心密度较高”的部分，避免 N^2
    # 策略：每个站取最近的 k 个邻站（默认 3），形成有向对；再随机下采样到最多 Pairs_Limit
    K_NEI = 3
    PAIRS_LIMIT = 5000  # 安全上限，必要时可调大/小
    neighbors = nearest_neighbors(stations, k=K_NEI)

    pairs = []
    for s in stations:
        a = s["ekispert_station_code"]
        for b in neighbors.get(a, []):
            if a and b:
                pairs.append((a, b))

    # 去重（无向）
    pairs = list({tuple(sorted(p)) for p in pairs})
    random.shuffle(pairs)
    if len(pairs) > PAIRS_LIMIT:
        pairs = pairs[:PAIRS_LIMIT]

    print(f"🔎 计划查询的站对数: {len(pairs)} (每对 1 次 extreme)")

    # cache
    cache = iter_courses_from_cache()

    sess = requests.Session()
    seen_pairs = 0
    all_lines: Dict[str, Dict[str, Any]] = {}  # line_id -> aggregated record
    edges = set()  # (line_id, stop_code)

    for a, b in tqdm(pairs, desc="fetch extreme"):
        pair_key = cached_pair_key(a, b)
        if pair_key in cache:
            payload = cache[pair_key]
        else:
            params = {
                "key": key,
                "viaList": f"{a}:{b}",
                "addStop": "true",
                "answerCount": "3",
            }
            try:
                r = sess.get(API_URL, params=params, timeout=30)
                if r.status_code != 200:
                    # 保存错误，继续
                    payload = {"_error": r.text[:200], "_status": r.status_code}
                else:
                    payload = r.json()
            except Exception as e:
                payload = {"_exception": str(e)}
            save_cache_entry(pair_key, payload)
            time.sleep(0.15)  # 温和限速

        seen_pairs += 1
        # 解析 bus 段
        lines = extract_lines_from_course_payload(payload)
        for it in lines:
            lid = it["line_id"]
            if lid not in all_lines:
                all_lines[lid] = {
                    "line_id": lid,
                    "corp": it["corp"],
                    "sample_name": it["name"],
                    "sample_pairs": set(),
                    "stop_codes": set(),
                }
            rec = all_lines[lid]
            rec["sample_pairs"].add(pair_key)
            for sc in it["stop_codes"]:
                edges.add((lid, sc))
                rec["stop_codes"].add(sc)

    # 写出 lines 聚合
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_LINES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "line_id",
                "corporation",
                "sample_name",
                "sample_pairs_count",
                "stop_count",
            ]
        )
        for lid, rec in sorted(all_lines.items(), key=lambda x: x[0]):
            w.writerow(
                [
                    lid,
                    rec.get("corp", ""),
                    rec.get("sample_name", ""),
                    len(rec.get("sample_pairs", [])),
                    len(rec.get("stop_codes", [])),
                ]
            )

    # 写出 line-stop 关系
    with open(OUT_EDGES, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["line_id", "station_code"])
        for lid, sc in sorted(edges):
            w.writerow([lid, sc])

    print(f"✅ 输出: {OUT_LINES}（线路数 {len(all_lines)}）")
    print(f"✅ 输出: {OUT_EDGES}（line-stop 关系数 {len(edges)}）")
    print(f"🧾 缓存: {CACHE_FILE}（累计 pair 请求 {seen_pairs}）")
    if len(all_lines) == 0:
        print(
            "⚠️ 如果仍为 0：可能该区域 pair 过稀或 answerCount 太小，调大 K_NEI/PAIRS_LIMIT/answerCount 再试。"
        )


if __name__ == "__main__":
    main()
