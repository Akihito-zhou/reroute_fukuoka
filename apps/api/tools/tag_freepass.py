#!/usr/bin/env python3
"""
Tag "freepass-eligible" lines with built-in paths (no CLI required).
Inputs (defaults, can be overridden by CLI):
  - apps/api/data/stations.csv            (headers: ekispert_station_code,name,lat,lon)
  - apps/api/data/line_stop_edges.csv     (headers: line_id,station_code)
  - apps/api/data/lines_from_extreme.csv  (headers: line_id,corporation,sample_name,...)
  - apps/api/data/fukuoka_city.geojson    (Polygon/MultiPolygon)

Outputs:
  - apps/api/data/freepass_lines.yml
  - apps/api/data/freepass_summary.csv
"""

import argparse
import csv
import json
import os
import sys
from typing import Any

# ======= 内置默认路径（可用 CLI 覆盖） =======
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")

DEFAULT_STATIONS_CSV = os.path.join(DATA_DIR, "stations.csv")
DEFAULT_EDGES_CSV = os.path.join(DATA_DIR, "line_stop_edges.csv")  # 代 timetable 使用
DEFAULT_LINES_META_CSV = os.path.join(DATA_DIR, "lines_from_extreme.csv")  # 线路名/公司
DEFAULT_CITY_GEOJSON = os.path.join(DATA_DIR, "fukuoka_city.geojson")

DEFAULT_OUT_YML = os.path.join(DATA_DIR, "freepass_lines.yml")
DEFAULT_OUT_SUMMARY = os.path.join(DATA_DIR, "freepass_summary.csv")

# ======= 规则：公司白名单 + 关键词黑名单 =======
CORP_ALLOW_SUBSTR = ["西鉄バス"]  # 只要包含这些子串之一视为“西鉄”
NAME_DENY_KEYWORDS = [
    "高速",
    "空港",
    "BRT",
    "特急",
    "急行",
    "快速",
    "深夜",
    "ライナー",
    "都市高速",
]


