import json
from pathlib import Path

import pytest

from services.planner import PlannerError, PlannerService

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def planner_service() -> PlannerService:
    segments = sorted(DATA_DIR.glob("segments_*.csv"), key=lambda p: p.stat().st_mtime)
    if not segments:
        pytest.skip("No segments_*.csv available for testing.")

    latest = segments[-1]
    service = PlannerService(data_dir=latest.parent)
    service._load_static_assets()
    try:
        service._load_edges(latest)
    except PlannerError as exc:  # pragma: no cover - diagnostic skip
        pytest.skip(f"Segments could not be loaded: {exc}")

    assert service._stop_schedules, "Stop schedules not populated from segments."
    return service


def _summarize_plan(plan, filename: str, label: str) -> None:
    total_minutes = sum(leg.ride_minutes for leg in plan.legs)
    print(f"\n[{label} Preview]")
    print(f"Leg count: {len(plan.legs)} / Total ride minutes: {total_minutes}")
    for leg in plan.legs[:10]:
        print(
            f"{leg.line_id} {leg.from_name}→{leg.to_name} "
            f"{leg.depart:04d}-{leg.arrive:04d} ({leg.ride_minutes}分)"
        )

    output_path = DATA_DIR / filename
    output_path.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nSaved full {label.lower()} plan to {output_path}")


def test_longest_duration_plan(planner_service: PlannerService) -> None:
    plan = planner_service._plan_longest_duration()
    assert plan.legs, "Planner failed to produce longest-duration legs."
    _summarize_plan(plan, "debug_longest_duration.json", "Longest Duration")
    metrics = {
        "legs": len(plan.legs),
        "ride_minutes": sum(leg.ride_minutes for leg in plan.legs),
        "distance_km": sum(leg.distance_km for leg in plan.legs),
        "unique_lines": len({leg.line_id for leg in plan.legs}),
        "unique_stops": len(
            {leg.from_code for leg in plan.legs} | {plan.legs[-1].to_code}
        ),
        "quadrants": len(
            {planner_service._quadrant_map.get(leg.to_code, 0) for leg in plan.legs}
        ),
    }
    print(f"[Longest Duration Metrics] {metrics}")


def test_most_unique_plan(planner_service: PlannerService) -> None:
    plan = planner_service._plan_most_unique_stops()
    assert plan.legs, "Planner failed to produce most-unique-stops legs."
    _summarize_plan(plan, "debug_most_unique.json", "Most Unique Stops")
    metrics = {
        "legs": len(plan.legs),
        "ride_minutes": sum(leg.ride_minutes for leg in plan.legs),
        "distance_km": sum(leg.distance_km for leg in plan.legs),
        "unique_lines": len({leg.line_id for leg in plan.legs}),
        "unique_stops": len(
            {leg.from_code for leg in plan.legs} | {plan.legs[-1].to_code}
        ),
        "quadrants": len(
            {planner_service._quadrant_map.get(leg.to_code, 0) for leg in plan.legs}
        ),
    }
    print(f"[Most Stops Metrics] {metrics}")


def test_city_loop_plan(planner_service: PlannerService) -> None:
    plan = planner_service._plan_city_loop()
    assert plan.legs, "Planner failed to produce city-loop legs."
    _summarize_plan(plan, "debug_city_loop.json", "City Loop")
    metrics = {
        "legs": len(plan.legs),
        "ride_minutes": sum(leg.ride_minutes for leg in plan.legs),
        "distance_km": sum(leg.distance_km for leg in plan.legs),
        "unique_lines": len({leg.line_id for leg in plan.legs}),
        "unique_stops": len(
            {leg.from_code for leg in plan.legs} | {plan.legs[-1].to_code}
        ),
        "quadrants": len(
            {planner_service._quadrant_map.get(leg.to_code, 0) for leg in plan.legs}
        ),
    }
    print(f"[City Loop Metrics] {metrics}")


def test_longest_distance_plan(planner_service: PlannerService) -> None:
    plan = planner_service._plan_longest_distance()
    assert plan.legs, "Planner failed to produce longest-distance legs."
    _summarize_plan(plan, "debug_longest_distance.json", "Longest Distance")
    metrics = {
        "legs": len(plan.legs),
        "ride_minutes": sum(leg.ride_minutes for leg in plan.legs),
        "distance_km": sum(leg.distance_km for leg in plan.legs),
        "unique_lines": len({leg.line_id for leg in plan.legs}),
        "unique_stops": len(
            {leg.from_code for leg in plan.legs} | {plan.legs[-1].to_code}
        ),
        "quadrants": len(
            {planner_service._quadrant_map.get(leg.to_code, 0) for leg in plan.legs}
        ),
    }
    print(f"[Longest Distance Metrics] {metrics}")
