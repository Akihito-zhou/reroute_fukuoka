from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from typing import Dict, Iterable, Optional, Sequence, Tuple, TYPE_CHECKING

try:  # pragma: no cover - support flat module imports
    from ..clients.ekispert_bus import EkispertBusClient, TripQuery
except ImportError:  # pragma: no cover
    from clients.ekispert_bus import EkispertBusClient, TripQuery  # type: ignore

if TYPE_CHECKING:
    try:
        from .planner import TripEdge
    except ImportError:  # pragma: no cover
        from planner import TripEdge  # type: ignore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeSegmentPatch:
    trip_id: str
    from_code: str
    to_code: str
    depart: Optional[int]
    arrive: Optional[int]
    status: str | None = None
    delay_minutes: Optional[int] = None


class RealtimeTimetableManager:
    """Maintains a fused view of static timetable edges and realtime patches."""

    def __init__(
        self,
        client: Optional[EkispertBusClient],
        *,
        enable_realtime: bool = True,
        cache_seconds: int = 120,
    ) -> None:
        self._realtime_enabled = bool(enable_realtime and client is not None)
        self._client = client if self._realtime_enabled else None
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._static_edges: list["TripEdge"] = []
        self._patches: Dict[Tuple[str, str, str], RealtimeSegmentPatch] = {}
        self._last_refresh: float = 0.0

    def load_static_edges(self, edges: Sequence["TripEdge"]) -> None:
        with self._lock:
            self._static_edges = list(edges)
            self._patches.clear()
            self._last_refresh = 0.0

    def get_edges_for_window(
        self,
        start_minutes: int,
        end_minutes: int,
        *,
        line_filter: Optional[Iterable[str]] = None,
        force_refresh: bool = False,
    ) -> list["TripEdge"]:
        """Return edges clipped to the requested time window, patched with realtime data."""
        if force_refresh:
            self.refresh_realtime(line_filter=line_filter)
        else:
            self.refresh_realtime(line_filter=line_filter, soft=True)

        selected_lines = set(line_filter) if line_filter else None

        with self._lock:
            result: list["TripEdge"] = []
            for edge in self._static_edges:
                if selected_lines and edge.line_id not in selected_lines:
                    continue
                if edge.arrive < start_minutes or edge.depart > end_minutes:
                    continue
                patch = self._patches.get((edge.trip_id, edge.from_code, edge.to_code))
                if patch and patch.status and patch.status.lower() == "cancelled":
                    continue
                if patch and patch.depart is not None and patch.arrive is not None:
                    result.append(replace(edge, depart=patch.depart, arrive=patch.arrive))
                else:
                    result.append(edge)
            return result

    def refresh_realtime(
        self,
        *,
        line_filter: Optional[Iterable[str]] = None,
        soft: bool = False,
    ) -> None:
        """Fetch realtime updates if cache expired. `soft=True` skips fetch when cache valid."""
        if not self._realtime_enabled or not self._client:
            return
        now = time.time()
        with self._lock:
            if soft and now - self._last_refresh < self._cache_seconds:
                return
        queries = self._build_trip_queries(line_filter)
        if not queries:
            with self._lock:
                self._last_refresh = now
            return
        payload = self._client.fetch_realtime_trips(queries)
        patches = self._parse_trip_payload(payload)
        with self._lock:
            if patches:
                self._patches.update(patches)
            self._last_refresh = now

    @property
    def realtime_enabled(self) -> bool:
        return self._realtime_enabled

    def _build_trip_queries(
        self, line_filter: Optional[Iterable[str]]
    ) -> list[TripQuery]:
        if line_filter:
            lines = set(line_filter)
        else:
            lines = set()
        with self._lock:
            if lines:
                relevant = [edge for edge in self._static_edges if edge.line_id in lines]
            else:
                relevant = self._static_edges
            queries: list[TripQuery] = []
            seen: set[Tuple[str, str]] = set()
            for edge in relevant:
                key = (edge.line_id, edge.trip_id)
                if key in seen:
                    continue
                seen.add(key)
                queries.append(
                    TripQuery(
                        line_id=edge.line_id,
                        trip_id=edge.trip_id,
                        direction=edge.direction,
                    )
                )
            return queries

    def _parse_trip_payload(
        self, payload: Sequence[dict]
    ) -> Dict[Tuple[str, str, str], RealtimeSegmentPatch]:
        patches: Dict[Tuple[str, str, str], RealtimeSegmentPatch] = {}
        for entry in payload or []:
            trip = entry.get("Trip") or entry
            trip_id = str(trip.get("tripId") or trip.get("TripID") or trip.get("id") or "")
            line_id = str(trip.get("operationLineCode") or trip.get("line_id") or "")
            stops = trip.get("Stop") or entry.get("Stop")
            if isinstance(stops, dict):
                stops = [stops]
            if not trip_id or not stops:
                continue
            for segment in stops:
                frm = str(segment.get("fromCode") or segment.get("from") or segment.get("from_stop") or "")
                to = str(segment.get("toCode") or segment.get("to") or segment.get("to_stop") or "")
                if not frm or not to:
                    continue
                depart = self._parse_minutes(segment.get("departure"))
                arrive = self._parse_minutes(segment.get("arrival"))
                status = segment.get("status") or trip.get("status")
                delay = self._parse_optional_int(segment.get("delay"))
                patches[(trip_id, frm, to)] = RealtimeSegmentPatch(
                    trip_id=trip_id,
                    from_code=frm,
                    to_code=to,
                    depart=depart,
                    arrive=arrive,
                    status=status,
                    delay_minutes=delay,
                )
        if not patches and payload:
            logger.debug("Realtime payload contained no recognizable segment updates.")
        return patches

    @staticmethod
    def _parse_minutes(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) >= 5 and text[2] == ":":
            try:
                hours = int(text[0:2])
                mins = int(text[3:5])
            except ValueError:
                return None
            return hours * 60 + mins
        try:
            return int(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_optional_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