# ======= Geo 工具：Point-In-Polygon（支持 MultiPolygon） =======
def _point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray casting in lon-lat order (x=lon, y=lat). ring: [(lon,lat), ...]"""
    x, y = lon, lat
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        # check if edge crosses the horizontal ray
        intersect = ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1
        )
        if intersect:
            inside = not inside
    return inside


def _point_in_poly(
    lat: float, lon: float, coords: list[list[tuple[float, float]]]
) -> bool:
    """
    Polygon with holes: coords[0] is outer, coords[1:] are holes.
    Return True if inside the outer polygon and outside every hole.
    """
    if not coords:
        return False
    if not _point_in_ring(lat, lon, coords[0]):
        return False
    # holes
    for hole in coords[1:]:
        if _point_in_ring(lat, lon, hole):
            return False
    return True


def _any_polygon_contains(
    lat: float, lon: float, multipoly: list[list[list[tuple[float, float]]]]
) -> bool:
    """multipoly: list of polygons; each polygon is list of rings; ring is list of (lon,lat)."""
    for poly in multipoly:
        if _point_in_poly(lat, lon, poly):
            return True
    return False


def load_city_multipolygon(geojson_path: str) -> list[list[list[tuple[float, float]]]]:
    """
    Return MultiPolygon normalized to: List[Polygon], Polygon -> List[Ring], Ring -> List[(lon,lat)]
    Accepts Feature/FeatureCollection/Geometry. Supports Polygon and MultiPolygon.
    """
    if not os.path.exists(geojson_path):
        print(f"❌ 缺少市界 GeoJSON: {geojson_path}", file=sys.stderr)
        sys.exit(1)
    with open(geojson_path, encoding="utf-8") as f:
        gj = json.load(f)

    def normalize_geom(geom: dict[str, Any]) -> list[list[list[tuple[float, float]]]]:
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Polygon":
            # coords: [ [ [lon,lat], ... ], [hole...], ... ]
            return [[[(float(x), float(y)) for x, y in ring] for ring in coords]]
        elif gtype == "MultiPolygon":
            # coords: [ [ [ [lon,lat], ... ] ], [ ... ], ... ]
            out = []
            for poly in coords:
                out.append([[(float(x), float(y)) for x, y in ring] for ring in poly])
            return out
        else:
            return []

    # FeatureCollection
    if gj.get("type") == "FeatureCollection":
        acc = []
        for feat in gj.get("features", []):
            geom = feat.get("geometry") or {}
            acc.extend(normalize_geom(geom))
        return acc
    # Feature
    if gj.get("type") == "Feature":
        return normalize_geom(gj.get("geometry") or {})
    # Geometry
    return normalize_geom(gj)


# ======= 数据加载 =======
def load_stations(stations_csv: str) -> dict[str, tuple[float, float]]:
    if not os.path.exists(stations_csv):
        print(f"❌ 未找到站点文件: {stations_csv}", file=sys.stderr)
        sys.exit(1)
    code2ll: dict[str, tuple[float, float]] = {}
    with open(stations_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            code = (
                row.get("ekispert_station_code")
                or row.get("station_code")
                or row.get("code")
            )
            lat = row.get("lat")
            lon = row.get("lon")
            if not code:
                continue
            try:
                latf = float(lat) if lat not in (None, "") else None
                lonf = float(lon) if lon not in (None, "") else None
            except (TypeError, ValueError):
                latf = lonf = None
            if latf is None or lonf is None:
                continue
            code2ll[str(code)] = (latf, lonf)
    return code2ll


def load_edges(edges_csv: str) -> dict[str, set]:
    """Return: line_id -> {station_code,...}"""
    if not os.path.exists(edges_csv):
        print(f"❌ 未找到线路-站点关系文件: {edges_csv}", file=sys.stderr)
        sys.exit(1)
    line2stops: dict[str, set] = {}
    with open(edges_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            lid = row.get("line_id")
            sc = (
                row.get("station_code")
                or row.get("stop_code")
                or row.get("ekispert_station_code")
            )
            if not lid or not sc:
                continue
            line2stops.setdefault(lid, set()).add(str(sc))
    return line2stops


def load_line_meta(lines_meta_csv: str) -> dict[str, dict[str, str]]:
    """Return: line_id -> {'corporation':..., 'name':...}"""
    meta: dict[str, dict[str, str]] = {}
    if not os.path.exists(lines_meta_csv):
        # 可缺省
        return meta
    with open(lines_meta_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            lid = row.get("line_id")
            if not lid:
                continue
            meta[lid] = {
                "corporation": row.get("corporation", ""),
                "name": row.get("sample_name", "") or row.get("name", ""),
            }
    return meta


# ======= 规则判定 =======
def corp_allowed(corp: str) -> bool:
    if not corp:
        return False
    return any(k in corp for k in CORP_ALLOW_SUBSTR)


def name_denied(name: str) -> bool:
    if not name:
        return False
    return any(k in name for k in NAME_DENY_KEYWORDS)


# ======= 主流程 =======
def main():
    parser = argparse.ArgumentParser(
        description="Tag freepass lines (built-in defaults, CLI optional)."
    )
    parser.add_argument("--stations", default=DEFAULT_STATIONS_CSV)
    parser.add_argument(
        "--edges", default=DEFAULT_EDGES_CSV, help="line_stop_edges.csv"
    )
    parser.add_argument("--lines-meta", default=DEFAULT_LINES_META_CSV)
    parser.add_argument("--city-geojson", default=DEFAULT_CITY_GEOJSON)
    parser.add_argument("--out-freepass-yml", default=DEFAULT_OUT_YML)
    parser.add_argument("--out-summary", default=DEFAULT_OUT_SUMMARY)
    args = parser.parse_args()

    stations_csv = args.stations
    edges_csv = args.edges
    lines_meta_csv = args.lines_meta
    city_geojson = args.city_geojson
    out_yml = args.out_freepass_yml
    out_summary = args.out_summary

    print(f"📄 stations: {stations_csv}")
    print(f"📄 edges   : {edges_csv}")
    print(f"📄 meta    : {lines_meta_csv}")
    print(f"📄 city    : {city_geojson}")

    code2ll = load_stations(stations_csv)
    if not code2ll:
        print("⚠️ stations.csv 里没有有效的 (code,lat,lon)。", file=sys.stderr)

    line2stops = load_edges(edges_csv)
    lines_meta = load_line_meta(lines_meta_csv)
    multipoly = load_city_multipolygon(city_geojson)

    # 统计
    summary_rows: list[dict[str, Any]] = []
    yml_lines: list[str] = ["# generated by tag_freepass.py", "freepass_lines:"]

    for lid, stops in sorted(line2stops.items()):
        corp = lines_meta.get(lid, {}).get("corporation", "")
        name = lines_meta.get(lid, {}).get("name", "")

        inside, outside, unknown = 0, 0, 0
        outside_stop_codes: list[str] = []
        for sc in stops:
            ll = code2ll.get(sc)
            if not ll:
                unknown += 1
                continue
            lat, lon = ll
            if _any_polygon_contains(lat, lon, multipoly):
                inside += 1
            else:
                outside += 1
                outside_stop_codes.append(sc)

        # 规则：公司白名单 + 名称不含黑名单关键词（即便有市外站也保留，后续过滤时再剔除站点）
        eligible = corp_allowed(corp) and (not name_denied(name))
        reason = []
        if not corp_allowed(corp):
            reason.append("corp_not_allowed")
        if name_denied(name):
            reason.append("name_blacklisted")
        if outside > 0:
            reason.append("has_outside_stops")
        reason_str = ",".join(reason) if reason else "ok"

        summary_rows.append(
            {
                "line_id": lid,
                "corporation": corp,
                "name": name,
                "stops_total": len(stops),
                "stops_inside": inside,
                "stops_outside": outside,
                "stops_unknown": unknown,
                "outside_stop_codes": ",".join(outside_stop_codes),
                "eligible": "yes" if eligible else "no",
                "reason": reason_str,
            }
        )

        # yml
        yml_lines.append(f'  - line_id: "{lid}"')
        yml_lines.append(f'    corporation: "{corp}"')
        yml_lines.append(f'    name: "{name}"')
        yml_lines.append(f"    stops_inside: {inside}")
        yml_lines.append(f"    stops_outside: {outside}")
        yml_lines.append(f"    stops_unknown: {unknown}")
        yml_lines.append(f"    eligible: {str(eligible).lower()}")
        yml_lines.append(f'    reason: "{reason_str}"')
        if outside_stop_codes:
            yml_lines.append("    outside_stops:")
            for code in outside_stop_codes:
                yml_lines.append(f'      - "{code}"')
        else:
            yml_lines.append("    outside_stops: []")

    # 写出
    os.makedirs(os.path.dirname(out_yml), exist_ok=True)
    with open(out_yml, "w", encoding="utf-8") as f:
        f.write("\n".join(yml_lines) + "\n")

    with open(out_summary, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "line_id",
                "corporation",
                "name",
                "stops_total",
                "stops_inside",
                "stops_outside",
                "stops_unknown",
                "outside_stop_codes",
                "eligible",
                "reason",
            ],
        )
        w.writeheader()
        for row in summary_rows:
            w.writerow(row)

    print(f"✅ 输出 YAML : {out_yml}  （{len(summary_rows)} 条线路）")
    print(f"✅ 输出 CSV  : {out_summary}")
    # 小提示
    if not lines_meta:
        print(
            "ℹ️ 未找到 lines_from_extreme.csv，将缺少公司与线路名；只会按地理规则打标。"
        )
    missing_coords = sum(1 for rows in summary_rows if rows["stops_unknown"] > 0)
    if missing_coords:
        print(
            f"⚠️ 有 {missing_coords} 条线路含未知坐标站点，请检查 stations.csv 经纬度列。"
        )


if __name__ == "__main__":
    main()
