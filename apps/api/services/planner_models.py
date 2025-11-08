from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from .planner_constants import START_TIME_MINUTES, TRANSFER_BUFFER_MINUTES


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class TripEdge:
    line_id: str
    line_name: str
    trip_id: str
    direction: str
    service_date: str
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    depart: int
    arrive: int
    distance_km: float
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float

    @property
    def ride_minutes(self) -> int:
        """返回本段乘车分钟 / この区間の乗車分を返す。"""
        return max(0, self.arrive - self.depart)


@dataclass
class StopSchedule:
    departures: list[int] = field(default_factory=list)
    edges: list[TripEdge] = field(default_factory=list)

    def add_edge(self, edge: TripEdge) -> None:
        """向站点时刻表追加一条边 / 停留所スケジュールにエッジを追加する。"""
        self.departures.append(edge.depart)
        self.edges.append(edge)

    def finalize(self) -> None:
        """按照出发时间排序固化 / 出発時刻順にソートして確定させる。"""
        if not self.departures:
            return
        combined = sorted(zip(self.departures, self.edges, strict=False), key=lambda pair: pair[0])
        self.departures = [d for d, _ in combined]
        self.edges = [e for _, e in combined]


@dataclass
class LegPlan:
    line_id: str
    line_name: str
    trip_id: str
    from_code: str
    from_name: str
    to_code: str
    to_name: str
    depart: int
    arrive: int
    ride_minutes: int
    distance_km: float
    stop_hops: int
    path: list[tuple[float, float]]
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float


@dataclass(frozen=True)
class JourneyLeg:
    line_id: str
    line_name: str
    trip_id: str
    from_code: str
    to_code: str
    depart: int
    arrive: int
    distance_km: float
    stop_hops: int


@dataclass(frozen=True)
class Label:
    arrival: int
    ride_minutes: int
    distance_km: float
    visited: frozenset[str]
    quadrant_mask: int
    legs: tuple[JourneyLeg, ...]
    score: float
    stop_counts: tuple[tuple[str, int], ...] = field(default_factory=tuple, compare=False)
    line_counts: tuple[tuple[str, int], ...] = field(default_factory=tuple, compare=False)
    transfers: int = field(default=0, compare=False)
    min_transfer_gap: int = field(default=10**9, compare=False)


@dataclass(frozen=True)
class ChallengeConfig:
    challenge_id: str
    title: str
    tagline: str
    theme_tags: list[str]
    badge: str
    require_quadrants: bool
    max_rounds: int
    scoring_fn: Callable[[Label, dict[str, float]], float]
    dominance_fn: Callable[[Label, dict[str, float], Label, dict[str, float]], bool]
    accept_fn: Callable[[Label, dict[str, float]], bool]
    min_transfer_minutes: int = TRANSFER_BUFFER_MINUTES
    transfer_penalty_minutes: int = 0
    max_stop_visits: int | None = None
    max_line_visits: int | None = None
    forbid_non_hakata_duplicates: bool = False
    allow_hakata_revisit: bool = True
    hakata_max_visits: int | None = None
    stop_repeat_penalty_weight: int = 0


@dataclass
class RouteTrip:
    trip_id: str
    departures: list[int]
    arrivals: list[int]
    segment_distances: list[float]


@dataclass
class RouteData:
    line_id: str
    direction: str
    line_name: str
    stops: list[str]
    stop_to_index: dict[str, int]
    trips: list[RouteTrip]


@dataclass
class ChallengePlan:
    challenge_id: str
    title: str
    tagline: str
    theme_tags: list[str]
    badge: str
    legs: list[LegPlan]
    start_stop_name: str
    wards: list[str]

    def to_dict(self) -> dict:
        """把计划转换为API字典 / プランをAPI用の辞書に変換する。"""
        from .planner_utils import format_minutes, generate_rest_stops

        legs_payload = [
            {
                "sequence": idx + 1,
                "line_label": leg.line_id,
                "line_name": leg.line_name,
                "from_stop": leg.from_name,
                "to_stop": leg.to_name,
                "departure": format_minutes(leg.depart),
                "arrival": format_minutes(leg.arrive),
                "ride_minutes": leg.ride_minutes,
                "distance_km": round(leg.distance_km, 2),
                "notes": [f"停車数 {leg.stop_hops + 1}"],
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[round(lon, 6), round(lat, 6)] for lat, lon in leg.path],
                },
                "path": [{"lat": round(lat, 6), "lon": round(lon, 6)} for lat, lon in leg.path],
                "from_coord": {"lat": round(leg.from_lat, 6), "lon": round(leg.from_lon, 6)},
                "to_coord": {"lat": round(leg.to_lat, 6), "lon": round(leg.to_lon, 6)},
            }
            for idx, leg in enumerate(self.legs)
        ]
        rest_stops = generate_rest_stops(self.legs)
        total_minutes = sum(leg.ride_minutes for leg in self.legs)
        total_distance = sum(leg.distance_km for leg in self.legs)
        return {
            "id": self.challenge_id,
            "title": self.title,
            "tagline": self.tagline,
            "theme_tags": self.theme_tags,
            "start_stop": self.start_stop_name,
            "start_time": format_minutes(START_TIME_MINUTES),
            "total_ride_minutes": total_minutes,
            "total_distance_km": round(total_distance, 1),
            "transfers": max(0, len(self.legs) - 1),
            "wards": self.wards or ["福岡市内"],
            "badges": [self.badge],
            "legs": legs_payload,
            "rest_stops": rest_stops,
        }


@dataclass(order=True)
class SearchState:
    priority: float
    ride_minutes: int = field(compare=False)
    current_time: int = field(compare=False)
    stop_code: str = field(compare=False)
    path: tuple[TripEdge, ...] = field(compare=False, default=())
    unique_count: int = field(compare=False, default=0)
    quadrant_mask: int = field(compare=False, default=0)
    stop_visit_counts: dict[str, int] = field(compare=False, default_factory=dict)
    line_visit_counts: dict[str, int] = field(compare=False, default_factory=dict)
    transfers: int = field(compare=False, default=0)


__all__ = [
    "ChallengeConfig",
    "ChallengePlan",
    "JourneyLeg",
    "Label",
    "LegPlan",
    "RouteData",
    "RouteTrip",
    "SearchState",
    "Station",
    "StopSchedule",
    "TripEdge",
]
