import json
from pathlib import Path

import pytest

from services.planner import (
    PlannerError,
    PlannerService,
    JourneyLeg,
    Label,
    START_TIME_MINUTES,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def planner_service() -> PlannerService:
    segments = sorted(DATA_DIR.glob("segments_*.csv"), key=lambda p: p.stat().st_mtime)
    if not segments:
        pytest.skip("No segments_*.csv available for diagnostics.")
    latest = segments[-1]
    service = PlannerService(data_dir=latest.parent)
    service._load_static_assets()
    try:
        service._load_edges(latest)
    except PlannerError as exc:
        pytest.skip(f"Segments could not be loaded: {exc}")
    if not service._routes:
        print(
            "RAPTOR route tables are empty. Check segments CSV for consistent trip sequences."
        )
        pytest.skip("RAPTOR route tables were not constructed from provided segments.")
    return service


def _label_from_plan(service: PlannerService, plan) -> Label:
    ride_minutes = sum(leg.ride_minutes for leg in plan.legs)
    distance_km = sum(leg.distance_km for leg in plan.legs)
    visited = []
    if plan.legs:
        visited.append(plan.legs[0].from_code)
        for leg in plan.legs:
            visited.append(leg.to_code)
    quadrant_mask = 0
    for code in visited:
        quadrant_mask |= service._quadrant_map.get(code, 0)
    journey_legs = tuple(
        JourneyLeg(
            line_id=leg.line_id,
            line_name=leg.line_name,
            trip_id=leg.trip_id,
            from_code=leg.from_code,
            to_code=leg.to_code,
            depart=leg.depart,
            arrive=leg.arrive,
            distance_km=leg.distance_km,
            stop_hops=leg.stop_hops,
        )
        for leg in plan.legs
    )
    arrival = plan.legs[-1].arrive if plan.legs else START_TIME_MINUTES
    return Label(
        arrival=arrival,
        ride_minutes=ride_minutes,
        distance_km=distance_km,
        visited=frozenset(visited),
        quadrant_mask=quadrant_mask,
        legs=journey_legs,
        score=0.0,
    )


def _print_plan_summary(service: PlannerService, tag: str, plan) -> None:
    label = _label_from_plan(service, plan)
    metrics = service._label_metrics(label)
    summary = {
        "legs": len(plan.legs),
        "ride_minutes": label.ride_minutes,
        "distance_km": round(label.distance_km, 2),
        "unique_lines": len({leg.line_id for leg in plan.legs}),
        "unique_stops": len(label.visited),
        "quadrants": int(metrics["quadrants"]),
        "boundary_hits": metrics.get("boundary_hits", 0),
        "boundary_ratio": round(metrics.get("boundary_ratio", 0.0), 3),
        "boundary_progress": round(metrics.get("boundary_progress", 0.0), 3),
        "hull_area": round(metrics.get("hull_area", 0.0), 2),
        "avg_radius": round(metrics.get("avg_radius", 0.0), 2),
    }
    print(f"\n[{tag}] {summary}")
    output = DATA_DIR / f"raptor_debug_{tag.replace(' ', '_').lower()}.json"
    output.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved RAPTOR plan to {output}")


def _diagnose_config(service: PlannerService, tag: str, config) -> None:
    print(f"\n=== {tag} Diagnostics ===")
    plan = service._run_raptor_challenge(config)
    if plan is None:
        print("RAPTOR returned None, fallback will be used.")
        pytest.skip(f"RAPTOR returned None for {tag}")
    _print_plan_summary(service, tag, plan)


def test_boundary_sequence(planner_service: PlannerService) -> None:
    seq = planner_service._boundary_sequence
    print(f"Boundary sequence length: {len(seq)}")
    if seq:
        print("Boundary sample:", seq[: min(10, len(seq))])
    else:
        pytest.skip("Boundary sequence is empty.")


def test_raptor_longest_duration(planner_service: PlannerService) -> None:
    _diagnose_config(
        planner_service, "Longest Duration", planner_service._config_longest_duration()
    )


def test_raptor_most_stops(planner_service: PlannerService) -> None:
    _diagnose_config(
        planner_service, "Most Stops", planner_service._config_most_stops()
    )


def test_raptor_city_loop(planner_service: PlannerService) -> None:
    _diagnose_config(planner_service, "City Loop", planner_service._config_city_loop())


def test_raptor_longest_distance(planner_service: PlannerService) -> None:
    _diagnose_config(
        planner_service, "Longest Distance", planner_service._config_longest_distance()
    )
