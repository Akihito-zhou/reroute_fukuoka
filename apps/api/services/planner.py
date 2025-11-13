from __future__ import annotations

import heapq
import logging
import os
import threading
import time
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import planner_loader
from .planner_constants import (
    DATA_DIR,
    DEFAULT_REALTIME_CACHE_SECONDS,
    MAX_BRANCH_PER_EXPANSION,
    MAX_EXPANSIONS,
    MAX_QUEUE_SIZE,
    MAX_ROUTES_FOR_RAPTOR,
    MAX_TRIPS_PER_ROUTE,
    START_TIME_MINUTES,
    TRANSFER_BUFFER_MINUTES,
)
from .planner_models import (
    ChallengePlan,
    JourneyLeg,
    RouteData,
    RouteTrip,
    SearchState,
    Station,
    StopSchedule,
    TripEdge,
)
from .planner_utils import collapse_edges, derive_quadrant_labels
from .planners import city_loop, longest_distance, longest_duration, most_stops

try:  # pragma: no cover - allow running as either package or module
    from ..clients.ekispert_bus import EkispertBusClient
except ImportError:  # pragma: no cover
    from clients.ekispert_bus import EkispertBusClient  # type: ignore

try:  # pragma: no cover - allow running as either package or module
    from .realtime_timetable import RealtimeTimetableManager
except ImportError:  # pragma: no cover
    from realtime_timetable import RealtimeTimetableManager  # type: ignore


logger = logging.getLogger(__name__)


