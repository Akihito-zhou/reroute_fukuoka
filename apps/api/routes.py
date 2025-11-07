from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from data.challenges import CHALLENGES
from schemas import ChallengeDetailOut, ChallengeSummaryOut
from services import PlannerError, PlannerService

router = APIRouter(prefix="/api/v1")
_planner_service: PlannerService | None = None
_debug_cache: dict[str, dict] = {}

DATA_DIR = Path(__file__).resolve().parent / "data"
DEBUG_FILES = {
    "longest-duration": DATA_DIR / "debug_longest_duration.json",
    "most-stops": DATA_DIR / "debug_most_unique.json",
    "city-loop": DATA_DIR / "debug_city_loop.json",
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
        try:
            return planner.list_challenges()
        except PlannerError:
            pass
    debug = _load_all_debug_challenges()
    if debug:
        return debug
    return CHALLENGES


@router.get("/challenges/{challenge_id}", response_model=ChallengeDetailOut)
def get_challenge(challenge_id: str) -> ChallengeDetailOut:
    planner = get_planner_service()
    if planner:
        try:
            return planner.get_challenge(challenge_id)
        except PlannerError:
            pass
    debug = _load_debug_challenge(challenge_id)
    if debug:
        return debug

    for challenge in CHALLENGES:
        if challenge["id"] == challenge_id:
            return challenge
    raise HTTPException(status_code=404, detail="Challenge not found")


def _load_debug_challenge(challenge_id: str) -> dict | None:
    if challenge_id in _debug_cache:
        return _debug_cache[challenge_id]
    path = DEBUG_FILES.get(challenge_id)
    if not path or not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except json.JSONDecodeError:
        return None
    _debug_cache[challenge_id] = payload
    return payload


def _load_all_debug_challenges() -> list[dict]:
    challenges: list[dict] = []
    for challenge_id in DEBUG_FILES.keys():
        payload = _load_debug_challenge(challenge_id)
        if payload:
            challenges.append(payload)
    return challenges
