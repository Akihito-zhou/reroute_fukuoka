from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import math
import yaml

from .planner_constants import (
    BOUNDARY_BIN_COUNT,
    BOUNDARY_MAX_DIST_KM,
    BOUNDARY_MIN_DIST_KM,
    SEGMENTS_PREFIX,
    TIMETABLE_PREFIX,
)
from .planner_models import Station, TripEdge
from .planner_utils import distance_km, haversine_km, parse_datetime, project_to_plane

if TYPE_CHECKING:
    from .planner import PlannerService

logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> dict:
    """读取YAML文件并返回字典 / YAMLファイルを読み込み辞書を返す。"""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    return data


def load_static_assets(service: "PlannerService") -> None:
    """加载站点、线路、边界等静态资产 / 駅・路線・境界などの静的資産を読み込む。"""
    service.stations = load_stations(service)
    service.line_names, service.eligible_lines = load_line_meta(service)
    service.hakata_stops = detect_hakata_stops(service)
    if not service.hakata_stops:
        raise RuntimeError("博多駅周辺の停留所が stations.csv から検出できません")
    origin_station = service.stations.get(service.hakata_stops[0])
    if origin_station:
        service.hakata_coord = (origin_station.lat, origin_station.lon)
    service.quadrant_map = assign_quadrants(service)
    service.city_boundary = load_city_boundary(service)
    service.line_stop_edges = load_line_stop_edges(service)


def load_stations(service: "PlannerService") -> dict[str, Station]:
    """读取 stations.csv 并返回站点映射 / stations.csv を読み駅マップを返す。"""
    path = service.data_dir / "stations.csv"
    if not path.exists():
        raise RuntimeError("stations.csv が見つかりません")
    stations: dict[str, Station] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get("ekispert_station_code") or row.get("station_code")
            if not code:
                continue
            try:
                lat = float(row.get("lat") or 0)
                lon = float(row.get("lon") or 0)
            except ValueError:
                continue
            if lat == 0 and lon == 0:
                continue
            stations[str(code)] = Station(
                code=str(code),
                name=row.get("name") or str(code),
                lat=lat,
                lon=lon,
            )
    if not stations:
        raise RuntimeError("stations.csv に有効なデータがありません")
    return stations


def load_line_meta(service: "PlannerService") -> tuple[dict[str, str], set[str]]:
    """读取 freepass 配置，返回线路名称与可用集合 / freepass設定を読み路線名と対象集合を返す。"""
    path = service.data_dir / "freepass_lines.yml"
    data = load_yaml(path)
    line_names: dict[str, str] = {}
    eligible: set[str] = set()
    for row in data.get("freepass_lines", []):
        line_id = str(row.get("line_id"))
        if not line_id:
            continue
        name = row.get("name") or row.get("line_name") or line_id
        line_names[line_id] = name
        if row.get("eligible"):
            eligible.add(line_id)
    if not eligible:
        raise RuntimeError("freepass_lines.yml に eligible な路線がありません")
    return line_names, eligible


def detect_hakata_stops(service: "PlannerService") -> list[str]:
    """通过关键词匹配博多相关站点 / キーワードで博多関連停留所を抽出する。"""
    keywords = ["博多", "博多ﾊﾞｽﾀｰﾐﾅﾙ", "博多駅前", "博多ﾊﾞｽﾀ"]
    results = [
        code
        for code, st in service.stations.items()
        if any(keyword in st.name for keyword in keywords)
    ]
    if results:
        return results
    # fallback: pick stations near Hakata coordinate
    fallback = sorted(
        service.stations.values(),
        key=lambda st: (st.lat - 33.589) ** 2 + (st.lon - 130.42) ** 2,
    )
    return [station.code for station in fallback[:3]]


def assign_quadrants(service: "PlannerService") -> dict[str, int]:
    """根据相对于博多的位置给站点打上象限标签 / 博多基準で象限ビットを付与する。"""
    mask: dict[str, int] = {}
    base_lat, base_lon = service.hakata_coord
    for code, station in service.stations.items():
        lat = station.lat
        lon = station.lon
        quadrant = 0
        if lat >= base_lat:
            quadrant |= 1  # north
        else:
            quadrant |= 4  # south
        if lon >= base_lon:
            quadrant |= 2  # east
        else:
            quadrant |= 8  # west
        mask[code] = quadrant
    return mask


