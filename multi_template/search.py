"""Optuna TPE search jointly over (template, placement, scale, rotation).

We fix the working graph (one OSMnx pull per location), then ask Optuna for
candidates: pick a template index, jitter the centre by ±placement_m,
choose a scale within the target range, and a rotation. Score by combined
fidelity (Fréchet + (1-IoU)) plus a soft penalty if route distance leaves
the target band.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from .fidelity import score_route
from .graph_loader import StreetGraph, _haversine_m
from .projection import project_template
from .router import RoutedShape, route_through_waypoints
from .templates_loader import Template


@dataclass
class Candidate:
    template_idx: int
    template_vote_id: str
    template_source: str
    center_lat: float
    center_lon: float
    scale_m: float
    rotation_deg: float
    n_waypoints: int
    routed: RoutedShape
    fidelity: dict
    objective: float


@dataclass
class SearchResult:
    best: Candidate
    all_candidates: List[Candidate]
    n_trials: int
    elapsed_s: float


def _objective_value(
    fid: dict,
    route_len_m: float,
    target_min_m: float,
    target_max_m: float,
    *,
    length_penalty_per_km: float = 1.0,
) -> float:
    if not fid["ok"]:
        return 1e6
    base = fid["frechet"] + 0.5 * fid["mhd"] + 0.5 * (1.0 - fid["iou"])
    if length_penalty_per_km > 0:
        if route_len_m < target_min_m:
            base += length_penalty_per_km * (target_min_m - route_len_m) / 1000.0
        elif route_len_m > target_max_m:
            base += length_penalty_per_km * (route_len_m - target_max_m) / 1000.0
    return base


def search_animal_at_location(
    templates: List[Template],
    sg: StreetGraph,
    *,
    target_distance_m: float = 20_000,
    distance_tolerance_m: float = 5_000,
    placement_radius_m: float = 4_000,
    scale_min_m: float = 4_000,
    scale_max_m: float = 9_000,
    n_waypoints: int = 32,
    n_trials: int = 60,
    seed: int = 17,
    keep_top: int = 8,
    router_alpha: float = 3.0,
    router_beta: float = 2.5,
    router_revisit_penalty_m: float = 4000.0,
    rotation_min_deg: float = -90.0,
    rotation_max_deg: float = 90.0,
    length_penalty_per_km: float = 1.0,
) -> SearchResult:
    """Joint Optuna search.

    `scale_m` is the long-side metric extent of the projected template.
    Routed length will typically be 2-3× scale because the route walks the
    whole outline (perimeter ≈ 2-3× side for irregular shapes).
    """
    if not templates:
        raise ValueError("no templates")
    G = sg.G
    target_min = target_distance_m - distance_tolerance_m
    target_max = target_distance_m + distance_tolerance_m

    # convert placement_radius_m to lat/lon offsets for sampling
    deg_per_m_lat = 1.0 / 111_320.0
    deg_per_m_lon = 1.0 / (111_320.0 * math.cos(math.radians(sg.center_lat)))

    candidates: List[Candidate] = []
    t0 = time.time()

    def objective(trial: optuna.Trial) -> float:
        idx = trial.suggest_int("template_idx", 0, len(templates) - 1)
        dx = trial.suggest_float("offset_x_m", -placement_radius_m, placement_radius_m)
        dy = trial.suggest_float("offset_y_m", -placement_radius_m, placement_radius_m)
        scale_m = trial.suggest_float("scale_m", scale_min_m, scale_max_m)
        rot = trial.suggest_float("rotation_deg", rotation_min_deg, rotation_max_deg)

        clat = sg.center_lat + dy * deg_per_m_lat
        clon = sg.center_lon + dx * deg_per_m_lon

        tpl = templates[idx]
        try:
            waypoints, _ = project_template(
                tpl.points,
                center_lat=clat, center_lon=clon,
                scale_m=scale_m, rotation_deg=rot,
                n_waypoints=n_waypoints,
            )
            routed = route_through_waypoints(
                G, waypoints,
                alpha=router_alpha,
                beta=router_beta,
                revisit_penalty_m=router_revisit_penalty_m,
            )
        except Exception as e:
            return 1e6
        if routed is None:
            return 1e6

        fid = score_route(tpl.points, routed.polyline, n_samples=120)
        obj = _objective_value(
            fid, routed.total_length_m, target_min, target_max,
            length_penalty_per_km=length_penalty_per_km,
        )
        candidates.append(Candidate(
            template_idx=idx, template_vote_id=tpl.vote_id, template_source=tpl.source_kind,
            center_lat=clat, center_lon=clon, scale_m=scale_m, rotation_deg=rot,
            n_waypoints=n_waypoints, routed=routed, fidelity=fid, objective=obj,
        ))
        return obj

    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=12)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    candidates.sort(key=lambda c: c.objective)
    best = candidates[0]
    return SearchResult(
        best=best, all_candidates=candidates[:keep_top],
        n_trials=n_trials, elapsed_s=time.time() - t0,
    )
