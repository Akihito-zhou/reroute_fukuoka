from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from fastapi import APIRouter, HTTPException

from data.challenges import CHALLENGES
from schemas import ChallengeDetailOut, ChallengeSummaryOut
from services import PlannerError, PlannerService

router = APIRouter(prefix="/api/v1")
_planner_service: PlannerService | None = None
_debug_cache: dict[str, dict] = {}
logger = logging.getLogger(__name__)

# 15秒のタイムアウト
PLANNER_TIMEOUT_SECONDS = 15

DATA_DIR = Path(__file__).resolve().parent / "data"
DEBUG_FILES = {
    "longest-duration": DATA_DIR / "raptor_debug_longest_duration.json",
    "most-stops": DATA_DIR / "raptor_debug_most_stops.json",
    "city-loop": DATA_DIR / "raptor_debug_city_loop.json",
    "longest-distance": DATA_DIR / "raptor_debug_longest_distance.json",
}


def get_planner_service() -> PlannerService | None:
    global _planner_service
    if _planner_service is None:
        try:
            _planner_service = PlannerService()
        except PlannerError:
            _planner_service = None
    return _planner_service


@router.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/challenges", response_model=list[ChallengeSummaryOut])
def list_challenges() -> list[ChallengeSummaryOut]:
    planner = get_planner_service()
    if planner:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(planner.list_challenges)
            try:
                return future.result(timeout=PLANNER_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("Planner timed out for list_challenges. Falling back.")
            except Exception:
                logger.exception("Planner failed for list_challenges. Falling back.")

    # フォールバックロジック
    debug = _load_all_debug_challenges()
    if debug:
        return debug
    return CHALLENGES


@router.get("/challenges/{challenge_id}", response_model=ChallengeDetailOut)
def get_challenge(challenge_id: str) -> ChallengeDetailOut:
    planner = get_planner_service()
    if planner:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(planner.get_challenge, challenge_id)
            try:
                return future.result(timeout=PLANNER_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning(
                    f"Planner timed out for challenge '{challenge_id}'. Falling back."
                )
            except Exception:
                logger.exception(
                    f"Planner failed for challenge '{challenge_id}'. Falling back."
                )

    # フォールバックロジック
    debug = _load_debug_challenge(challenge_id)
    if debug:
        return debug

    slug = _normalize_challenge_id(challenge_id)
    for challenge in CHALLENGES:
        if _normalize_challenge_id(challenge["id"]) == slug:
            return challenge
    raise HTTPException(status_code=404, detail="Challenge not found")



def _load_debug_challenge(challenge_id: str) -> dict | None:
    slug = _normalize_challenge_id(challenge_id)
    if slug in _debug_cache:
        return _debug_cache[slug]

    path = DEBUG_FILES.get(slug)
    if not path or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except json.JSONDecodeError:
        return None
    _debug_cache[slug] = payload
    return payload


def _load_all_debug_challenges() -> list[dict]:
    challenges: list[dict] = []
    for challenge_id in DEBUG_FILES.keys():
        payload = _load_debug_challenge(challenge_id)
        if payload:
            challenges.append(payload)
    return challenges


def _normalize_challenge_id(challenge_id: str) -> str:
    """Normalize incoming challenge IDs for consistent lookup."""
    return challenge_id.strip().lower().replace("_", "-")
