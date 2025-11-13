
from __future__ import annotations

from typing import TYPE_CHECKING

from ..planner_cityloop import plan_city_loop_tsp
from ..planner_models import ChallengeConfig, ChallengePlan, Label
from ..raptor import run_raptor_challenge

if TYPE_CHECKING:
    from ..planner import PlannerService


def get_config(planner: PlannerService) -> ChallengeConfig:
    """Returns the configuration for the City Loop challenge."""
    transfer_buffer = 5
    transfer_penalty_weight = 900

    def scoring_fn(label: Label, metrics: dict[str, float]) -> float:
        if metrics["quadrants"] < 4:
            return (
                metrics["quadrants"] * 1200
                + metrics["avg_radius"] * 80
                + metrics["boundary_ratio"] * 1800
                - metrics["stop_repeat_total"] * 1200
            )
        return (
            metrics["hull_area"] * 120
            + metrics["avg_radius"] * 220
            + metrics["angle_span"] * 35
            + metrics["turn_sum"] * 25
            + label.distance_km * 25
            + metrics["boundary_ratio"] * 8000
            + metrics["boundary_progress"] * 6000
            + metrics["max_radius_per_quadrant"] * 1000
            - metrics["center_ratio"] * 4500
            - metrics["repeat_penalty"] * 500
            - metrics["stop_repeat_total"] * 1500
            - label.transfers * transfer_penalty_weight
        )

    def dominance_fn(
        a: Label,
        metrics_a: dict[str, float],
        b: Label,
        metrics_b: dict[str, float],
    ) -> bool:
        if (
            metrics_a["quadrants"] >= metrics_b["quadrants"]
            and metrics_a["boundary_ratio"] >= metrics_b["boundary_ratio"]
            and metrics_a["hull_area"] >= metrics_b["hull_area"]
            and a.arrival <= b.arrival
        ):
            return a.score >= b.score
        return False

    def accept_fn(label: Label, metrics: dict[str, float]) -> bool:
        return (
            metrics["quadrants"] == 4
            and metrics["hull_area"] >= 25.0
            and metrics["avg_radius"] >= 3.0
            and metrics["angle_span"] >= 180.0
            and metrics["boundary_ratio"] >= 0.3
        )

    return ChallengeConfig(
        challenge_id="city-loop",
        title="福岡市一周トレース",
        tagline="市内の北東・南東・南西・北西ゾーンをすべて踏んで一筆書きで戻る。",
        theme_tags=["シティループ", "周回"],
        badge="周回達人",
        require_quadrants=True,
        max_rounds=50,
        scoring_fn=scoring_fn,
        dominance_fn=dominance_fn,
        accept_fn=accept_fn,
        min_transfer_minutes=transfer_buffer,
    )


def plan(planner: "PlannerService") -> ChallengePlan | None:
    """Plans the City Loop challenge, trying TSP first and falling back to RAPTOR."""
    tsp_plan = plan_city_loop_tsp(planner)
    if tsp_plan:
        return tsp_plan
    
    result = planner.run_beam_search(
        score_key="loop",
        require_unique=False,
        require_quadrants=True,
        max_queue=3500,
        max_expansions=220000,
        max_branch=12,
        min_transfer_minutes=5,
        transfer_penalty_minutes=5,
        hakata_max_visits=2,
        stop_repeat_penalty_weight=1400,
    )
    if result:
        from ..planner_utils import collapse_edges, derive_quadrant_labels
        legs = collapse_edges(result.path, planner.stations)
        return ChallengePlan(
            challenge_id="city-loop",
            title="福岡市一周トレース",
            tagline="市内の北東・南東・南西・北西ゾーンをすべて踏んで一筆書きで戻る。",
            theme_tags=["シティループ", "周回"],
            badge="周回達人",
            legs=legs,
            start_stop_name=planner.stations[planner.hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, planner.quadrant_map),
        )

    # Fallback to the more expensive RAPTOR algorithm
    config = get_config(planner)
    return run_raptor_challenge(planner, config)
