from __future__ import annotations

import logging
from typing import Sequence, TYPE_CHECKING

from .planner_constants import ALL_QUADRANTS_MASK, START_TIME_MINUTES
from .planner_models import ChallengeConfig, ChallengePlan, Label
from .planner_utils import derive_quadrant_labels, distance_km, label_leg_to_plan
from .planners import city_loop
from .raptor import run_raptor_challenge

if TYPE_CHECKING:
    from .planner import PlannerService

logger = logging.getLogger(__name__)


def plan_city_loop_tsp(service: "PlannerService") -> ChallengePlan | None:
    """用TSP启发式配合RAPTOR拼出城市环方案 / TSPヒューリスティックとRAPTORを組み合わせて市内ループ案を生成する。"""
    if not service.hakata_stops or not service.boundary_sequence:
        logger.warning("Cannot plan TSP city loop: Hakata stops or boundary sequence missing.")
        return None

    start_stop = service.hakata_stops[0]
    ordered_candidates = [start_stop] + [code for code in service.boundary_sequence if code != start_stop]

    if len(ordered_candidates) < 4:
        logger.warning("Not enough boundary candidates (%d) for TSP city loop.", len(ordered_candidates))
        return None

    distance_matrix = _build_tsp_distance_matrix(service, ordered_candidates)
    candidate_sequences = _generate_tsp_sequences(ordered_candidates, distance_matrix)

    logger.info("TSP city loop will evaluate %d candidate tours.", len(candidate_sequences))

    for idx, sequence in enumerate(candidate_sequences, start=1):
        logger.info("Evaluating TSP tour %d: %s", idx, sequence)
        plan = _assemble_city_loop_plan(service, sequence)
        if plan:
            logger.info("TSP city loop accepted candidate %d.", idx)
            return plan

    logger.warning("TSP city loop planner could not produce a valid itinerary.")
    return None


def _build_tsp_distance_matrix(service: "PlannerService", nodes: Sequence[str]) -> dict[tuple[str, str], float]:
    """根据站点经纬度计算节点距离矩阵 / 停留所の緯度経度からノード間距離行列を計算する。"""
    matrix: dict[tuple[str, str], float] = {}
    for i, a in enumerate(nodes):
        station_a = service.stations.get(a)
        if not station_a:
            continue
        for j, b in enumerate(nodes):
            if i == j:
                continue
            station_b = service.stations.get(b)
            if not station_b:
                continue
            matrix[(a, b)] = distance_km(station_a.lat, station_a.lon, station_b.lat, station_b.lon)
    return matrix


def _nearest_neighbor_tour(
    nodes: Sequence[str],
    matrix: dict[tuple[str, str], float],
) -> list[str]:
    """使用最近邻策略构造初始巡回 / 最近近傍法で初期巡回を作成する。"""
    start = nodes[0]
    unvisited = list(nodes[1:])
    route = [start]
    current = start
    while unvisited:
        next_stop = min(unvisited, key=lambda stop: matrix.get((current, stop), float("inf")))
        route.append(next_stop)
        unvisited.remove(next_stop)
        current = next_stop
    route.append(start)
    return route


def _two_opt_tour(
    route: Sequence[str],
    matrix: dict[tuple[str, str], float],
    max_iterations: int = 30,
) -> list[str]:
    """用2-opt迭代优化巡回顺序 / 2-optアルゴリズムで巡回順を改良する。"""
    best = list(route)
    improved = True

    def distance(a: str, b: str) -> float:
        return matrix.get((a, b)) or matrix.get((b, a)) or float("inf")

    def tour_length(path: Sequence[str]) -> float:
        return sum(distance(path[i], path[i + 1]) for i in range(len(path) - 1))

    current_distance = tour_length(best)
    iterations = 0
    while improved and iterations < max_iterations:
        improved = False
        iterations += 1
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                if j - i == 1:
                    continue
                new_route = best[:i] + best[i:j][::-1] + best[j:]
                new_distance = tour_length(new_route)
                if new_distance + 1e-6 < current_distance:
                    best = new_route
                    current_distance = new_distance
                    improved = True
                    break
            if improved:
                break
    return best