def load_city_boundary(service: "PlannerService") -> list[list[tuple[float, float]]]:
    """???????? polygon??????? / ???????????????????"""
    path = service.data_dir / "fukuoka_city.geojson"
    if not path.exists():
        logger.warning("fukuoka_city.geojson not found; city loop may degrade.")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("City boundary geojson is not valid JSON.")
        return []

    features = data.get("features")
    if not isinstance(features, list):
        logger.warning("City boundary geojson must be a FeatureCollection.")
        return []

    rings: list[list[tuple[float, float]]] = []

    def append_ring(raw_ring: list[list[float]]) -> None:
        cleaned: list[tuple[float, float]] = []
        for pair in raw_ring:
            if (
                isinstance(pair, (list, tuple))
                and len(pair) >= 2
                and isinstance(pair[0], (int, float))
                and isinstance(pair[1], (int, float))
            ):
                lon, lat = pair[0], pair[1]
                cleaned.append((lat, lon))
        if len(cleaned) >= 2:
            rings.append(cleaned)

    for feature in features:
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict):
            continue
        gtype = geometry.get("type")
        coords = geometry.get("coordinates")
        if not coords:
            continue
        if gtype == "Polygon" and isinstance(coords, list):
            append_ring(coords[0] if coords else [])
        elif gtype == "MultiPolygon" and isinstance(coords, list):
            for poly in coords:
                if poly:
                    append_ring(poly[0])

    if not rings:
        logger.warning("City boundary geojson has no polygon data.")
        return []
    return rings



def load_line_stop_edges(service: "PlannerService") -> dict[str, list[str]]:
    """读取 line_stop_edges.csv，构建线路停靠顺序 / line_stop_edges.csv から路線停留順を構築する。"""
    path = service.data_dir / "line_stop_edges.csv"
    mapping: dict[str, list[str]] = defaultdict(list)
    if not path.exists():
        logger.warning("line_stop_edges.csv missing; RAPTOR coverage may be limited.")
        return mapping
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            line_id = str(row.get("line_id") or "")
            stop_id = str(row.get("station_code") or "")
            if not line_id or not stop_id:
                continue
            mapping[line_id].append(stop_id)
    logger.info(f"Loaded {len(mapping)} line-stop mappings.")
    return mapping


def distance_point_to_polyline(service: "PlannerService", lat: float, lon: float) -> float:
    """????????????????? / ???????????????"""
    if not service.city_boundary:
        return float("inf")
    px, py = project_to_plane(lat, lon, *service.hakata_coord)
    min_dist = float("inf")
    for ring in service.city_boundary:
        if len(ring) < 2:
            continue
        for idx in range(len(ring) - 1):
            lat_a, lon_a = ring[idx]
            lat_b, lon_b = ring[idx + 1]
            ax, ay = project_to_plane(lat_a, lon_a, *service.hakata_coord)
            bx, by = project_to_plane(lat_b, lon_b, *service.hakata_coord)
            dist = point_segment_distance(px, py, ax, ay, bx, by)
            if dist < min_dist:
                min_dist = dist
    return min_dist



def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """计算点到线段的距离 / 点と線分の距離を算出する。"""
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nx = ax + t * dx
    ny = ay + t * dy
    return math.hypot(px - nx, py - ny)


