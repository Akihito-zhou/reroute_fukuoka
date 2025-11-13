
from __future__ import annotations

from typing import TYPE_CHECKING

from ..planner_models import ChallengeConfig, ChallengePlan, Label
from ..raptor import run_raptor_challenge

if TYPE_CHECKING:
    from ..planner import PlannerService


def get_config(planner: PlannerService) -> ChallengeConfig:
    """Returns the configuration for the Longest Duration challenge."""
    transfer_buffer = 5
    transfer_penalty_weight = 800

    def scoring_fn(label: Label, metrics: dict[str, float]) -> float:
        stop_counts = dict(label.stop_counts)
        for stop, count in stop_counts.items():
            limit = challenge_config.max_stop_visits
            if stop in planner.hakata_stops:
                limit = challenge_config.hakata_max_visits or limit
            if limit and count > limit:
                return -1.0

        return (
            label.ride_minutes * 10000
            + metrics["unique_lines"] * 600
            + metrics["quadrants"] * 1800
            + metrics["avg_radius"] * 160
            + metrics["boundary_ratio"] * 2200
            - metrics["center_ratio"] * 4000
            - metrics["short_leg_ratio"] * 3000
            - metrics["repeat_penalty"] * 500
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
            a.ride_minutes >= b.ride_minutes
            and metrics_a["unique_lines"] >= metrics_b["unique_lines"]
            and a.arrival <= b.arrival
        ):
            return a.score >= b.score
        return False

    def accept_fn(_: Label, __: dict[str, float]) -> bool:
        return True

    challenge_config = ChallengeConfig(
        challenge_id="longest-duration",
        title="24時間ロングライド",
        tagline="博多から出発し24時間ひたすら乗り継ぎ続ける耐久チャレンジ。",
        theme_tags=["時間最大化", "耐久"],
        badge="最長乗車",
        require_quadrants=False,
        max_rounds=50,
        scoring_fn=scoring_fn,
        dominance_fn=dominance_fn,
        accept_fn=accept_fn,
        min_transfer_minutes=transfer_buffer,
        max_stop_visits=3,
        max_line_visits=2,
        hakata_max_visits=3,
    )
    return challenge_config


def plan(planner: "PlannerService") -> ChallengePlan | None:
    """Plans the Longest Duration challenge."""
    result = planner.run_beam_search(
        score_key="ride",
        require_unique=False,
        require_quadrants=False,
        max_queue=2500,
        max_expansions=150000,
        max_stop_visits=3,
        max_line_visits=2,
        min_transfer_minutes=5,
        transfer_penalty_minutes=5,
        hakata_max_visits=3,
        stop_repeat_penalty_weight=900,
    )
    if result:
        from ..planner_utils import collapse_edges, derive_quadrant_labels
        legs = collapse_edges(result.path, planner.stations)
        return ChallengePlan(
            challenge_id="longest-duration",
            title="24時間ロングライド",
            tagline="博多から出発し24時間ひたすら乗り継ぎ続ける耐久チャレンジ。",
            theme_tags=["時間最大化", "耐久"],
            badge="最長乗車",
            legs=legs,
            start_stop_name=planner.stations[planner.hakata_stops[0]].name,
            wards=derive_quadrant_labels(legs, planner.quadrant_map),
        )

    # Fallback to the more expensive RAPTOR algorithm
    config = get_config(planner)
    return run_raptor_challenge(planner, config)