def _generate_tsp_sequences(
    nodes: Sequence[str],
    matrix: dict[tuple[str, str], float],
) -> list[list[str]]:
    """组合多种巡回候选供RAPTOR尝试 / RAPTORで試す複数の巡回候補を組み立てる。"""
    sequences: list[list[str]] = []

    nn_route = _nearest_neighbor_tour(nodes, matrix)
    sequences.append(nn_route)
    sequences.append(list(reversed(nn_route)))

    improved = _two_opt_tour(nn_route, matrix)
    if improved != nn_route:
        sequences.append(improved)

    boundary_cycle = list(nodes)
    if boundary_cycle[-1] != boundary_cycle[0]:
        boundary_cycle.append(boundary_cycle[0])
    sequences.append(boundary_cycle)

    unique_sequences: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for seq in sequences:
        key = tuple(seq)
        if key in seen:
            continue
        seen.add(key)
        unique_sequences.append(seq)
    return unique_sequences


def _assemble_city_loop_plan(service: "PlannerService", sequence: Sequence[str]) -> ChallengePlan | None:
    """按照TSP订单调用RAPTOR拼成完整计划 / TSP順にRAPTORを呼び出して完全なプランを組み立てる。"""
    if len(sequence) < 4:
        return None
    all_legs = []
    current_time = float(START_TIME_MINUTES)

    for from_stop, to_stop in zip(sequence, sequence[1:], strict=False):
        if from_stop == to_stop:
            continue
        logger.info("Planning TSP leg %s -> %s starting at %s", from_stop, to_stop, current_time)
        
        # Create a simple config for point-to-point routing
        config = ChallengeConfig(
            challenge_id="p2p",
            title="P2P",
            tagline="",
            theme_tags=[],
            badge="",
            require_quadrants=False,
            max_rounds=4,
            scoring_fn=lambda l, m: -l.arrival, # Fastest path
            dominance_fn=lambda a, ma, b, mb: a.arrival <= b.arrival,
            accept_fn=lambda l, m: l.visited and list(l.legs)[-1].to_code == to_stop,
            min_transfer_minutes=5,
        )
        
        # Temporarily modify service for single origin
        original_hakata_stops = service.hakata_stops
        service.hakata_stops = [from_stop]
        
        plan = run_raptor_challenge(service, config)
        
        # Restore service state
        service.hakata_stops = original_hakata_stops

        if not plan:
            logger.warning("No RAPTOR path for segment %s -> %s in TSP sequence.", from_stop, to_stop)
            return None
        
        all_legs.extend(plan.legs)
        current_time = plan.legs[-1].arrive if plan.legs else current_time

        if current_time - START_TIME_MINUTES > 24 * 60:
            logger.info("TSP candidate exceeded 24h horizon (arrival=%s).", current_time)
            return None

    if not _city_loop_plan_is_valid(service, all_legs, current_time):
        return None

    config = city_loop.get_config(service)
    start_name = (
        service.stations[service.hakata_stops[0]].name
        if service.hakata_stops and service.hakata_stops[0] in service.stations
        else "博多駅"
    )

    return ChallengePlan(
        challenge_id=config.challenge_id,
        title=config.title,
        tagline=config.tagline,
        theme_tags=config.theme_tags,
        badge=config.badge,
        legs=all_legs,
        start_stop_name=start_name,
        wards=derive_quadrant_labels(all_legs, service.quadrant_map),
    )


def _city_loop_plan_is_valid(service: "PlannerService", legs, final_arrival: float) -> bool:
    """检查是否满足24小时与四象限覆盖 / 24時間内・4象限制覇を満たしているか検証する。"""
    if not legs:
        return False
    duration = final_arrival - START_TIME_MINUTES
    if duration > 24 * 60:
        logger.info("City loop plan duration %.1fmin exceeds 24h.", duration)
        return False
    quadrant_mask = 0
    if service.hakata_stops:
        quadrant_mask |= service.quadrant_map.get(service.hakata_stops[0], 0)
    for leg in legs:
        quadrant_mask |= service.quadrant_map.get(leg.from_code, 0)
        quadrant_mask |= service.quadrant_map.get(leg.to_code, 0)
    if quadrant_mask != ALL_QUADRANTS_MASK:
        logger.info("City loop plan missing quadrants (mask=%s).", bin(quadrant_mask))
        return False
    return True