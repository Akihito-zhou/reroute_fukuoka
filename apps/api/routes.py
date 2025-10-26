from __future__ import annotations

from fastapi import APIRouter, HTTPException

from data.challenges import CHALLENGES
from schemas import ChallengeDetailOut, ChallengeSummaryOut
from services import PlannerError, PlannerService

router = APIRouter(prefix="/api/v1")
_planner_service: PlannerService | None = None


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
    return CHALLENGES


@router.get("/challenges/{challenge_id}", response_model=ChallengeDetailOut)
def get_challenge(challenge_id: str) -> ChallengeDetailOut:
    planner = get_planner_service()
    if planner:
        try:
            return planner.get_challenge(challenge_id)
        except PlannerError:
            pass

    for challenge in CHALLENGES:
        if challenge["id"] == challenge_id:
            return challenge
    raise HTTPException(status_code=404, detail="Challenge not found")
