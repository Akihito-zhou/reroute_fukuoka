from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Sequence

from .planner_constants import REST_SUGGESTIONS, REST_STOP_THRESHOLD
from .planner_models import LegPlan, TripEdge


def haversine_km(a, b) -> float:
    """计算两个站点间的大圆距离 / 2地点間の大円距離を計算する。"""
    r = 6371.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def format_minutes(total_minutes: int) -> str:
    """把分钟数格式化为时刻字符串 / 分単位を時刻文字列に整形する。"""
    if total_minutes < 0:
        total_minutes = 0
    days, minutes = divmod(total_minutes, 1440)
    hours, mins = divmod(minutes, 60)
    base = f"{hours:02d}:{mins:02d}"
    if days == 0:
        return base
    return f"+{days}d {base}"


def generate_rest_stops(legs: Sequence[LegPlan]) -> list[dict]:
    """根据停留间隔生成休息建议 / 区間の待ち時間に応じて休憩案を生成する。"""
    results: list[dict] = []
    for prev, nxt in zip(legs, legs[1:], strict=False):
        gap = nxt.depart - prev.arrive
        if gap < REST_STOP_THRESHOLD:
            continue
        suggestion = REST_SUGGESTIONS[len(results) % len(REST_SUGGESTIONS)]
        at_name = prev.to_name or prev.to_code
        results.append(
            {
                "at": at_name,
                "minutes": gap,
                "suggestion": suggestion,
            }
        )
    return results


def collapse_edges(
    edges: Sequence[TripEdge], stations: dict[str, "Station"]
) -> list[LegPlan]:
    """把连续同线路的边压缩成LegPlan / 同一路線の連続エッジをまとめてLegPlan化する。"""
    if not edges:
        return []
    legs: list[LegPlan] = []
    buffer = [edges[0]]
    for edge in edges[1:]:
        last = buffer[-1]
        if edge.trip_id == last.trip_id and edge.line_id == last.line_id:
            buffer.append(edge)
        else:
            legs.append(_compress_buffer(buffer, stations))
            buffer = [edge]
    if buffer:
        legs.append(_compress_buffer(buffer, stations))
    return legs


def _compress_buffer(
    buffer: Sequence[TripEdge], stations: dict[str, "Station"]
) -> LegPlan:
    """辅助函数：将缓冲区内的边合并 / 補助関数：バッファ内のエッジをマージする。"""
    first = buffer[0]
    last = buffer[-1]

    from_station = stations.get(first.from_code)
    to_station = stations.get(last.to_code)

    from_name = from_station.name if from_station else first.from_name
    to_name = to_station.name if to_station else last.to_name
    from_lat = from_station.lat if from_station else first.from_lat
    from_lon = from_station.lon if from_station else first.from_lon
    to_lat = to_station.lat if to_station else last.to_lat
    to_lon = to_station.lon if to_station else last.to_lon

    distance = sum(edge.distance_km for edge in buffer)
    ride_minutes = last.arrive - first.depart
    path: list[tuple[float, float]] = []
    for idx, edge in enumerate(buffer):
        edge_from_station = stations.get(edge.from_code)
        edge_to_station = stations.get(edge.to_code)
        if idx == 0:
            path.append(
                (
                    edge_from_station.lat if edge_from_station else 0.0,
                    edge_from_station.lon if edge_from_station else 0.0,
                )
            )
        path.append(
            (
                edge_to_station.lat if edge_to_station else 0.0,
                edge_to_station.lon if edge_to_station else 0.0,
            )
        )

    return LegPlan(
        line_id=first.line_id,
        line_name=first.line_name,
        trip_id=first.trip_id,
        from_code=first.from_code,
        from_name=from_name,
        to_code=last.to_code,
        to_name=to_name,
        depart=first.depart,
        arrive=last.arrive,
        ride_minutes=ride_minutes,
        distance_km=distance,
        stop_hops=len(buffer),
        path=path,
        from_lat=from_lat,
        from_lon=from_lon,
        to_lat=to_lat,
        to_lon=to_lon,
    )


def derive_quadrant_labels(legs: Sequence[LegPlan], quadrant_map: dict[str, int]) -> list[str]:
    """根据行程覆盖返回象限标签 / 走行軌跡のカバレッジから象限ラベルを返す。"""
    labels = {
        1: "福岡市北東エリア",
        2: "福岡市南東エリア",
        4: "福岡市南西エリア",
        8: "福岡市北西エリア",
    }
    visited = Counter()
    for leg in legs:
        visited.update([quadrant_map.get(leg.from_code, 0)])
        visited.update([quadrant_map.get(leg.to_code, 0)])
    out = []
    for bit, label in labels.items():
        if visited.get(bit):
            out.append(label)
    return out or ["福岡市内"]


def parse_datetime(raw: str, base_dt: datetime) -> datetime | None:
    """解析多种日期时间格式 / 複数フォーマットの日時文字列を解析する。"""
    text = raw.strip()
    fmts = [
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]
    if len(text) == 4 and text.isdigit():
        hours = int(text[:2])
        mins = int(text[2:])
        return base_dt.replace(hour=hours, minute=mins, second=0)
    if len(text) == 5 and text[2] == ":":
        hours = int(text[:2])
        mins = int(text[3:])
        return base_dt.replace(hour=hours, minute=mins, second=0)
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text and text.count(":") >= 2 and "T" in text:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates the Haversine distance between two points in kilometers."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def project_to_plane(
    lat: float, lon: float, base_lat: float, base_lon: float
) -> tuple[float, float]:
    """Projects lat/lon coordinates to a 2D plane relative to a base coordinate."""
    lat_diff = lat - base_lat
    lon_diff = lon - base_lon
    cos_lat = math.cos(math.radians(base_lat))
    x = lon_diff * cos_lat * 111.320  # km
    y = lat_diff * 110.574  # km
    return x, y


def label_leg_to_plan(leg: "JourneyLeg", stations: dict[str, "Station"]) -> LegPlan:
    from_station = stations.get(leg.from_code)
    to_station = stations.get(leg.to_code)
    from_name = from_station.name if from_station else leg.from_code
    to_name = to_station.name if to_station else leg.to_code
    from_lat = from_station.lat if from_station else 0.0
    from_lon = from_station.lon if from_station else 0.0
    to_lat = to_station.lat if to_station else 0.0
    to_lon = to_station.lon if to_station else 0.0
    path = [(from_lat, from_lon), (to_lat, to_lon)]
    ride_minutes = max(0, leg.arrive - leg.depart)
    return LegPlan(
        line_id=leg.line_id,
        line_name=leg.line_name,
        trip_id=leg.trip_id,
        from_code=leg.from_code,
        from_name=from_name,
        to_code=leg.to_code,
        to_name=to_name,
        depart=leg.depart,
        arrive=leg.arrive,
        ride_minutes=ride_minutes,
        distance_km=leg.distance_km,
        stop_hops=leg.stop_hops,
        path=path,
        from_lat=from_lat,
        from_lon=from_lon,
        to_lat=to_lat,
        to_lon=to_lon,
    )


__all__ = [
    "collapse_edges",
    "derive_quadrant_labels",
    "format_minutes",
    "generate_rest_stops",
    "haversine_km",
    "parse_datetime",
    "distance_km",
    "project_to_plane",
    "label_leg_to_plan",
]
