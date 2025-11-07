from __future__ import annotations

import csv
import heapq
import json
import logging
import math
import os
import threading
import time
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import yaml

try:  # pragma: no cover - allow running as either package or module
    from ..clients.ekispert_bus import EkispertBusClient
except ImportError:  # pragma: no cover
    from clients.ekispert_bus import EkispertBusClient  # type: ignore

try:  # pragma: no cover - allow running as either package or module
    from .realtime_timetable import RealtimeTimetableManager
except ImportError:  # pragma: no cover
    from realtime_timetable import RealtimeTimetableManager  # type: ignore

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TIMETABLE_PREFIX = "timetable_"
SEGMENTS_PREFIX = "segments_"

START_TIME_MINUTES = 7 * 60  # 07:00
TRANSFER_BUFFER_MINUTES = 3
MAX_BRANCH_PER_EXPANSION = 6
MAX_QUEUE_SIZE = 2000
MAX_EXPANSIONS = 120000
REST_STOP_THRESHOLD = 15  # minutes
DEFAULT_REALTIME_CACHE_SECONDS = 120
MAX_LABELS_PER_STOP = 6
MAX_TRANSFERS = 8
ALL_QUADRANTS_MASK = 1 | 2 | 4 | 8
BOUNDARY_BIN_COUNT = 18
BOUNDARY_MIN_DIST_KM = 0.3
BOUNDARY_MAX_DIST_KM = 4.0
MAX_ROUTES_FOR_RAPTOR = 120
MAX_TRIPS_PER_ROUTE = 25

REST_SUGGESTIONS = [
    "コンビニで飲み物を補給しよう。",
    "近くのベーカリーでテイクアウトを。",
    "周辺を5分だけ散策して気分転換。",
    "ベンチで次のルートを確認しよう。",
    "軽くストレッチしてリフレッシュ。",
]


logger = logging.getLogger(__name__)
class PlannerError(RuntimeError):
    """Raised when the planner cannot compute challenges."""


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
        return max(0, self.arrive - self.depart)


@dataclass
class StopSchedule:
    departures: list[int] = field(default_factory=list)
    edges: list[TripEdge] = field(default_factory=list)

    def add_edge(self, edge: TripEdge) -> None:
        self.departures.append(edge.depart)
        self.edges.append(edge)

    def finalize(self) -> None:
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
    stop_counts: tuple[tuple[str, int], ...] = field(
        default_factory=tuple, compare=False
    )
    line_counts: tuple[tuple[str, int], ...] = field(
        default_factory=tuple, compare=False
    )
    transfers: int = field(default=0, compare=False)
    min_transfer_gap: int = field(default=10**9, compare=False)


@dataclass(frozen=True)
class ChallengeConfig:
    """
    Tunable knobs per challenge. Feel free to adjust these when you need to
    rebalance feasibility vs. exploration:

    - min_transfer_minutes / transfer_penalty_minutes:
        Enforce minimum wait buffer and penalize excessive transfers.
    - max_stop_visits / hakata_max_visits:
        Hard cap on how many times a stop may appear in one itinerary.
        Use hakata_max_visits to allow slightly more visits for Hakata only.
    - max_line_visits:
        Limits how often the same line can be boarded (helps prevent looping).
    - stop_repeat_penalty_weight:
        Soft penalty applied to every repeated stop (even if under the hard cap).
        Raise this value when you want RAPTOR to strongly avoid revisits without
        completely cutting search feasibility.
    - forbid_non_hakata_duplicates / allow_hakata_revisit:
        Toggle whether non-Hakata stops may repeat at all and whether Hakata is
        allowed special treatment.
    """
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
                "notes": [f"停車数: {leg.stop_hops + 1}"],
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [round(lon, 6), round(lat, 6)] for lat, lon in leg.path
                    ],
                },
                "path": [
                    {"lat": round(lat, 6), "lon": round(lon, 6)}
                    for lat, lon in leg.path
                ],
                "from_coord": {
                    "lat": round(leg.from_lat, 6),
                    "lon": round(leg.from_lon, 6),
                },
                "to_coord": {
                    "lat": round(leg.to_lat, 6),
                    "lon": round(leg.to_lon, 6),
                },
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


def haversine_km(a: Station, b: Station) -> float:
    r = 6371.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


def format_minutes(total_minutes: int) -> str:
    if total_minutes < 0:
        total_minutes = 0
    days, minutes = divmod(total_minutes, 1440)
    hours, mins = divmod(minutes, 60)
    base = f"{hours:02d}:{mins:02d}"
    if days == 0:
        return base
    return f"+{days}d {base}"


