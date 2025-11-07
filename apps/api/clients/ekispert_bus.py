from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://mixway.ekispert.jp"
REALTIME_TRIP_ENDPOINT = "/v1/json/realtime/trip"
REALTIME_COURSE_EXTREME_ENDPOINT = "/v1/json/realtime/search/course/extreme"
REALTIME_COURSE_PATTERN_ENDPOINT = "/v1/json/realtime/search/course/pattern"


def _join_url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


@dataclass(frozen=True)
class TripQuery:
    line_id: str | None = None
    trip_id: str | None = None
    operation_line_code: str | None = None
    direction: str | None = None


class EkispertBusClient:
    """Thin wrapper around Ekispert realtime bus endpoints.

    The implementation focuses on resiliency: short timeout, limited retries,
    and graceful degradation (returning empty payload when the client is
    misconfigured). The caller is responsible for interpreting the response.
    """

    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: requests.Session | None = None,
        timeout: float = 6.0,
        max_retries: int = 2,
        retry_backoff: float = 0.6,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff

    def fetch_realtime_trips(
        self,
        queries: Sequence[TripQuery] | None = None,
        *,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch realtime trip status for a collection of queries.

        The Ekispert API supports a limited set of query parameters per request;
        the caller may invoke this method multiple times with different batches.
        """
        if not self._api_key:
            logger.debug("Realtime trip fetch skipped: missing API key.")
            return []
        params: dict[str, Any] = {"key": self._api_key}
        if extra_params:
            params.update(extra_params)
        if queries:
            # Filter out empty values to avoid API errors.
            first = queries[0]
            if first.line_id:
                params["line_id"] = first.line_id
            if first.trip_id:
                params["trip_id"] = first.trip_id
            if first.operation_line_code:
                params["operationLineCode"] = first.operation_line_code
            if first.direction:
                params["direction"] = first.direction
        raw = self._request_json(_join_url(self._base_url, REALTIME_TRIP_ENDPOINT), params)
        if isinstance(raw, dict):
            buses = raw.get("ResultSet", {}).get("Bus")
            if isinstance(buses, dict):
                return [buses]
            if isinstance(buses, list):
                return buses
            return []
        if isinstance(raw, list):
            return raw
        return []

    def fetch_realtime_courses(
        self,
        *,
        pattern: bool = False,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the realtime course endpoints (extreme or pattern)."""
        if not self._api_key:
            logger.debug("Realtime course fetch skipped: missing API key.")
            return {}
        payload = {"key": self._api_key}
        if params:
            payload.update(params)
        endpoint = (
            REALTIME_COURSE_PATTERN_ENDPOINT if pattern else REALTIME_COURSE_EXTREME_ENDPOINT
        )
        result = self._request_json(_join_url(self._base_url, endpoint), payload)
        if isinstance(result, list) and result:
            return result[0]
        if isinstance(result, dict):
            return result
        return {}

    def _request_json(self, url: str, params: dict[str, Any]) -> Any:
        """Execute GET with retries and parse JSON; returns {} / [] on errors."""
        for attempt in range(self._max_retries + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                logger.warning("Realtime request failed (%s): %s", url, exc)
                break
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    logger.warning("Realtime request returned non-JSON body at %s", url)
                    return []
            if response.status_code in {429, 500, 502, 503, 504}:
                sleep_for = self._retry_backoff * (2**attempt)
                logger.debug(
                    "Realtime request %s failed with %s; retrying in %.2fs",
                    url,
                    response.status_code,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue
            logger.warning(
                "Realtime request %s failed with status %s: %s",
                url,
                response.status_code,
                response.text[:200],
            )
            break
        return []
