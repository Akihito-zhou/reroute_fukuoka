
from __future__ import annotations

from typing import TYPE_CHECKING

from ..planner_models import ChallengeConfig, ChallengePlan, Label
from ..raptor import run_raptor_challenge
from . import longest_duration

if TYPE_CHECKING:
    from ..planner import PlannerService


def get_config(planner: PlannerService) -> ChallengeConfig:
    """Returns the configuration for the Longest Distance challenge."""
    transfer_buffer = 5
    transfer_penalty_weight = 900

    def scoring_fn(label: Label, metrics: dict[str, float]) -> float:
        return (
            label.distance_km * 12500
            + metrics["avg_leg_distance"] * 1000
            + metrics["max_leg_distance"] * 500
            + metrics["unique_lines"] * 800
            + metrics["avg_radius"] * 220
            + metrics["quadrants"] * 1500
            + metrics["hull_area"] * 60
            + metrics["boundary_ratio"] * 2500
            - metrics["repeat_penalty"] * 700
            - metrics["center_ratio"] * 3200
            - metrics["stop_repeat_total"] * 900
            - label.transfers * transfer_penalty_weight
        )

    def dominance_fn(
        a: Label,
        metrics_a: dict[str, float],
        b: Label,
        metrics_b: dict[str, float],
    ) -> bool:
        if (
            a.distance_km >= b.distance_km
            and metrics_a["avg_radius"] >= metrics_b["avg_radius"]
            and metrics_a["boundary_ratio"] >= metrics_b["boundary_ratio"]
            and a.arrival <= b.arrival
        ):
            return a.score >= b.score
        return False

    def accept_fn(_: Label, __: dict[str, float]) -> bool:
        return True

    return ChallengeConfig(
        challenge_id="longest-distance",
        title="距離最長ツアー",
        tagline="24時間で博多を起終点に最長距離を駆け抜けるロングトリップ。",
        theme_tags=["距離最大化", "耐久"],
        badge="最長距離",
        require_quadrants=False,
        max_rounds=50,
        scoring_fn=scoring_fn,
        dominance_fn=dominance_fn,
        accept_fn=accept_fn,
        min_transfer_minutes=transfer_buffer,
        max_stop_visits=4,
        max_line_visits=2,
    )


def plan(planner: "PlannerService") -> ChallengePlan | None:
    """Plans the Longest Distance challenge."""
    result = planner.run_beam_search(
        score_key="distance",
        require_unique=False,
        require_quadrants=False,
        max_queue=3500,
        max_expansions=220000,
        max_branch=12,
        max_stop_visits=4,
        min_transfer_minutes=5,
        transfer_penalty_minutes=5,
        hakata_max_visits=None,
        stop_repeat_penalty_weight=900,
    )
    if result:
        from ..planner_utils import collapse_edges, derive_quadrant_labels
        legs = collapse_edges(result.path, planner.stations)
        return ChallengePlan(
            challenge_id="longest-distance",
            title="距離最長ツアー",
            tagline="24時間で博多を起終点に最長距離を駆け抜けるロングトリップ。",
            theme_tags=["距離最大化", "耐久"],
            badge="最長距離",
            legs=legs,
            start_stop_name=planner.stations[planner.hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, planner.quadrant_map),
        )

    # Fallback to the more expensive RAPTOR algorithm
    config = get_config(planner)
    return run_raptor_challenge(planner, config)