def generate_rest_stops(legs: Sequence[LegPlan]) -> list[dict]:
    suggestions = []
    for prev, nxt in zip(legs, legs[1:], strict=False):
        idle = nxt.depart - prev.arrive
        if idle >= REST_STOP_THRESHOLD:
            idx = sum(ord(ch) for ch in prev.to_code) % len(REST_SUGGESTIONS)
            suggestions.append(
                {
                    "at": prev.to_name,
                    "minutes": idle,
                    "suggestion": REST_SUGGESTIONS[idx],
                }
            )
    return suggestions


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class PlannerService:
    """Generates challenge plans based on stored timetable + geo data."""

    def __init__(
        self,
        data_dir: Path | None = None,
        *,
        enable_realtime: bool | None = None,
        api_key: str | None = None,
        realtime_cache_seconds: int = DEFAULT_REALTIME_CACHE_SECONDS,
    ):
        self.data_dir = Path(data_dir) if data_dir else DATA_DIR
        self._stations: dict[str, Station] = {}
        self._line_names: dict[str, str] = {}
        self._eligible_lines: set[str] = set()
        self._stop_schedules: dict[str, StopSchedule] = {}
        self._hakata_stops: list[str] = []
        self._quadrant_map: dict[str, int] = {}
        self._line_stop_edges: dict[str, list[str]] = {}
        self._cache: dict[str, ChallengePlan] | None = None
        self._cache_mtime: float = 0.0
        self._lock = threading.Lock()
        self._latest_data_file: Path | None = None
        self._static_edges: list[TripEdge] = []
        self._routes: dict[str, RouteData] = {}
        self._routes_by_stop: dict[str, set[str]] = defaultdict(set)
        self._hakata_coord: tuple[float, float] = (33.589, 130.420)
        self._inner_radius_km: float = 2.0
        self._city_boundary: list[tuple[float, float]] = []
        self._boundary_sequence: list[str] = []
        self._boundary_index: dict[str, int] = {}

        env_flag = os.getenv("PLANNER_ENABLE_REALTIME", "").strip().lower()
        env_enabled = env_flag in {"1", "true", "yes", "on"}
        self._realtime_cache_seconds = max(30, realtime_cache_seconds)
        desired_realtime = (
            enable_realtime if enable_realtime is not None else env_enabled
        )
        api_key_value = api_key or os.getenv("EKISPERT_API_KEY")
        client = (
            EkispertBusClient(api_key_value)
            if desired_realtime and api_key_value
            else None
        )
        if desired_realtime and not api_key_value:
            logger.warning(
                "Planner realtime mode requested but EKISPERT_API_KEY is missing; "
                "falling back to static data."
            )
        self._timetable_manager = RealtimeTimetableManager(
            client,
            enable_realtime=client is not None,
            cache_seconds=self._realtime_cache_seconds,
        )
        self._realtime_active = self._timetable_manager.realtime_enabled
        self._cache_generated_at = 0.0

    # ---------- public API ----------

    def list_challenges(self) -> list[dict]:
        plans = self._ensure_plans()
        return [plan.to_dict() for plan in plans.values()]

    def get_challenge(self, challenge_id: str) -> dict:
        plans = self._ensure_plans()
        if challenge_id not in plans:
            raise PlannerError(f"challenge '{challenge_id}' not available")
        return plans[challenge_id].to_dict()

    # ---------- bootstrap ----------

    def _ensure_plans(self) -> dict[str, ChallengePlan]:
        with self._lock:
            latest = self._find_latest_data_file()
            latest_mtime = latest.stat().st_mtime if latest else 0.0
            now_ts = time.time()
            static_stale = (
                not self._cache
                or self._latest_data_file != latest
                or self._cache_mtime < latest_mtime
            )
            realtime_stale = self._realtime_active and (
                now_ts - self._cache_generated_at >= self._realtime_cache_seconds
            )
            if self._cache and not static_stale and not realtime_stale:
                return self._cache

            if static_stale:
                self._load_static_assets()
                self._load_edges(latest)
            elif realtime_stale:
                self._refresh_stop_schedules(force_refresh=True)

            plans = self._compute_challenges()
            self._cache = plans
            self._cache_mtime = latest_mtime
            self._latest_data_file = latest
            # track for realtime invalidation
            self._cache_generated_at = now_ts
            return plans

    def _load_static_assets(self) -> None:
        self._stations = self._load_stations()
        self._line_names, self._eligible_lines = self._load_line_meta()
        self._hakata_stops = self._detect_hakata_stops()
        self._quadrant_map = self._assign_quadrants()
        if not self._hakata_stops:
            raise PlannerError("博多駅周辺の停留所が stations.csv から検出できません。")
        origin_station = self._stations.get(self._hakata_stops[0])
        if origin_station:
            self._hakata_coord = (origin_station.lat, origin_station.lon)
        self._city_boundary = self._load_city_boundary()
        self._line_stop_edges = self._load_line_stop_edges()

    def _load_stations(self) -> dict[str, Station]:
        path = self.data_dir / "stations.csv"
        if not path.exists():
            raise PlannerError("stations.csv が見つかりません。")
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
            raise PlannerError("stations.csv に有効なデータがありません。")
        return stations

    def _load_line_meta(self) -> tuple[dict[str, str], set[str]]:
        path = self.data_dir / "freepass_lines.yml"
        data = load_yaml(path)
        line_names: dict[str, str] = {}
        eligible = set()
        for row in data.get("freepass_lines", []):
            line_id = str(row.get("line_id"))
            if not line_id:
                continue
            name = row.get("name") or row.get("line_name") or line_id
            line_names[line_id] = name
            if row.get("eligible"):
                eligible.add(line_id)
        if not eligible:
            raise PlannerError("freepass_lines.yml に eligible な路線がありません。")
        return line_names, eligible

    def _detect_hakata_stops(self) -> list[str]:
        keywords = ["博多駅", "博多ﾊﾞｽﾀｰﾐﾅﾙ", "博多駅前", "博多ﾊﾞｽﾀ"]
        results = [
            code
            for code, st in self._stations.items()
            if any(keyword in st.name for keyword in keywords)
        ]
        # fallback: pick most frequent stations near Hakata (lat 33.59 lon 130.42)
        if not results:
            target_lat, target_lon = 33.589, 130.420
            ranked = sorted(
                self._stations.values(),
                key=lambda s: ((s.lat - target_lat) ** 2 + (s.lon - target_lon) ** 2),
            )
            results = [s.code for s in ranked[:5]]
        return results

    def _assign_quadrants(self) -> dict[str, int]:
        lats = [s.lat for s in self._stations.values()]
        lons = [s.lon for s in self._stations.values()]
        lat_mid = (min(lats) + max(lats)) / 2
        lon_mid = (min(lons) + max(lons)) / 2
        mapping: dict[str, int] = {}
        for code, st in self._stations.items():
            north = st.lat >= lat_mid
            east = st.lon >= lon_mid
            if north and east:
                mapping[code] = 1  # NE
            elif not north and east:
                mapping[code] = 2  # SE
            elif not north and not east:
                mapping[code] = 4  # SW
            else:
                mapping[code] = 8  # NW
        return mapping

    def _load_city_boundary(self) -> list[tuple[float, float]]:
        path = self.data_dir / "fukuoka_city.geojson"
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            return []
        coords: list[tuple[float, float]] = []
        if "features" in data:
            features = data.get("features") or []
            for feature in features:
                geometry = feature.get("geometry") or {}
                if geometry.get("type") == "Polygon":
                    rings = geometry.get("coordinates") or []
                    if rings:
                        coords = [(lat, lon) for lon, lat in rings[0]]
                        break
                elif geometry.get("type") == "MultiPolygon":
                    polygons = geometry.get("coordinates") or []
                    if polygons:
                        coords = [(lat, lon) for lon, lat in polygons[0][0]]
                        break
        elif "geometry" in data:
            geometry = data.get("geometry") or {}
            if geometry.get("type") == "Polygon":
                rings = geometry.get("coordinates") or []
                if rings:
                    coords = [(lat, lon) for lon, lat in rings[0]]
            elif geometry.get("type") == "MultiPolygon":
                polygons = geometry.get("coordinates") or []
                if polygons:
                    coords = [(lat, lon) for lon, lat in polygons[0][0]]
        return coords

    def _load_line_stop_edges(self) -> dict[str, list[str]]:
        path = self.data_dir / "line_stop_edges.csv"
        if not path.exists():
            return {}
        mapping: dict[str, list[str]] = defaultdict(list)
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"line_id", "station_code"}
            if not required.issubset(reader.fieldnames or []):
                return {}
            for row in reader:
                line_id = str(row.get("line_id") or "")
                station_code = str(row.get("station_code") or "")
                if line_id and station_code:
                    mapping[line_id].append(station_code)
        return mapping

    def _distance_point_to_polyline(self, lat: float, lon: float) -> float:
        if not self._city_boundary:
            return float("inf")
        px, py = self._project_to_plane(lat, lon)
        min_dist = float("inf")
        coords = self._city_boundary
        for idx in range(len(coords)):
            lat_a, lon_a = coords[idx]
            lat_b, lon_b = coords[(idx + 1) % len(coords)]
            ax, ay = self._project_to_plane(lat_a, lon_a)
            bx, by = self._project_to_plane(lat_b, lon_b)
            dist = self._point_segment_distance(px, py, ax, ay, bx, by)
            if dist < min_dist:
                min_dist = dist
        return min_dist

    @staticmethod
    def _point_segment_distance(
        px: float, py: float, ax: float, ay: float, bx: float, by: float
    ) -> float:
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        nx = ax + t * dx
        ny = ay + t * dy
        return math.hypot(px - nx, py - ny)

    def _build_boundary_sequence(self) -> None:
        if not self._city_boundary:
            self._boundary_sequence = []
            self._boundary_index = {}
            return
        candidate_by_bin: dict[int, tuple[float, str]] = {}
        for code, station in self._stations.items():
            dist = self._distance_point_to_polyline(station.lat, station.lon)
            if not (BOUNDARY_MIN_DIST_KM <= dist <= BOUNDARY_MAX_DIST_KM):
                continue
            radius = self._distance_km(station.lat, station.lon, *self._hakata_coord)
            if radius < self._inner_radius_km:
                continue
            x, y = self._project_to_plane(station.lat, station.lon)
            if x == 0 and y == 0:
                continue
            angle = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
            bin_idx = int(angle / 360.0 * BOUNDARY_BIN_COUNT) % BOUNDARY_BIN_COUNT
            existing = candidate_by_bin.get(bin_idx)
            if existing is None or dist < existing[0]:
                candidate_by_bin[bin_idx] = (dist, code)

        if not candidate_by_bin:
            self._boundary_sequence = []
            self._boundary_index = {}
            return

        selected: list[tuple[float, str]] = []
        for _bin_idx, (_dist, code) in candidate_by_bin.items():
            station = self._stations.get(code)
            if not station:
                continue
            x, y = self._project_to_plane(station.lat, station.lon)
            angle = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
            selected.append((angle, code))

        selected.sort()

        # ensure uniqueness and remove codes too close in angle
        filtered: list[str] = []
        last_angle = None
        for angle, code in selected:
            if (
                filtered
                and last_angle is not None
                and abs(angle - last_angle) < (360 / BOUNDARY_BIN_COUNT) / 2
            ):
                continue
            filtered.append(code)
            last_angle = angle

        if self._hakata_stops:
            filtered = [self._hakata_stops[0]] + filtered + [self._hakata_stops[0]]

        seen: set[str] = set()
        sequence: list[str] = []
        for code in filtered:
            if code in seen:
                continue
            sequence.append(code)
            seen.add(code)

        self._boundary_sequence = sequence
        self._boundary_index = {code: idx for idx, code in enumerate(sequence)}

    def _find_latest_data_file(self) -> Path | None:
        for prefix in (SEGMENTS_PREFIX, TIMETABLE_PREFIX):
            candidates = sorted(
                self.data_dir.glob(f"{prefix}*.csv"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]
        return None

    def _load_edges(self, data_path: Path | None) -> None:
        if data_path is None:
            raise PlannerError(
                "segments_YYYYMMDD.csv または timetable_YYYYMMDD.csv が見つかりません。"
            )
        if data_path.name.startswith(SEGMENTS_PREFIX):
            edges = self._load_segment_edges(data_path)
        else:
            edges = self._load_timetable_edges(data_path)
        if not edges:
            raise PlannerError("エッジデータの読み込みに失敗しました。")
        self._static_edges = edges
        self._timetable_manager.load_static_edges(edges)
        self._refresh_stop_schedules(force_refresh=True)
        if not self._stop_schedules:
            raise PlannerError("利用可能な便が見つかりませんでした。")
        self._build_route_timetables()

    def _refresh_stop_schedules(self, *, force_refresh: bool = False) -> None:
        horizon_start = START_TIME_MINUTES
        horizon_end = START_TIME_MINUTES + 24 * 60
        edges: list[TripEdge] = []
        if self._timetable_manager:
            edges = self._timetable_manager.get_edges_for_window(
                horizon_start,
                horizon_end,
                line_filter=self._eligible_lines,
                force_refresh=force_refresh,
            )
        if not edges:
            edges = [
                edge
                for edge in self._static_edges
                if edge.arrive >= horizon_start and edge.depart <= horizon_end
            ]
        if not edges:
            logger.warning(
                "No timetable edges available between %s and %s minutes.",
                horizon_start,
                horizon_end,
            )
            self._stop_schedules = {}
            return
        schedules: dict[str, StopSchedule] = defaultdict(StopSchedule)
        for edge in edges:
            schedules[edge.from_code].add_edge(edge)
        if not schedules and edges:
            logger.warning(
                "Edges available but no schedules were constructed; check data integrity."
            )
        for sched in schedules.values():
            sched.finalize()
        self._stop_schedules = schedules
        self._build_route_timetables()

    def _build_route_timetables(self) -> None:
        routes: dict[str, RouteData] = {}
        routes_by_stop: dict[str, set[str]] = defaultdict(set)
        trip_groups: dict[str, dict[str, list[TripEdge]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for edge in self._static_edges:
            if edge.line_id not in self._eligible_lines:
                continue
            route_key = f"{edge.line_id}:{edge.direction}"
            trip_groups[route_key][edge.trip_id].append(edge)

        for _route_idx, (route_key, trips) in enumerate(trip_groups.items()):
            if not trips:
                continue
            sample_edges = next(iter(trips.values()))
            if not sample_edges:
                continue
            any_edge = sample_edges[0]
            base_stops = self._line_stop_edges.get(any_edge.line_id, [])
            if not base_stops:
                continue
            if any_edge.direction.lower() in {"down", "outbound", "reverse"}:
                base_sequence = list(reversed(base_stops))
            else:
                base_sequence = list(base_stops)
            if len(base_sequence) < 2:
                continue
            pair_set = {
                (edge.from_code, edge.to_code)
                for edges in trips.values()
                for edge in edges
            }
            stops_seq: list[str] = []
            for idx in range(len(base_sequence) - 1):
                stops_seq.append(base_sequence[idx])
                if (base_sequence[idx], base_sequence[idx + 1]) not in pair_set:
                    break
            else:
                stops_seq.append(base_sequence[-1])

            if len(stops_seq) < 2:
                continue
            # if len(stops_seq) > 15:
            #     stops_seq = stops_seq[:15]
            for edge_list in trips.values():
                edge_list.sort(key=lambda e: e.depart)
            stop_to_index = {code: idx for idx, code in enumerate(stops_seq)}

            route_trips: list[RouteTrip] = []
            for trip_id, edge_list in trips.items():
                departures: list[int | None] = [None] * len(stops_seq)
                arrivals: list[int | None] = [None] * len(stops_seq)
                segment_distances: list[float] = [0.0] * (len(stops_seq) - 1)
                trip_valid = True
                for edge in edge_list:
                    from_idx = stop_to_index.get(edge.from_code)
                    to_idx = stop_to_index.get(edge.to_code)
                    if from_idx is None or to_idx is None or to_idx != from_idx + 1:
                        trip_valid = False
                        break
                    departures[from_idx] = edge.depart
                    arrivals[to_idx] = edge.arrive
                    segment_distances[from_idx] = edge.distance_km
                if not trip_valid:
                    continue
                for idx in range(len(stops_seq) - 1):
                    if departures[idx] is None:
                        matching = next(
                            (e for e in edge_list if e.from_code == stops_seq[idx]),
                            None,
                        )
                        if matching is None:
                            trip_valid = False
                            break
                        departures[idx] = matching.depart
                    if arrivals[idx + 1] is None:
                        trip_valid = False
                        break
                    if arrivals[idx + 1] <= departures[idx]:
                        trip_valid = False
                        break
                if not trip_valid:
                    continue
                if arrivals[-1] is None:
                    arrivals[-1] = arrivals[-2]
                if departures[-1] is None and arrivals[-1] is not None:
                    departures[-1] = arrivals[-1]
                arrivals[0] = departures[0]
                departures_final: list[int] = []
                arrivals_final: list[int] = []
                trip_valid = True
                for value in departures:
                    if value is None:
                        trip_valid = False
                        break
                    departures_final.append(int(value))
                if not trip_valid:
                    continue
                for value in arrivals:
                    if value is None:
                        trip_valid = False
                        break
                    arrivals_final.append(int(value))
                if not trip_valid:
                    continue
                route_trips.append(
                    RouteTrip(
                        trip_id=trip_id,
                        departures=departures_final,
                        arrivals=arrivals_final,
                        segment_distances=segment_distances,
                    )
                )

            if not route_trips:
                continue
            any_edge = sample_edges[0]
            line_name = self._line_names.get(any_edge.line_id, any_edge.line_id)
            # limit number of trips per route (prefer先出発)
            if len(route_trips) > MAX_TRIPS_PER_ROUTE:
                route_trips.sort(key=lambda trip: trip.departures[0])
                route_trips = route_trips[:MAX_TRIPS_PER_ROUTE]

            routes[route_key] = RouteData(
                line_id=any_edge.line_id,
                direction=any_edge.direction,
                line_name=line_name,
                stops=stops_seq,
                stop_to_index=stop_to_index,
                trips=route_trips,
            )
            for stop in stops_seq:
                routes_by_stop[stop].add(route_key)
            if len(routes) >= MAX_ROUTES_FOR_RAPTOR:
                break

        self._routes = routes
        self._routes_by_stop = {stop: set(ids) for stop, ids in routes_by_stop.items()}
        self._build_boundary_sequence()

    def _load_timetable_edges(self, timetable_path: Path) -> list[TripEdge]:
        rows_by_trip: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
        with timetable_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                line_code = str(row.get("operationLineCode") or "")
                if line_code not in self._eligible_lines:
                    continue
                station_code = str(row.get("station_code") or "")
                if station_code not in self._stations:
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
            raise PlannerError(
                "時刻表から有効な trip データを読み込めませんでした。"
                "freepass 路線と日付を確認してください。"
            )
        edges: list[TripEdge] = []
        for (line_id, direction, service_date, trip_id), rows in rows_by_trip.items():
            rows.sort(key=lambda r: r["_seq"])
            edges.extend(
                self._rows_to_edges(
                    line_id=line_id,
                    direction=direction,
                    service_date=service_date,
                    trip_id=trip_id,
                    rows=rows,
                )
            )
        return edges

    def _rows_to_edges(
        self,
        line_id: str,
        direction: str,
        service_date: str,
        trip_id: str,
        rows: Sequence[dict],
    ) -> list[TripEdge]:
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

        for idx in range(len(enriched) - 1):
            cur = enriched[idx]
            nxt = enriched[idx + 1]
            depart = cur["dep"] or cur["arr"]
            arrive = nxt["arr"] or nxt["dep"]
            if depart is None or arrive is None or arrive <= depart:
                continue
            from_code = cur["station_code"]
            to_code = nxt["station_code"]
            if from_code not in self._stations or to_code not in self._stations:
                continue
            st_a = self._stations[from_code]
            st_b = self._stations[to_code]
            edge = TripEdge(
                line_id=line_id,
                line_name=self._line_names.get(line_id, line_id),
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
            edges.append(edge)
        return edges

    def _extend_label(
        self,
        base: Label,
        route: RouteData,
        trip: RouteTrip,
        segment_index: int,
        depart: int,
        arrive: int,
        config: ChallengeConfig,
    ) -> Label | None:
        from_code = route.stops[segment_index]
        to_code = route.stops[segment_index + 1]
        if (
            base.legs
            and base.legs[-1].from_code == to_code
            and base.legs[-1].to_code == from_code
        ):
            return None
        if arrive <= depart:
            return None
        distance_inc = trip.segment_distances[segment_index]
        visited: set[str] = set(base.visited)
        visited.add(to_code)
        quadrant_mask = base.quadrant_mask | self._quadrant_map.get(to_code, 0)
        ride_minutes = base.ride_minutes + max(0, arrive - depart)
        distance_km = base.distance_km + distance_inc
        legs = list(base.legs)
        prev_leg = legs[-1] if legs else None
        boarding_new_trip = (
            prev_leg is None
            or prev_leg.trip_id != trip.trip_id
            or prev_leg.line_id != route.line_id
        )
        gap = depart - prev_leg.arrive if prev_leg else None
        if boarding_new_trip and prev_leg and gap is not None:
            if gap < config.min_transfer_minutes:
                return None

        new_transfers = base.transfers
        new_min_gap = base.min_transfer_gap
        if boarding_new_trip and prev_leg:
            new_transfers += 1
            gap_value = gap if gap is not None else 10**9
            new_min_gap = min(base.min_transfer_gap, gap_value)

        if (
            legs
            and legs[-1].trip_id == trip.trip_id
            and legs[-1].line_id == route.line_id
        ):
            last = legs[-1]
            legs[-1] = JourneyLeg(
                line_id=last.line_id,
                line_name=last.line_name,
                trip_id=last.trip_id,
                from_code=last.from_code,
                to_code=to_code,
                depart=last.depart,
                arrive=arrive,
                distance_km=last.distance_km + distance_inc,
                stop_hops=last.stop_hops + 1,
            )
        else:
            legs.append(
                JourneyLeg(
                    line_id=route.line_id,
                    line_name=route.line_name,
                    trip_id=trip.trip_id,
                    from_code=from_code,
                    to_code=to_code,
                    depart=depart,
                    arrive=arrive,
                    distance_km=distance_inc,
                    stop_hops=1,
                )
            )

        stop_counts = dict(base.stop_counts)
        if not legs:
            stop_counts[from_code] = stop_counts.get(from_code, 0) + 1
        current_visits = stop_counts.get(to_code, 0)
        if to_code in self._hakata_stops:
            limit = config.hakata_max_visits or config.max_stop_visits
        else:
            limit = config.max_stop_visits
        if limit is not None and current_visits >= limit:
            return None
        if (
            config.forbid_non_hakata_duplicates
            and to_code not in self._hakata_stops
            and current_visits > 0
        ):
            return None
        stop_counts[to_code] = current_visits + 1

        line_counts = dict(base.line_counts)
        if boarding_new_trip:
            line_counts[route.line_id] = line_counts.get(route.line_id, 0) + 1
            if config.max_line_visits and line_counts[route.line_id] > config.max_line_visits:
                return None

        return Label(
            arrival=arrive,
            ride_minutes=ride_minutes,
            distance_km=distance_km,
            visited=frozenset(visited),
            quadrant_mask=quadrant_mask,
            legs=tuple(legs),
            score=0.0,
            stop_counts=tuple(sorted(stop_counts.items())),
            line_counts=tuple(sorted(line_counts.items())),
            transfers=new_transfers,
            min_transfer_gap=new_min_gap,
        )
    def _insert_label(
        self,
        bucket: list[Label],
        label: Label,
        label_metrics: dict[str, float],
        config: ChallengeConfig,
        get_metrics: Callable[[Label], dict[str, float]],
    ) -> bool:
        for existing in bucket:
            existing_metrics = get_metrics(existing)
            if config.dominance_fn(existing, existing_metrics, label, label_metrics):
                return False
        bucket[:] = [
            lbl
            for lbl in bucket
            if not config.dominance_fn(label, label_metrics, lbl, get_metrics(lbl))
        ]
        bucket.append(label)
        bucket.sort(key=lambda lbl: lbl.score, reverse=True)
        if len(bucket) > MAX_LABELS_PER_STOP:
            del bucket[MAX_LABELS_PER_STOP:]
        return True

    def _label_leg_to_plan(self, leg: JourneyLeg) -> LegPlan:
        from_station = self._stations.get(leg.from_code)
        to_station = self._stations.get(leg.to_code)
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

    def _run_raptor_challenge(self, config: ChallengeConfig) -> ChallengePlan | None:
        if not self._routes:
            return None

        rounds: list[dict[str, list[Label]]] = [
            defaultdict(list) for _ in range(config.max_rounds + 1)
        ]
        metrics_cache: dict[tuple, dict[str, float]] = {}

        def metrics_key(label: Label) -> tuple:
            return self._label_metrics_key(label)

        def get_metrics(label: Label) -> dict[str, float]:
            key = metrics_key(label)
            metrics = metrics_cache.get(key)
            if metrics is None:
                metrics = self._label_metrics(label)
                metrics_cache[key] = metrics
            return metrics

        marked_stops: set[str] = set()
        for stop_code in self._hakata_stops:
            mask = self._quadrant_map.get(stop_code, 0)
            base_label = Label(
                arrival=START_TIME_MINUTES,
                ride_minutes=0,
                distance_km=0.0,
                visited=frozenset({stop_code}),
                quadrant_mask=mask,
                legs=(),
                score=0.0,
                stop_counts=((stop_code, 1),),
                line_counts=tuple(),
                transfers=0,
                min_transfer_gap=10**9,
            )
            metrics = get_metrics(base_label)
            scored = replace(base_label, score=config.scoring_fn(base_label, metrics))
            metrics_cache[metrics_key(scored)] = metrics
            rounds[0][stop_code].append(scored)
            marked_stops.add(stop_code)

        time_limit = START_TIME_MINUTES + 24 * 60
        best_labels: list[Label] = []

        for round_idx in range(config.max_rounds):
            if not marked_stops:
                break
            next_marked: set[str] = set()
            routes_to_scan: set[str] = set()
            for stop in marked_stops:
                routes_to_scan.update(self._routes_by_stop.get(stop, ()))
            for route_id in routes_to_scan:
                route = self._routes.get(route_id)
                if not route:
                    continue
                for trip in route.trips:
                    for from_idx, stop_code in enumerate(route.stops[:-1]):
                        if stop_code not in marked_stops:
                            continue
                        labels_at_stop = rounds[round_idx].get(stop_code)
                        if not labels_at_stop:
                            continue
                        for label in labels_at_stop:
                            earliest_depart = label.arrival + config.min_transfer_minutes
                            onboard_label: Label | None = None
                            boarded = False
                            for seg_idx in range(from_idx, len(route.stops) - 1):
                                depart = trip.departures[seg_idx]
                                arrive = trip.arrivals[seg_idx + 1]
                                if not boarded and depart < earliest_depart:
                                    continue
                                base_label = onboard_label if boarded else label
                                new_label = self._extend_label(
                                    base_label,
                                    route,
                                    trip,
                                    seg_idx,
                                    depart,
                                    arrive,
                                    config,
                                )
                                if new_label is None:
                                    if boarded:
                                        break
                                    continue
                                if new_label.arrival > time_limit:
                                    break
                                metrics = get_metrics(new_label)
                                scored_label = replace(
                                    new_label,
                                    score=config.scoring_fn(new_label, metrics),
                                )
                                metrics_cache[metrics_key(scored_label)] = metrics
                                to_stop = route.stops[seg_idx + 1]
                                inserted = self._insert_label(
                                    rounds[round_idx + 1][to_stop],
                                    scored_label,
                                    metrics,
                                    config,
                                    get_metrics,
                                )
                                if inserted:
                                    next_marked.add(to_stop)
                                if (
                                    to_stop in self._hakata_stops
                                    and scored_label.arrival >= START_TIME_MINUTES + 120
                                    and (
                                        not config.require_quadrants
                                        or scored_label.quadrant_mask
                                        == ALL_QUADRANTS_MASK
                                    )
                                    and config.accept_fn(scored_label, metrics)
                                ):
                                    best_labels.append(scored_label)
                                onboard_label = scored_label
                                boarded = True
            marked_stops = next_marked

        if not best_labels:
            return None
        best_labels.sort(key=lambda lbl: lbl.score, reverse=True)
        selected = best_labels[0]
        legs = [self._label_leg_to_plan(leg) for leg in selected.legs]
        start_name = (
            self._stations[self._hakata_stops[0]].name
            if self._hakata_stops
            else "博多駅"
        )
        return ChallengePlan(
            challenge_id=config.challenge_id,
            title=config.title,
            tagline=config.tagline,
            theme_tags=config.theme_tags,
            badge=config.badge,
            legs=legs,
            start_stop_name=start_name,
            wards=derive_quadrant_labels(legs, self._quadrant_map),
        )

    def _load_segment_edges(self, segment_path: Path) -> list[TripEdge]:
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
                raise PlannerError("segments CSV の列構成が想定外です。")
            for row in reader:
                line_id = str(row.get("line_id") or "")
                if line_id not in self._eligible_lines:
                    continue
                from_code = str(row.get("from_stop") or "")
                to_code = str(row.get("to_stop") or "")
                if from_code not in self._stations or to_code not in self._stations:
                    continue
                depart = self._parse_segment_minutes(row.get("depart"))
                arrive = self._parse_segment_minutes(row.get("arrive"))
                if depart is None or arrive is None:
                    continue
                if arrive <= depart:
                    arrive += 1440
                st_a = self._stations[from_code]
                st_b = self._stations[to_code]
                trip_identifier = str(
                    row.get("trip_id")
                    or row.get("segment_id")
                    or f"{line_id}-{from_code}-{to_code}"
                )
                edges.append(
                    TripEdge(
                        line_id=line_id,
                        line_name=self._line_names.get(line_id, line_id),
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

    # ---------- challenge planners ----------

    def _config_longest_duration(self) -> ChallengeConfig:
        transfer_buffer = 5
        transfer_penalty_weight = 800

        def scoring(label: Label, metrics: dict[str, float], config: ChallengeConfig) -> float:
            stop_counts = dict(label.stop_counts)
            for stop, count in stop_counts.items():
                limit = config.max_stop_visits
                if stop in self._hakata_stops:
                    limit = config.hakata_max_visits or limit
                if limit and count > limit:
                    return -1.0

            return (
                label.ride_minutes * 10000
                + metrics["unique_lines"] * 600
                + metrics["quadrants"] * 1800
                + metrics["avg_radius"] * 160
                + metrics["boundary_ratio"] * 2200
                - metrics["center_ratio"] * 4000
                - metrics["short_leg_ratio"] * 3000
                - metrics["repeat_penalty"] * 500
                - metrics["stop_repeat_total"] * 900
                - label.transfers * transfer_penalty_weight
            )

        def dominance(
            a: Label,
            metrics_a: dict[str, float],
            b: Label,
            metrics_b: dict[str, float],
        ) -> bool:
            if (
                a.ride_minutes >= b.ride_minutes
                and metrics_a["unique_lines"] >= metrics_b["unique_lines"]
                and a.arrival <= b.arrival
            ):
                return a.score >= b.score
            return False

        def accept(_: Label, __: dict[str, float]) -> bool:
            return True

        def dominance(
            a: Label,
            metrics_a: dict[str, float],
            b: Label,
            metrics_b: dict[str, float],
        ) -> bool:
            if (
                a.ride_minutes >= b.ride_minutes
                and metrics_a["unique_lines"] >= metrics_b["unique_lines"]
                and a.arrival <= b.arrival
            ):
                return a.score >= b.score
            return False

        def accept(_: Label, __: dict[str, float]) -> bool:
            return True

        challenge_config = ChallengeConfig(
            challenge_id="longest-duration",
            title="24時間ロングライド",
            tagline="博多から出発し24時間ひたすら乗り継ぎ続ける耐久チャレンジ。",
            theme_tags=["時間最大化", "耐久"],
            badge="最長乗車",
            require_quadrants=False,
            max_rounds=min(5, MAX_TRANSFERS),
            scoring_fn=lambda l, m: scoring(l, m, challenge_config),
            dominance_fn=dominance,
            accept_fn=accept,
            min_transfer_minutes=transfer_buffer,
            transfer_penalty_minutes=transfer_buffer,
            max_stop_visits=3,  # 除博多外至多出现 3 次
            max_line_visits=2,
            hakata_max_visits=3,  # 博多站允许出现 3 次（出发/返回/中转）
            stop_repeat_penalty_weight=900,  # 重复停靠越多得分越低
        )
        return challenge_config

    def _config_most_stops(self) -> ChallengeConfig:
        transfer_buffer = 6
        transfer_penalty_weight = 1000

        def scoring(label: Label, metrics: dict[str, float]) -> float:
            return (
                metrics["unique_stops"] * 12000
                + metrics["quadrants"] * 1200
                + metrics["avg_radius"] * 180
                + label.distance_km * 40
                + metrics["boundary_ratio"] * 2500
                - metrics["center_ratio"] * 2500
                - metrics["repeat_penalty"] * 600
                - metrics["stop_repeat_total"] * 1600
                - label.transfers * transfer_penalty_weight
            )

        def dominance(
            a: Label,
            metrics_a: dict[str, float],
            b: Label,
            metrics_b: dict[str, float],
        ) -> bool:
            if (
                metrics_a["unique_stops"] >= metrics_b["unique_stops"]
                and a.arrival <= b.arrival
            ):
                return a.score >= b.score
            return False

        def accept(_: Label, __: dict[str, float]) -> bool:
            return True

        return ChallengeConfig(
            challenge_id="most-stops",
            title="ユニーク停留所コンプリート",
            tagline="24時間以内にできるだけ多くの停留所を踏破して博多へ戻るトレース。",
            theme_tags=["停留所制覇", "博多起終点"],
            badge="停留所ハンター",
            require_quadrants=False,
            max_rounds=min(5, MAX_TRANSFERS),
            scoring_fn=scoring,
            dominance_fn=dominance,
            accept_fn=accept,
            min_transfer_minutes=transfer_buffer,
            transfer_penalty_minutes=transfer_buffer,
            max_stop_visits=None,
            max_line_visits=None,
            forbid_non_hakata_duplicates=False,
            allow_hakata_revisit=True,
            hakata_max_visits=None,
            stop_repeat_penalty_weight=1600,  # 最多停一次，超过直接扣重分
        )

    def _config_city_loop(self) -> ChallengeConfig:
        transfer_buffer = 5
        transfer_penalty_weight = 900

        def scoring(label: Label, metrics: dict[str, float]) -> float:
            if metrics["quadrants"] < 4:
                return (
                    metrics["quadrants"] * 1200
                    + metrics["avg_radius"] * 80
                    + metrics["boundary_ratio"] * 1800
                    - metrics["stop_repeat_total"] * 1200
                )
            return (
                metrics["hull_area"] * 120
                + metrics["avg_radius"] * 220
                + metrics["angle_span"] * 35
                + metrics["turn_sum"] * 25
                + label.distance_km * 25
                + metrics["boundary_ratio"] * 8000
                + metrics["boundary_progress"] * 6000
                - metrics["center_ratio"] * 4500
                - metrics["repeat_penalty"] * 500
                - metrics["stop_repeat_total"] * 1500
                - label.transfers * transfer_penalty_weight
            )

        def dominance(
            a: Label,
            metrics_a: dict[str, float],
            b: Label,
            metrics_b: dict[str, float],
        ) -> bool:
            if (
                metrics_a["quadrants"] >= metrics_b["quadrants"]
                and metrics_a["boundary_ratio"] >= metrics_b["boundary_ratio"]
                and metrics_a["hull_area"] >= metrics_b["hull_area"]
                and a.arrival <= b.arrival
            ):
                return a.score >= b.score
            return False

        def accept(label: Label, metrics: dict[str, float]) -> bool:
            return (
                metrics["quadrants"] == 4
                and metrics["hull_area"] >= 25.0
                and metrics["avg_radius"] >= 3.0
                and metrics["angle_span"] >= 180.0
                and metrics["boundary_ratio"] >= 0.3
            )

        return ChallengeConfig(
            challenge_id="city-loop",
            title="福岡市一周トレース",
            tagline="市内の北東・南東・南西・北西ゾーンをすべて踏んで一筆書きで戻る。",
            theme_tags=["シティループ", "周回"],
            badge="周回達人",
            require_quadrants=True,
            max_rounds=min(6, MAX_TRANSFERS + 2),
            scoring_fn=scoring,
            dominance_fn=dominance,
            accept_fn=accept,
            min_transfer_minutes=transfer_buffer,
            transfer_penalty_minutes=transfer_buffer,
            max_stop_visits=None,
            max_line_visits=None,
            stop_repeat_penalty_weight=1400,
            hakata_max_visits=None,
        )

    def _config_longest_distance(self) -> ChallengeConfig:
        transfer_buffer = 5
        transfer_penalty_weight = 900

        def scoring(label: Label, metrics: dict[str, float]) -> float:
            return (
                label.distance_km * 12500
                + metrics["avg_radius"] * 220
                + metrics["quadrants"] * 1500
                + metrics["hull_area"] * 60
                + metrics["boundary_ratio"] * 2500
                - metrics["repeat_penalty"] * 700
                - metrics["center_ratio"] * 3200
                - metrics["stop_repeat_total"] * 900
                - label.transfers * transfer_penalty_weight
            )

        def dominance(
            a: Label,
            metrics_a: dict[str, float],
            b: Label,
            metrics_b: dict[str, float],
        ) -> bool:
            if (
                a.distance_km >= b.distance_km
                and metrics_a["avg_radius"] >= metrics_b["avg_radius"]
                and metrics_a["boundary_ratio"] >= metrics_b["boundary_ratio"]
                and a.arrival <= b.arrival
            ):
                return a.score >= b.score
            return False

        def accept(_: Label, metrics: dict[str, float]) -> bool:
            return True

        return ChallengeConfig(
            challenge_id="longest-distance",
            title="距離最長ツアー",
            tagline="24時間で博多を起終点に最長距離を駆け抜けるロングトリップ。",
            theme_tags=["距離最大化", "耐久"],
            badge="最長距離",
            require_quadrants=False,
            max_rounds=min(6, MAX_TRANSFERS + 2),
            scoring_fn=scoring,
            dominance_fn=dominance,
            accept_fn=accept,
            min_transfer_minutes=transfer_buffer,
            transfer_penalty_minutes=transfer_buffer,
            max_stop_visits=4,
            max_line_visits=None,
            hakata_max_visits=None,
            stop_repeat_penalty_weight=900,
        )

    def _plan_longest_duration(self) -> ChallengePlan:
        plan = self._run_raptor_challenge(self._config_longest_duration())
        if plan:
            return plan
        return self._plan_longest_duration_beam()

    def _plan_most_unique_stops(self) -> ChallengePlan:
        plan = self._run_raptor_challenge(self._config_most_stops())
        if plan:
            return plan
        return self._plan_most_unique_stops_beam()

    def _plan_city_loop(self) -> ChallengePlan:
        plan = self._run_raptor_challenge(self._config_city_loop())
        if plan:
            return plan
        return self._plan_city_loop_beam()

    def _plan_longest_distance(self) -> ChallengePlan:
        plan = self._run_raptor_challenge(self._config_longest_distance())
        if plan:
            return plan
        # フォールバックとして最長乗車の結果を再利用（距離優先ではないが空欄防止）
        fallback = self._plan_longest_duration_beam()
        return ChallengePlan(
            challenge_id="longest-distance",
            title="距離最長ツアー",
            tagline="24時間で博多を起終点に最長距離を駆け抜けるロングトリップ。",
            theme_tags=["距離最大化", "耐久"],
            badge="最長距離",
            legs=list(fallback.legs),
            start_stop_name=fallback.start_stop_name,
            wards=fallback.wards,
        )

    def _label_metrics_key(self, label: Label) -> tuple:
        legs_key = tuple(
            (
                leg.line_id,
                leg.trip_id,
                leg.from_code,
                leg.to_code,
                leg.depart,
                leg.arrive,
            )
            for leg in label.legs
        )
        return (
            label.arrival,
            label.ride_minutes,
            round(label.distance_km, 6),
            label.visited,
            label.quadrant_mask,
            legs_key,
        )

    def _distance_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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

    def _project_to_plane(self, lat: float, lon: float) -> tuple[float, float]:
        base_lat, base_lon = self._hakata_coord
        lat_diff = lat - base_lat
        lon_diff = lon - base_lon
        cos_lat = math.cos(math.radians(base_lat))
        x = lon_diff * cos_lat * 111.320  # km
        y = lat_diff * 110.574  # km
        return x, y

    def _convex_hull(
        self, points: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        unique_points = sorted(set(points))
        if len(unique_points) <= 1:
            return unique_points

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        lower: list[tuple[float, float]] = []
        for p in unique_points:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        upper: list[tuple[float, float]] = []
        for p in reversed(unique_points):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        return lower[:-1] + upper[:-1]

    def _polygon_area(self, coords: list[tuple[float, float]]) -> float:
        points = [
            self._project_to_plane(lat, lon) for lat, lon in coords if lat and lon
        ]
        hull = self._convex_hull(points)
        if len(hull) < 3:
            return 0.0
        area = 0.0
        for i in range(len(hull)):
            x1, y1 = hull[i]
            x2, y2 = hull[(i + 1) % len(hull)]
            area += x1 * y2 - x2 * y1
        return abs(area) / 2.0

    def _angle_metrics(self, coords: list[tuple[float, float]]) -> tuple[float, float]:
        if len(coords) < 2:
            return 0.0, 0.0
        angles: list[float] = []
        for lat, lon in coords:
            x, y = self._project_to_plane(lat, lon)
            if x == 0.0 and y == 0.0:
                continue
            angle = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
            angles.append(angle)
        if len(angles) < 2:
            return 0.0, 0.0
        total_turn = 0.0
        for prev, nxt in zip(angles, angles[1:], strict=False):
            diff = (nxt - prev + 180.0) % 360.0 - 180.0
            total_turn += abs(diff)
        sorted_angles = sorted(angles)
        max_gap = 0.0
        for i in range(len(sorted_angles) - 1):
            gap = sorted_angles[i + 1] - sorted_angles[i]
            if gap > max_gap:
                max_gap = gap
        wrap_gap = sorted_angles[0] + 360.0 - sorted_angles[-1]
        if wrap_gap > max_gap:
            max_gap = wrap_gap
        span = 360.0 - max_gap
        return span, total_turn

    def _count_stop_visits_from_legs(
        self, legs: Sequence[JourneyLeg]
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        for leg in legs:
            counts[leg.from_code] += 1
            counts[leg.to_code] += 1
        return counts

    def _label_metrics(self, label: Label) -> dict[str, float]:
        unique_lines = len({leg.line_id for leg in label.legs})
        unique_stops = len(label.visited)
        quadrants = bin(label.quadrant_mask).count("1")
        stop_counts_map = dict(label.stop_counts)
        stop_repeat_total = sum(max(0, cnt - 1) for cnt in stop_counts_map.values())
        stop_repeat_max = max(stop_counts_map.values()) if stop_counts_map else 0

        visited_coords: list[tuple[float, float]] = []
        distances: list[float] = []
        for code in label.visited:
            station = self._stations.get(code)
            if not station:
                continue
            visited_coords.append((station.lat, station.lon))
            distances.append(
                self._distance_km(station.lat, station.lon, *self._hakata_coord)
            )

        avg_radius = sum(distances) / len(distances) if distances else 0.0
        max_radius = max(distances) if distances else 0.0
        center_visits = sum(1 for d in distances if d < self._inner_radius_km)
        center_ratio = (center_visits / len(distances)) if distances else 0.0

        path_coords: list[tuple[float, float]] = []
        if label.legs:
            first_leg = label.legs[0]
            start_station = self._stations.get(first_leg.from_code)
            if start_station:
                path_coords.append((start_station.lat, start_station.lon))
            for leg in label.legs:
                station = self._stations.get(leg.to_code)
                if station:
                    path_coords.append((station.lat, station.lon))
        else:
            path_coords.extend(visited_coords)

        hull_area = self._polygon_area(path_coords)
        angle_span, turn_sum = self._angle_metrics(path_coords)

        repeat_penalty = max(0, len(label.legs) - unique_lines)
        short_leg_count = sum(1 for leg in label.legs if leg.distance_km < 0.5)
        short_leg_ratio = (short_leg_count / len(label.legs)) if label.legs else 0.0
        boundary_hits = 0
        boundary_ratio = 0.0
        boundary_progress = 0.0
        boundary_set = set(self._boundary_sequence)
        if boundary_set:
            boundary_hits = sum(1 for stop in label.visited if stop in boundary_set)
            boundary_ratio = boundary_hits / max(1, len(boundary_set))
            sequence_indices: list[int] = []
            seen_boundary: set[str] = set()
            for leg in label.legs:
                for code in (leg.from_code, leg.to_code):
                    if code in boundary_set and code not in seen_boundary:
                        seen_boundary.add(code)
                        idx = self._boundary_index.get(code)
                        if idx is not None:
                            sequence_indices.append(idx)
            if sequence_indices:
                sequence_indices.sort()
                coverage = sequence_indices[-1] - sequence_indices[0]
                total = max(1, len(self._boundary_sequence))
                boundary_progress = min(1.0, coverage / total)

        return {
            "unique_lines": float(unique_lines),
            "unique_stops": float(unique_stops),
            "quadrants": float(quadrants),
            "avg_radius": avg_radius,
            "max_radius": max_radius,
            "center_ratio": center_ratio,
            "hull_area": hull_area,
            "angle_span": angle_span,
            "turn_sum": turn_sum,
            "repeat_penalty": float(repeat_penalty),
            "short_leg_ratio": short_leg_ratio,
            "boundary_hits": float(boundary_hits),
            "boundary_ratio": boundary_ratio,
            "boundary_progress": boundary_progress,
            "stop_repeat_total": float(stop_repeat_total),
            "stop_repeat_max": float(stop_repeat_max),
        }

    def _compute_challenges(self) -> dict[str, ChallengePlan]:
        longest = self._plan_longest_duration()
        most_stops = self._plan_most_unique_stops()
        city_loop = self._plan_city_loop()
        longest_distance = self._plan_longest_distance()
        plans = {
            "longest-duration": longest,
            "most-stops": most_stops,
            "city-loop": city_loop,
            "longest-distance": longest_distance,
        }
        return plans

    def _plan_longest_duration_beam(self) -> ChallengePlan:
        result = self._run_search(
            score_key="ride",
            require_unique=False,
            require_quadrants=False,
            max_queue=2500,
            max_expansions=150000,
            max_stop_visits=None,
            max_line_visits=None,
            min_transfer_minutes=5,
            transfer_penalty_minutes=5,
            hakata_max_visits=3,
            stop_repeat_penalty_weight=900,
        )
        if result is None:
            raise PlannerError("最長乗車ルートの探索に失敗しました。")
        legs = collapse_edges(result.path)
        return ChallengePlan(
            challenge_id="longest-duration",
            title="24時間ロングライド",
            tagline="博多から出発し24時間ひたすら乗り継ぎ続ける耐久チャレンジ。",
            theme_tags=["時間最大化", "耐久"],
            badge="最長乗車",
            legs=legs,
            start_stop_name=self._stations[self._hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, self._quadrant_map),
        )

    def _plan_most_unique_stops_beam(self) -> ChallengePlan:
        result = self._run_search(
            score_key="unique",
            require_unique=True,
            require_quadrants=False,
            max_queue=3200,
            max_expansions=180000,
            max_branch=10,
            max_stop_visits=None,
            max_line_visits=None,
            min_transfer_minutes=6,
            transfer_penalty_minutes=6,
            hakata_max_visits=2,
            stop_repeat_penalty_weight=1600,
        )
        if result is None:
            raise PlannerError("最多停留所ルートの探索に失敗しました。")
        legs = collapse_edges(result.path)
        return ChallengePlan(
            challenge_id="most-stops",
            title="ユニーク停留所コンプリート",
            tagline="24時間以内にできるだけ多くの停留所を踏破して博多へ戻るトレース。",
            theme_tags=["停留所制覇", "博多起終点"],
            badge="停留所ハンター",
            legs=legs,
            start_stop_name=self._stations[self._hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, self._quadrant_map),
        )

    def _plan_city_loop_beam(self) -> ChallengePlan:
        result = self._run_search(
            score_key="loop",
            require_unique=False,
            require_quadrants=True,
            max_queue=3500,
            max_expansions=220000,
            max_branch=12,
            max_stop_visits=None,
            max_line_visits=None,
            min_transfer_minutes=5,
            transfer_penalty_minutes=5,
            hakata_max_visits=2,
            stop_repeat_penalty_weight=1400,
        )
        if result is None:
            # second attempt with relaxed branching penalty
            result = self._run_search(
                score_key="loop",
                require_unique=False,
                require_quadrants=True,
                max_queue=4500,
                max_expansions=260000,
                max_branch=16,
                max_stop_visits=None,
                max_line_visits=None,
                min_transfer_minutes=5,
                transfer_penalty_minutes=5,
                hakata_max_visits=2,
                stop_repeat_penalty_weight=1400,
            )
        if result is None:
            fallback = self._run_search(
                score_key="loop",
                require_unique=False,
                require_quadrants=False,
                max_queue=5200,
                max_expansions=320000,
                max_branch=18,
                max_stop_visits=None,
                max_line_visits=None,
                min_transfer_minutes=5,
                transfer_penalty_minutes=5,
                hakata_max_visits=2,
                stop_repeat_penalty_weight=1400,
            )
            if fallback:
                result = fallback
        if result is None:
            raise PlannerError("市内ループルートの探索に失敗しました。")
        legs = collapse_edges(result.path)
        return ChallengePlan(
            challenge_id="city-loop",
            title="福岡市一周トレース",
            tagline="市内の北東・南東・南西・北西ゾーンをすべて踏んで一筆書きで戻る。",
            theme_tags=["シティループ", "周回"],
            badge="周回達人",
            legs=legs,
            start_stop_name=self._stations[self._hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, self._quadrant_map),
        )

    # ---------- search ----------

    def _run_search(
        self,
        *,
        score_key: str,
        require_unique: bool,
        require_quadrants: bool,
        max_queue: int | None = None,
        max_expansions: int | None = None,
        max_branch: int | None = None,
        max_stop_visits: int | None = None,
        max_line_visits: int | None = None,
        min_transfer_minutes: int = TRANSFER_BUFFER_MINUTES,
        transfer_penalty_minutes: int = 0,
        stop_repeat_penalty_weight: int = 0,
        hakata_max_visits: int | None = None,
    ) -> SearchState | None:
        if not self._stop_schedules:
            raise PlannerError("時刻表がロードされていません。")
        time_limit = START_TIME_MINUTES + 24 * 60
        pq: list[tuple[float, int, SearchState]] = []
        counter = 0
        queue_limit = max_queue or MAX_QUEUE_SIZE
        expansion_limit = max_expansions or MAX_EXPANSIONS
        branch_limit = max_branch or MAX_BRANCH_PER_EXPANSION
        stop_limit = max_stop_visits if max_stop_visits and max_stop_visits > 0 else None
        line_limit = max_line_visits if max_line_visits and max_line_visits > 0 else None

        def push(state: SearchState, priority: float) -> None:
            nonlocal counter
            counter += 1
            if len(pq) >= queue_limit:
                heapq.heappushpop(pq, (priority, counter, state))
            else:
                heapq.heappush(pq, (priority, counter, state))

        best_key_score: dict[tuple[str, int], float] = {}
        results: list[SearchState] = []

        for stop_code in self._hakata_stops:
            mask = self._quadrant_map.get(stop_code, 0)
            initial_unique = 1 if require_unique else 0
            state = SearchState(
                priority=0.0,
                ride_minutes=0,
                current_time=START_TIME_MINUTES,
                stop_code=stop_code,
                path=(),
                unique_count=initial_unique,
                quadrant_mask=mask,
                stop_visit_counts={stop_code: 1},
                line_visit_counts={},
                transfers=0,
            )
            push(state, 0.0)

        expansions = 0
        while pq and expansions < expansion_limit:
            priority, _, state = heapq.heappop(pq)
            expansions += 1
            # completion check
            if (
                state.path
                and state.stop_code in self._hakata_stops
                and state.current_time >= START_TIME_MINUTES + 120
            ):
                if require_quadrants and state.quadrant_mask != 15:
                    pass
                else:
                    results.append(state)
                    if score_key == "loop" and state.quadrant_mask == 15:
                        break

            next_edges = self._next_edges(
                state.stop_code, state.current_time + min_transfer_minutes
            )
            if not next_edges:
                continue
            branch_count = 0
            for edge in next_edges:
                if edge.arrive > time_limit:
                    continue
                branch_count += 1
                if branch_count > branch_limit:
                    break

                if require_unique and edge.to_code in state.stop_visit_counts:
                    if not (edge.to_code in self._hakata_stops and state.path):
                        continue

                if stop_limit:
                    limit = stop_limit
                    if edge.to_code in self._hakata_stops and hakata_max_visits:
                        limit = hakata_max_visits
                    if state.stop_visit_counts.get(edge.to_code, 0) >= limit:
                        continue

                new_path = state.path + (edge,)
                new_time = edge.arrive
                new_ride = state.ride_minutes + edge.ride_minutes
                new_mask = state.quadrant_mask | self._quadrant_map.get(edge.to_code, 0)

                current_stop_visits = state.stop_visit_counts.get(edge.to_code, 0)
                new_stop_counts = dict(state.stop_visit_counts)
                new_stop_counts[edge.to_code] = current_stop_visits + 1

                prev_edge = state.path[-1] if state.path else None
                boarding_new_trip = prev_edge is None or edge.trip_id != prev_edge.trip_id
                is_transfer = boarding_new_trip and prev_edge is not None

                if line_limit and boarding_new_trip:
                    if state.line_visit_counts.get(edge.line_id, 0) >= line_limit:
                        continue

                if boarding_new_trip:
                    new_line_counts = dict(state.line_visit_counts)
                    new_line_counts[edge.line_id] = (
                        new_line_counts.get(edge.line_id, 0) + 1
                    )
                else:
                    new_line_counts = state.line_visit_counts

                new_unique = (
                    state.unique_count + 1 if require_unique else state.unique_count
                )

                if (
                    require_quadrants
                    and new_mask == state.quadrant_mask
                    and not state.path
                ):
                    # encourage exploring outward first
                    continue

                next_state = SearchState(
                    priority=0.0,
                    ride_minutes=new_ride,
                    current_time=new_time,
                    stop_code=edge.to_code,
                    path=new_path,
                    unique_count=new_unique,
                    quadrant_mask=new_mask,
                    stop_visit_counts=new_stop_counts,
                    line_visit_counts=new_line_counts,
                    transfers=state.transfers + (1 if is_transfer else 0),
                )
                score = self._score_state(
                    next_state,
                    score_key,
                    transfer_penalty_minutes,
                    stop_repeat_penalty_weight,
                )
                key = (edge.to_code, new_time // 30)
                if score <= best_key_score.get(key, -1):
                    continue
                best_key_score[key] = score
                push(next_state, -score)

        if not results:
            return None
        scores = [
            (
                self._score_state(
                    state, score_key, transfer_penalty_minutes, stop_repeat_penalty_weight
                ),
                state,
            )
            for state in results
        ]
        scores.sort(key=lambda tup: tup[0], reverse=True)
        return scores[0][1]

    def _next_edges(self, stop_code: str, earliest_depart: int) -> list[TripEdge]:
        schedule = self._stop_schedules.get(stop_code)
        if not schedule or not schedule.departures:
            return []
        idx = bisect_left(schedule.departures, earliest_depart)
        return schedule.edges[idx:]

    def _score_state(
        self,
        state: SearchState,
        key: str,
        transfer_penalty_minutes: int = 0,
        stop_repeat_penalty_weight: int = 0,
    ) -> float:
        line_ids = [edge.line_id for edge in state.path]
        unique_lines = len(set(line_ids))
        repeat_penalty = max(0, len(line_ids) - unique_lines)
        transfer_penalty_total = state.transfers * transfer_penalty_minutes
        stop_repeat = sum(max(0, count - 1) for count in state.stop_visit_counts.values())
        stop_repeat_penalty = stop_repeat * stop_repeat_penalty_weight

        if key == "loop":
            quadrants = bin(state.quadrant_mask).count("1")
            diversity_bonus = unique_lines * 15
            repeat_penalty_value = repeat_penalty * 4
            return (
                quadrants * 2000
                + float(state.ride_minutes)
                + diversity_bonus
                - repeat_penalty_value
                - transfer_penalty_total
                - stop_repeat_penalty
            )

        if key == "unique":
            diversity_bonus = unique_lines * 12
            repeat_penalty_value = repeat_penalty * 6
            return (
                state.unique_count * 1200
                + float(state.ride_minutes)
                + diversity_bonus
                - repeat_penalty_value
                - transfer_penalty_total
                - stop_repeat_penalty
            )

        diversity_bonus = unique_lines * 10
        repeat_penalty_value = repeat_penalty * 8
        return (
            float(state.ride_minutes)
            + diversity_bonus
            - repeat_penalty_value
            - transfer_penalty_total
            - stop_repeat_penalty
        )

    def _parse_segment_minutes(self, raw: str | None) -> int | None:
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


def parse_datetime(raw: str, base_dt: datetime) -> datetime | None:
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


def collapse_edges(edges: Sequence[TripEdge]) -> list[LegPlan]:
    if not edges:
        return []
    legs: list[LegPlan] = []
    buffer = [edges[0]]
    for edge in edges[1:]:
        last = buffer[-1]
        if edge.trip_id == last.trip_id and edge.line_id == last.line_id:
            buffer.append(edge)
        else:
            legs.append(_compress_buffer(buffer))
            buffer = [edge]
    if buffer:
        legs.append(_compress_buffer(buffer))
    return legs


def _compress_buffer(buffer: Sequence[TripEdge]) -> LegPlan:
    first = buffer[0]
    last = buffer[-1]
    distance = sum(edge.distance_km for edge in buffer)
    ride_minutes = last.arrive - first.depart
    path: list[tuple[float, float]] = []
    for idx, edge in enumerate(buffer):
        if idx == 0:
            path.append((edge.from_lat, edge.from_lon))
        path.append((edge.to_lat, edge.to_lon))
    return LegPlan(
        line_id=first.line_id,
        line_name=first.line_name,
        trip_id=first.trip_id,
        from_code=first.from_code,
        from_name=first.from_name,
        to_code=last.to_code,
        to_name=last.to_name,
        depart=first.depart,
        arrive=last.arrive,
        ride_minutes=ride_minutes,
        distance_km=distance,
        stop_hops=len(buffer),
        path=path,
        from_lat=first.from_lat,
        from_lon=first.from_lon,
        to_lat=last.to_lat,
        to_lon=last.to_lon,
    )


def derive_quadrant_labels(
    legs: Sequence[LegPlan], quadrant_map: dict[str, int]
) -> list[str]:
    labels = {1: "北東", 2: "南東", 4: "南西", 8: "北西"}
    visited = Counter()
    for leg in legs:
        visited.update([quadrant_map.get(leg.from_code, 0)])
        visited.update([quadrant_map.get(leg.to_code, 0)])
    out = []
    for bit, label in labels.items():
        if visited.get(bit):
            out.append(f"福岡市{label}エリア")
    return out
