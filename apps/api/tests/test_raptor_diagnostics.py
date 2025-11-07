import json
import time
from collections import Counter
from pathlib import Path

import pytest

from services.planner import (
    START_TIME_MINUTES,
    JourneyLeg,
    Label,
    PlannerError,
    PlannerService,
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
    stop_counts = Counter()
    line_counts = Counter()
    transfers = 0
    min_transfer_gap = 10**9
    prev_leg = None
    for idx, leg in enumerate(plan.legs):
        if idx == 0:
            visited.append(leg.from_code)
        stop_counts[leg.from_code] += 1
        visited.append(leg.to_code)
        stop_counts[leg.to_code] += 1
        line_counts[leg.line_id] += 1
        if prev_leg:
            if prev_leg.line_id != leg.line_id or prev_leg.trip_id != leg.trip_id:
                transfers += 1
                gap = leg.depart - prev_leg.arrive
                min_transfer_gap = min(min_transfer_gap, gap)
        prev_leg = leg
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
        stop_counts=tuple(sorted(stop_counts.items())),
        line_counts=tuple(sorted(line_counts.items())),
        transfers=transfers,
        min_transfer_gap=min_transfer_gap if transfers else 10**9,
    )


def _collect_plan_stats(service: PlannerService, plan) -> dict:
    label = _label_from_plan(service, plan)
    metrics = service._label_metrics(label)
    stop_counts: Counter[str] = Counter()
    line_counts: Counter[str] = Counter()
    min_transfer_gap = None
    transfers = 0
    prev_leg = None
    for leg in plan.legs:
        stop_counts[leg.from_code] += 1
        stop_counts[leg.to_code] += 1
        line_counts[leg.line_id] += 1
        if prev_leg:
            gap = leg.depart - prev_leg.arrive
            min_transfer_gap = gap if min_transfer_gap is None else min(min_transfer_gap, gap)
            if prev_leg.line_id != leg.line_id or prev_leg.trip_id != leg.trip_id:
                transfers += 1
        prev_leg = leg

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
        "min_transfer_gap": min_transfer_gap if min_transfer_gap is not None else 0,
        "transfers": transfers,
        "max_stop_visits": max(stop_counts.values()) if stop_counts else 0,
        "stop_counts": stop_counts,
        "line_counts": line_counts,
    }
    return summary


def _print_plan_summary(service: PlannerService, tag: str, plan) -> dict:
    stats = _collect_plan_stats(service, plan)
    print(f"\n[{tag}] {stats}")
    output = DATA_DIR / f"raptor_debug_{tag.replace(' ', '_').lower()}.json"
    output.write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Saved RAPTOR plan to {output}")
    return stats


def _diagnose_config(service: PlannerService, tag: str, config) -> None:
    print(f"\n=== {tag} Diagnostics ===")
    start = time.perf_counter()
    plan = service._run_raptor_challenge(config)
    duration = time.perf_counter() - start
    print(f"{tag} computed in {duration:.2f}s")
    if plan is None:
        print("RAPTOR returned None, fallback will be used.")
        pytest.skip(f"RAPTOR returned None for {tag}")
    stats = _print_plan_summary(service, tag, plan)
    expectations = ROUTE_EXPECTATIONS.get(tag)
    if expectations:
        _assert_plan_constraints(
            stats, expectations, set(service._hakata_stops or [])
        )


def _assert_plan_constraints(
    stats: dict, expectations: dict, hakata_stops: set[str]
) -> None:
    if "min_transfer_gap" in expectations:
        assert (
            stats["min_transfer_gap"] >= expectations["min_transfer_gap"]
        ), (
            "Minimum transfer gap "
            f"{stats['min_transfer_gap']} is less than expected "
            f"{expectations['min_transfer_gap']}"
        )

    if "max_stop_visits" in expectations:
        non_hakata_counts = [
            count
            for stop, count in stats["stop_counts"].items()
            if stop not in hakata_stops
        ]
        max_non_hakata = max(non_hakata_counts) if non_hakata_counts else 0
        assert (
            max_non_hakata <= expectations["max_stop_visits"]
        ), f"Non-Hakata stop exceeded visit limit: {stats['stop_counts']}"

    if expectations.get("forbid_non_hakata_duplicates"):
        duplicates = [
            stop
            for stop, count in stats["stop_counts"].items()
            if stop not in hakata_stops and count > 1
        ]
        assert not duplicates, f"Non-Hakata stops repeated: {duplicates}"

    if expectations.get("require_quadrants"):
        assert (
            stats["quadrants"] >= 4
        ), f"Quadrant coverage insufficient: {stats['quadrants']}"


ROUTE_EXPECTATIONS = {
    "Longest Duration": {"min_transfer_gap": 5, "max_stop_visits": 3},
    "Longest Distance": {"min_transfer_gap": 5, "max_stop_visits": 4},
    "Most Stops": {
        "min_transfer_gap": 6,
        "max_stop_visits": 2,
        "forbid_non_hakata_duplicates": False,
    },
    "City Loop": {
        "min_transfer_gap": 5,
        "max_stop_visits": 2,
        "require_quadrants": True,
    },
}


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
