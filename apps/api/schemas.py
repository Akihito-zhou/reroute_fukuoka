from __future__ import annotations

"""
Pydantic response schemas emitted by the FastAPI service.

These schemas wrap the static challenge data so that the frontend consumes
typed and well-defined JSON structures.
"""

from typing import List, Literal, Tuple

from pydantic import BaseModel, Field


class RestStopOut(BaseModel):
    at: str = Field(..., description="Stop name where riders can take a break.")
    minutes: int = Field(..., description="Recommended break duration in minutes.")
    suggestion: str = Field(..., description="Idea for how to spend the break.")


class LegOut(BaseModel):
    sequence: int = Field(..., description="Sequential order of the leg within the itinerary.")
    line_label: str = Field(..., description="Line number or code shown on buses.")
    line_name: str = Field(..., description="Official or common line name.")
    from_stop: str = Field(..., description="Boarding stop name.")
    to_stop: str = Field(..., description="Alighting stop name.")
    departure: str = Field(..., description="Scheduled departure time (HH:MM).")
    arrival: str = Field(..., description="Scheduled arrival time (HH:MM).")
    ride_minutes: int = Field(..., description="Planned riding duration in minutes.")
    distance_km: float = Field(..., description="Approximate distance covered during the leg.")
    notes: List[str] = Field(default_factory=list, description="Notes highlighting unique aspects.")
    geometry: dict | None = Field(
        default=None,
        description="GeoJSON geometry describing the leg path (LineString).",
    )
    path: List[dict] | None = Field(
        default=None,
        description="Simplified list of coordinate dicts (lat/lon) for the leg path.",
    )
    from_coord: dict | None = Field(
        default=None, description="Starting coordinate of the leg (lat/lon)."
    )
    to_coord: dict | None = Field(
        default=None, description="Ending coordinate of the leg (lat/lon)."
    )


class ChallengeSummaryOut(BaseModel):
    id: str
    title: str
    tagline: str
    theme_tags: List[str]
    start_stop: str
    start_time: str
    total_ride_minutes: int
    total_distance_km: float
    transfers: int
    wards: List[str]
    badges: List[str]


class ChallengeDetailOut(ChallengeSummaryOut):
    legs: List[LegOut]
    rest_stops: List[RestStopOut]