class PlannerError(RuntimeError):
    """Raised when the planner cannot compute challenges."""


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
        self.stations: dict[str, Station] = {}
        self.line_names: dict[str, str] = {}
        self.eligible_lines: set[str] = set()
        self.stop_schedules: dict[str, StopSchedule] = {}
        self.hakata_stops: list[str] = []
        self.quadrant_map: dict[str, int] = {}
        self.line_stop_edges: dict[str, list[str]] = {}
        self._cache: dict[str, ChallengePlan] | None = None
        self._cache_mtime: float = 0.0
        self._lock = threading.Lock()
        self._latest_data_file: Path | None = None
        self.static_edges: list[TripEdge] = []
        self.routes: dict[str, RouteData] = {}
        self.routes_by_stop: dict[str, set[str]] = defaultdict(set)
        self.hakata_coord: tuple[float, float] = (33.589, 130.420)
        self.inner_radius_km: float = 2.0
        self.city_boundary: list[list[tuple[float, float]]] = []
        self.boundary_sequence: list[str] = []
        self.boundary_index: dict[str, int] = {}

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

    @staticmethod
    def _normalize_challenge_id(challenge_id: str) -> str:
        """Normalize challenge IDs to the kebab-case form used by the API."""
        return challenge_id.strip().lower().replace("_", "-")

    def list_challenges(self) -> list[dict]:
        plans = self._ensure_plans()
        return [plan.to_dict() for plan in plans.values() if plan]

    def get_challenge(self, challenge_id: str) -> dict:
        normalized_id = self._normalize_challenge_id(challenge_id)
        plans = self._ensure_plans()
        if normalized_id not in plans or not plans[normalized_id]:
            raise PlannerError(f"challenge '{challenge_id}' not available")
        return plans[normalized_id].to_dict()

    # ---------- bootstrap ----------

    def _ensure_plans(self) -> dict[str, ChallengePlan | None]:
        with self._lock:
            latest = self._call_loader(planner_loader.find_latest_data_file, self)
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

    def _call_loader(self, func: Callable, *args, **kwargs):
        """Invokes a loader function, wrapping exceptions in PlannerError."""
        try:
            return func(*args, **kwargs)
        except RuntimeError as exc:
            raise PlannerError(str(exc)) from exc

    def _load_static_assets(self) -> None:
        """Loads static assets like station and line data."""
        self._call_loader(planner_loader.load_static_assets, self)
        
        # Load Fukuoka city boundary and filter stations
        import json
        from .planner_utils import is_in_fukuoka
        
        self.fukuoka_polygons = []
        geojson_path = self.data_dir / "fukuoka_city.geojson"
        if geojson_path.exists():
            with geojson_path.open("r", encoding="utf-8") as f:
                geojson_data = json.load(f)
                for feature in geojson_data.get("features", []):
                    geom = feature.get("geometry", {})
                    if geom.get("type") == "Polygon":
                        # GeoJSON format is [lon, lat]
                        self.fukuoka_polygons.append(geom["coordinates"][0])
                    elif geom.get("type") == "MultiPolygon":
                        for polygon in geom["coordinates"]:
                            self.fukuoka_polygons.append(polygon[0])

        self.fukuoka_station_codes = set()
        if self.fukuoka_polygons:
            for station in self.stations.values():
                if is_in_fukuoka(station.lat, station.lon, self.fukuoka_polygons):
                    self.fukuoka_station_codes.add(station.code)
        else:
            # If no boundary file, assume all stations are valid
            self.fukuoka_station_codes = set(self.stations.keys())

    def _load_edges(self, data_path: Path | None) -> None:
        """Loads trip edge data and initializes schedules."""
        self._call_loader(planner_loader.load_edges, self, data_path)
        if not self.stop_schedules:
            raise PlannerError("Failed to find a route for the longest ride.")

    def _refresh_stop_schedules(self, *, force_refresh: bool = False) -> None:
        """Refreshes stop schedules from either realtime or static data."""
        horizon_start = START_TIME_MINUTES
        horizon_end = START_TIME_MINUTES + 24 * 60
        edges: list[TripEdge] = []
        if self._timetable_manager:
            edges = self._timetable_manager.get_edges_for_window(
                horizon_start,
                horizon_end,
                line_filter=self.eligible_lines,
                force_refresh=force_refresh,
            )
        if not edges:
            edges = [
                edge
                for edge in self.static_edges
                if edge.arrive >= horizon_start and edge.depart <= horizon_end
            ]
        if not edges:
            logger.warning(
                "No timetable edges available between %s and %s minutes.",
                horizon_start,
                horizon_end,
            )
            self.stop_schedules = {}
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
        self.stop_schedules = schedules
        self._build_route_timetables()

    def _build_route_timetables(self) -> None:
        """Constructs route-based timetables from trip edges."""
        routes: dict[str, RouteData] = {}
        routes_by_stop: dict[str, set[str]] = defaultdict(set)
        trip_groups: dict[str, dict[str, list[TripEdge]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for edge in self.static_edges:
            if edge.line_id not in self.eligible_lines:
                continue
            route_key = f"{edge.line_id}:{edge.direction}"
            trip_groups[route_key][edge.trip_id].append(edge)

        for _route_idx, (route_key, trips) in enumerate(trip_groups.items()):
            if not trips or len(routes) >= MAX_ROUTES_FOR_RAPTOR:
                continue
            
            sample_edges = next(iter(trips.values()), None)
            if not sample_edges: continue

            any_edge = sample_edges[0]
            base_stops = self.line_stop_edges.get(any_edge.line_id, [])
            if not base_stops:
                continue

            base_sequence = list(reversed(base_stops)) if any_edge.direction.lower() in {"down", "outbound", "reverse"} else list(base_stops)
            if len(base_sequence) < 2:
                continue

            pair_set = {(e.from_code, e.to_code) for es in trips.values() for e in es}
            stops_seq: list[str] = []
            for idx in range(len(base_sequence) - 1):
                stops_seq.append(base_sequence[idx])
                if (base_sequence[idx], base_sequence[idx + 1]) not in pair_set:
                    break
            else:
                stops_seq.append(base_sequence[-1])

            if len(stops_seq) < 2:
                continue

            for edge_list in trips.values():
                edge_list.sort(key=lambda e: e.depart)
            
            stop_to_index = {code: idx for idx, code in enumerate(stops_seq)}
            route_trips = self._create_route_trips(trips, stops_seq, stop_to_index)

            if not route_trips:
                continue

            line_name = self.line_names.get(any_edge.line_id, any_edge.line_id)
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

        self.routes = routes
        self.routes_by_stop = {stop: set(ids) for stop, ids in routes_by_stop.items()}
        planner_loader.build_boundary_sequence(self)

    def _create_route_trips(self, trips: dict[str, list[TripEdge]], stops_seq: list[str], stop_to_index: dict[str, int]) -> list[RouteTrip]:
        route_trips = []
        for trip_id, edge_list in trips.items():
            departures: list[int | None] = [None] * len(stops_seq)
            arrivals: list[int | None] = [None] * len(stops_seq)
            segment_distances: list[float] = [0.0] * (len(stops_seq) - 1)
            
            for edge in edge_list:
                from_idx = stop_to_index.get(edge.from_code)
                to_idx = stop_to_index.get(edge.to_code)
                if from_idx is not None and to_idx is not None and to_idx == from_idx + 1:
                    departures[from_idx] = edge.depart
                    arrivals[to_idx] = edge.arrive
                    segment_distances[from_idx] = edge.distance_km

            # A very simplified validation
            if all(d is not None for d in departures[:-1]) and all(a is not None for a in arrivals[1:]):
                final_departures = [d for d in departures]
                final_arrivals = [a for a in arrivals]
                if final_departures[0] is None and final_arrivals[0] is not None:
                    final_departures[0] = final_arrivals[0]
                if final_arrivals[0] is None and final_departures[0] is not None:
                    final_arrivals[0] = final_departures[0]
                if final_departures[-1] is None and final_arrivals[-1] is not None:
                    final_departures[-1] = final_arrivals[-1]
                
                if all(d is not None for d in final_departures) and all(a is not None for a in final_arrivals):
                    route_trips.append(
                        RouteTrip(
                            trip_id=trip_id,
                            departures=final_departures,
                            arrivals=final_arrivals,
                            segment_distances=segment_distances,
                        )
                    )
        return route_trips

    # ---------- challenge planners ----------

    def _compute_challenges(self) -> dict[str, ChallengePlan | None]:
        """Computes all challenges in parallel by delegating to the specific planner modules."""
        planners = {
            "longest-duration": longest_duration.plan,
            "most-stops": most_stops.plan,
            "city-loop": city_loop.plan,
            "longest-distance": longest_distance.plan,
        }
        
        plans: dict[str, ChallengePlan | None] = {}
        with ThreadPoolExecutor(max_workers=len(planners)) as executor:
            future_to_challenge = {
                executor.submit(planner_func, self): challenge_id
                for challenge_id, planner_func in planners.items()
            }
            for future in future_to_challenge:
                challenge_id = future_to_challenge[future]
                normalized_id = self._normalize_challenge_id(challenge_id)
                try:
                    plan = future.result()
                    if plan:
                        plan.challenge_id = self._normalize_challenge_id(
                            plan.challenge_id
                        )
                    plans[normalized_id] = plan
                except Exception:
                    logger.exception(f"Error computing challenge '{challenge_id}'")
                    plans[normalized_id] = None
        return plans



    def run_beam_search(
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
        if not self.stop_schedules:
            raise PlannerError("Timetables are not loaded.")
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

        for stop_code in self.hakata_stops:
            mask = self.quadrant_map.get(stop_code, 0)
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
            _priority, _, state = heapq.heappop(pq)
            expansions += 1
            
            if (
                state.path
                and state.stop_code in self.hakata_stops
                and state.current_time >= START_TIME_MINUTES + 120
            ):
                if not require_quadrants or state.quadrant_mask == 15:
                    results.append(state)
                    if score_key == "loop" and state.quadrant_mask == 15:
                        break

            next_edges = self._next_edges(
                state.stop_code, state.current_time + min_transfer_minutes
            )
            if not next_edges:
                continue

            for i, edge in enumerate(next_edges):
                if i >= branch_limit: break
                if edge.arrive > time_limit: continue

                if require_unique and edge.to_code in state.stop_visit_counts and not (edge.to_code in self.hakata_stops and state.path):
                    continue

                if stop_limit:
                    limit = hakata_max_visits if edge.to_code in self.hakata_stops and hakata_max_visits else stop_limit
                    if state.stop_visit_counts.get(edge.to_code, 0) >= limit:
                        continue
                
                new_stop_counts = dict(state.stop_visit_counts)
                new_stop_counts[edge.to_code] = new_stop_counts.get(edge.to_code, 0) + 1

                prev_edge = state.path[-1] if state.path else None
                is_new_trip = prev_edge is None or edge.trip_id != prev_edge.trip_id
                
                if line_limit and is_new_trip and state.line_visit_counts.get(edge.line_id, 0) >= line_limit:
                    continue

                new_line_counts = dict(state.line_visit_counts)
                if is_new_trip:
                    new_line_counts[edge.line_id] = new_line_counts.get(edge.line_id, 0) + 1

                next_state = SearchState(
                    priority=0.0,
                    ride_minutes=state.ride_minutes + edge.ride_minutes,
                    current_time=edge.arrive,
                    stop_code=edge.to_code,
                    path=state.path + (edge,),
                    unique_count=state.unique_count + (1 if require_unique and edge.to_code not in state.stop_visit_counts else 0),
                    quadrant_mask=state.quadrant_mask | self.quadrant_map.get(edge.to_code, 0),
                    stop_visit_counts=new_stop_counts,
                    line_visit_counts=new_line_counts,
                    transfers=state.transfers + (1 if is_new_trip and prev_edge is not None else 0),
                )
                score = self._score_state(
                    next_state,
                    score_key,
                    transfer_penalty_minutes,
                    stop_repeat_penalty_weight,
                )
                key = (edge.to_code, next_state.current_time // 30)
                if score > best_key_score.get(key, -1):
                    best_key_score[key] = score
                    push(next_state, -score)

        if not results:
            return None
        
        scores = [
            (self._score_state(s, score_key, transfer_penalty_minutes, stop_repeat_penalty_weight), s)
            for s in results
        ]
        scores.sort(key=lambda t: t[0], reverse=True)
        return scores[0][1]

    def _next_edges(self, stop_code: str, earliest_depart: int) -> list[TripEdge]:
        schedule = self.stop_schedules.get(stop_code)
        if not schedule or not schedule.departures:
            return []
        idx = bisect_left(schedule.departures, earliest_depart)
        return schedule.edges[idx:]

    def run_simple_raptor(
        self,
        origin: str,
        destination: str,
        depart_after: int,
    ) -> tuple[int, list[JourneyLeg]] | None:
        if not self.stop_schedules:
            return None
        if origin not in self.stop_schedules or destination not in self.stop_schedules:
            return None
        time_limit = START_TIME_MINUTES + 24 * 60
        earliest: dict[str, int] = {origin: depart_after}
        queue: list[tuple[int, str, tuple[JourneyLeg, ...]]] = []
        heapq.heappush(queue, (depart_after, origin, tuple()))

        while queue:
            current_time, stop_code, path = heapq.heappop(queue)
            known = earliest.get(stop_code, float("inf"))
            if current_time > known:
                continue
            if stop_code == destination and path:
                return current_time, list(path)
            if current_time >= time_limit:
                continue
            ready_time = current_time if not path else current_time + TRANSFER_BUFFER_MINUTES
            edges = self._next_edges(stop_code, ready_time)
            if not edges:
                continue
            
            for i, edge in enumerate(edges):
                if i >= 30: break
                if edge.depart < ready_time: continue
                if edge.arrive > time_limit: break
                
                leg = JourneyLeg(
                    line_id=edge.line_id,
                    line_name=edge.line_name,
                    trip_id=edge.trip_id,
                    from_code=edge.from_code,
                    to_code=edge.to_code,
                    depart=edge.depart,
                    arrive=edge.arrive,
                    distance_km=edge.distance_km,
                    stop_hops=1,
                )
                new_time = edge.arrive
                prev_best = earliest.get(edge.to_code)
                if prev_best is None or new_time < prev_best:
                    earliest[edge.to_code] = new_time
                    heapq.heappush(queue, (new_time, edge.to_code, path + (leg,)))
        return None

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

        base_score = 0.0
        if key == "loop":
            quadrants = bin(state.quadrant_mask).count("1")
            base_score = quadrants * 2000 + float(state.ride_minutes) + unique_lines * 15
        elif key == "unique":
            base_score = state.unique_count * 1200 + float(state.ride_minutes) + unique_lines * 12
        elif key == "distance":
            base_score = state.path[-1].distance_km * 1000 + float(state.ride_minutes) + unique_lines * 10
        else: # ride
            base_score = float(state.ride_minutes) + unique_lines * 10

        return base_score - repeat_penalty * (8 if key != "loop" else 4) - transfer_penalty_total - stop_repeat_penalty