def build_boundary_sequence(service: "PlannerService") -> None:
    """根据边界筛站点，生成城市环候选序列 / 境界条件から停留所を抽出しループ候補列を構築する。"""
    if not service.city_boundary:
        service.boundary_sequence = []
        service.boundary_index = {}
        return
    
    candidates: dict[str, tuple[float, str]] = {}
    for code, station in service.stations.items():
        dist = distance_point_to_polyline(service, station.lat, station.lon)
        if not (BOUNDARY_MIN_DIST_KM <= dist <= BOUNDARY_MAX_DIST_KM):
            continue
        radius = distance_km(station.lat, station.lon, *service.hakata_coord)
        if radius < service.inner_radius_km:
            continue
        candidates[code] = (dist, code)

    if not candidates:
        service.boundary_sequence = []
        service.boundary_index = {}
        return

    selected: list[tuple[float, str]] = []
    for _, code in candidates.values():
        station = service.stations.get(code)
        if not station:
            continue
        x, y = project_to_plane(station.lat, station.lon, *service.hakata_coord)
        angle = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
        selected.append((angle, code))

    selected.sort()

    filtered: list[str] = [code for angle, code in selected]

    if service.hakata_stops:
        filtered = [service.hakata_stops[0]] + filtered + [service.hakata_stops[0]]

    seen: set[str] = set()
    sequence: list[str] = []
    for code in filtered:
        if code in seen:
            continue
        sequence.append(code)
        seen.add(code)

    service.boundary_sequence = sequence
    service.boundary_index = {code: idx for idx, code in enumerate(sequence)}


def find_latest_data_file(service: "PlannerService") -> Path | None:
    """寻找最新的 segments 或 timetable 文件 / 最新のsegments/timetableファイルを探す。"""
    for prefix in (SEGMENTS_PREFIX, TIMETABLE_PREFIX):
        candidates = sorted(
            service.data_dir.glob(f"{prefix}*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def load_edges(service: "PlannerService", data_path: Path | None) -> None:
    """加载CSV并生成 TripEdge 列表 / CSVを読みTripEdge一覧を生成する。"""
    if data_path is None:
        raise RuntimeError("segments_YYYYMMDD.csv または timetable_YYYYMMDD.csv が見つかりません")
    if data_path.name.startswith(SEGMENTS_PREFIX):
        edges = load_segment_edges(service, data_path)
    else:
        edges = load_timetable_edges(service, data_path)
    if not edges:
        raise RuntimeError("エッジデータの読み込みに失敗しました")
    service.static_edges = edges
    service._timetable_manager.load_static_edges(edges)
    service._refresh_stop_schedules(force_refresh=True)


def load_segment_edges(service: "PlannerService", segment_path: Path) -> list[TripEdge]:
    """读取 segments CSV 并转换为边 / segments CSV を読みエッジへ変換する。"""
    edges: list[TripEdge] = []
    with segment_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {
            "line_id",
            "direction",
            "service_date",
            "segment_id",
            "from_stop",
            "to_stop",
            "depart",
            "arrive",
        }
        if not required.issubset(set(reader.fieldnames or [])):
            raise RuntimeError("segments CSV の列構成が想定外です")
        for row in reader:
            line_id = str(row.get("line_id") or "")
            if line_id not in service.eligible_lines:
                continue
            from_code = str(row.get("from_stop") or "")
            to_code = str(row.get("to_stop") or "")
            if from_code not in service.stations or to_code not in service.stations:
                continue
            depart = parse_segment_minutes(row.get("depart"))
            arrive = parse_segment_minutes(row.get("arrive"))
            if depart is None or arrive is None:
                continue
            if arrive <= depart:
                arrive += 1440
            st_a = service.stations[from_code]
            st_b = service.stations[to_code]
            trip_identifier = str(
                row.get("trip_id")
                or row.get("segment_id")
                or f"{line_id}-{from_code}-{to_code}"
            )
            edges.append(
                TripEdge(
                    line_id=line_id,
                    line_name=service.line_names.get(line_id, line_id),
                    trip_id=trip_identifier,
                    direction=str(row.get("direction") or ""),
                    service_date=str(row.get("service_date") or ""),
                    from_code=from_code,
                    from_name=row.get("from_name") or st_a.name,
                    to_code=to_code,
                    to_name=row.get("to_name") or st_b.name,
                    depart=depart,
                    arrive=arrive,
                    distance_km=haversine_km(st_a, st_b),
                    from_lat=st_a.lat,
                    from_lon=st_a.lon,
                    to_lat=st_b.lat,
                    to_lon=st_b.lon,
                )
            )
    return edges


def load_timetable_edges(service: "PlannerService", timetable_path: Path) -> list[TripEdge]:
    """解析 timetable CSV 为 TripEdge 列表 / timetable CSV を解析しTripEdge一覧を得る。"""
    rows_by_trip: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    with timetable_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            line_code = str(row.get("operationLineCode") or "")
            if line_code not in service.eligible_lines:
                continue
            station_code = str(row.get("station_code") or "")
            if station_code not in service.stations:
                continue
            try:
                seq = int(row.get("stop_seq") or 0)
            except ValueError:
                seq = 0
            row["_seq"] = seq
            key = (
                line_code,
                str(row.get("direction") or ""),
                str(row.get("service_date") or ""),
                str(row.get("trip_id") or ""),
            )
            rows_by_trip[key].append(row)
    if not rows_by_trip:
        raise RuntimeError("時刻表から有効な trip データを読み込めませんでした")
    edges: list[TripEdge] = []
    for (line_id, direction, service_date, trip_id), rows in rows_by_trip.items():
        rows.sort(key=lambda r: r["_seq"])
        edges.extend(
            rows_to_edges(
                service=service,
                line_id=line_id,
                direction=direction,
                service_date=service_date,
                trip_id=trip_id,
                rows=rows,
            )
        )
    return edges


def rows_to_edges(
    service: "PlannerService",
    line_id: str,
    direction: str,
    service_date: str,
    trip_id: str,
    rows: Sequence[dict],
) -> list[TripEdge]:
    """把单趟行程的原始行转换为 TripEdge 序列 / 1便分の行データをTripEdge列へ変換する。"""
    edges: list[TripEdge] = []
    try:
        base_dt = datetime.strptime(service_date or "19700101", "%Y%m%d")
    except ValueError:
        base_dt = datetime.strptime("19700101", "%Y%m%d")
    prev_minutes: int | None = None
    rollover = 0

    def normalize_time(raw: str | None) -> int | None:
        nonlocal prev_minutes, rollover
        if not raw:
            return None
        raw = raw.strip()
        dt_val = parse_datetime(raw, base_dt)
        if dt_val is None:
            return None
        minutes = int((dt_val - base_dt).total_seconds() // 60)
        if prev_minutes is not None and minutes + rollover + 600 < prev_minutes:
            rollover += 1440
        minutes += rollover
        prev_minutes = minutes
        return minutes

    enriched = []
    for row in rows:
        dep = normalize_time(row.get("dep") or row.get("Departure"))
        arr = normalize_time(row.get("arr") or row.get("Arrival"))
        enriched.append(
            {
                "station_code": str(row.get("station_code")),
                "dep": dep,
                "arr": arr,
            }
        )

    for from_row, to_row in zip(enriched, enriched[1:], strict=False):
        from_code = str(from_row["station_code"])
        to_code = str(to_row["station_code"])
        if from_code not in service.stations or to_code not in service.stations:
            continue
        depart = from_row["dep"]
        arrive = to_row["arr"]
        if depart is None or arrive is None or arrive <= depart:
            continue
        st_a = service.stations[from_code]
        st_b = service.stations[to_code]
        edges.append(
            TripEdge(
                line_id=line_id,
                line_name=service.line_names.get(line_id, line_id),
                trip_id=trip_id,
                direction=direction,
                service_date=service_date,
                from_code=from_code,
                from_name=st_a.name,
                to_code=to_code,
                to_name=st_b.name,
                depart=depart,
                arrive=arrive,
                distance_km=haversine_km(st_a, st_b),
                from_lat=st_a.lat,
                from_lon=st_a.lon,
                to_lat=st_b.lat,
                to_lon=st_b.lon,
            )
        )
    return edges


def parse_segment_minutes(raw: str | None) -> int | None:
    """解析 segments CSV 的时间字段 / segments CSV の時間文字列を解析する。"""
    if not raw:
        return None
    text = raw.strip()
    if len(text) < 5 or text[2] != ":":
        return None
    try:
        hours = int(text[0:2])
        minutes = int(text[3:5])
    except ValueError:
        return None
    return hours * 60 + minutes
