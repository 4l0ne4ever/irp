"""
Travel time models for IRP-TW-DT.

`TravelTimeModel` is the façade: the solver calls `duration_h(from_idx, to_idx, depart_h, dist_km)`
instead of reading hardcoded zones directly.

Default `IGPModel` matches the historical IGP piecewise speeds (Hanoi-style profile).
`MockAPIModel` loads zone speeds from JSON (simulated API payload).
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

import numpy as np

from .constants import TRAFFIC_ZONES as DEFAULT_TRAFFIC_ZONES, H

logger = logging.getLogger(__name__)

# Repo root: src/core/traffic.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MOCK_PATH = _REPO_ROOT / "config" / "traffic_mock.json"


def _find_zone(hour: float, zones: Sequence[Tuple[float, float, float]]) -> int:
    hour = hour % H
    for i, (z_start, z_end, _) in enumerate(zones):
        if z_start <= hour < z_end:
            return i
    return 0


def _igp_travel_time_core(
    distance_km: float,
    depart_h: float,
    zones: Sequence[Tuple[float, float, float]],
) -> float:
    if distance_km < 0.0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")
    if distance_km <= 0.0:
        return 0.0

    depart_h = depart_h % H
    remaining_km = distance_km
    current_h = depart_h
    elapsed_h = 0.0
    max_iterations = len(zones) * 3
    iteration = 0

    while remaining_km > 1e-12 and iteration < max_iterations:
        iteration += 1
        zone_idx = _find_zone(current_h, zones)
        z_start, z_end, speed = zones[zone_idx]
        time_available = z_end - current_h
        if time_available <= 1e-12:
            current_h = z_end % H
            if current_h < 1e-12 and z_end >= H:
                current_h = 0.0
            continue
        dist_possible = time_available * speed
        if remaining_km <= dist_possible + 1e-12:
            elapsed_h += remaining_km / speed
            remaining_km = 0.0
        else:
            elapsed_h += time_available
            remaining_km -= dist_possible
            current_h = z_end % H
            if current_h < 1e-12 and z_end >= H:
                current_h = 0.0

    return elapsed_h


class TravelTimeModel(ABC):
    """Abstract travel-time façade (hours) for dynamic or static routing."""

    @abstractmethod
    def duration_h(
        self,
        from_idx: int,
        to_idx: int,
        depart_h: float,
        dist_km: float,
    ) -> float:
        """Travel time in hours from `from_idx` to `to_idx` departing at `depart_h` (decimal hour)."""

    def matrix_slice(self, dist_matrix: np.ndarray, depart_h: float) -> np.ndarray:
        """Full time matrix for a fixed departure hour (uses graph indices 0..N-1)."""
        n = dist_matrix.shape[0]
        out = np.zeros((n, n), dtype=float)
        for i in range(n):
            for j in range(n):
                if i != j:
                    out[i, j] = self.duration_h(i, j, depart_h, float(dist_matrix[i, j]))
        return out


class IGPModel(TravelTimeModel):
    """Piecewise constant speeds (default constants.TRAFFIC_ZONES)."""

    def __init__(self, zones: Optional[Sequence[Tuple[float, float, float]]] = None) -> None:
        self._zones: List[Tuple[float, float, float]] = [
            (float(a), float(b), float(c)) for a, b, c in (zones or DEFAULT_TRAFFIC_ZONES)
        ]

    def duration_h(
        self,
        from_idx: int,
        to_idx: int,
        depart_h: float,
        dist_km: float,
    ) -> float:
        del from_idx, to_idx
        return _igp_travel_time_core(dist_km, depart_h, self._zones)


class TomTomModel(TravelTimeModel):
    """
    Scales IGP travel time by a congestion factor f(sim_time), typically from TrafficStateStore.
    """

    def __init__(self, get_factor: Callable[[float], float]) -> None:
        self._igp = IGPModel()
        self._get_factor = get_factor

    def duration_h(
        self,
        from_idx: int,
        to_idx: int,
        depart_h: float,
        dist_km: float,
    ) -> float:
        del from_idx, to_idx
        base = self._igp.duration_h(0, 0, depart_h, dist_km)
        f = float(self._get_factor(float(depart_h)))
        f = max(0.3, min(1.0, f))
        return base * f


class MockAPIModel(TravelTimeModel):
    """
    Loads `traffic_zones` from JSON (simulated API). Same structure as IGP zones:
    each entry [start_h, end_h, speed_kmh].
    """

    def __init__(self, json_path: Optional[os.PathLike[str] | str] = None) -> None:
        path = Path(json_path or os.environ.get("TRAFFIC_MOCK_JSON", _DEFAULT_MOCK_PATH))
        if not path.is_file():
            raise FileNotFoundError(f"Mock traffic JSON not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        zones = raw.get("traffic_zones")
        if not zones or not isinstance(zones, list):
            raise ValueError("traffic_mock.json must contain non-empty 'traffic_zones' array")
        self._zones = [(float(z[0]), float(z[1]), float(z[2])) for z in zones]
        self.meta: dict[str, Any] = {
            "source": raw.get("source", "mock_api"),
            "valid_until": raw.get("valid_until"),
            "confidence": float(raw.get("confidence", 0.0)),
        }

    def duration_h(
        self,
        from_idx: int,
        to_idx: int,
        depart_h: float,
        dist_km: float,
    ) -> float:
        del from_idx, to_idx
        return _igp_travel_time_core(dist_km, depart_h, self._zones)


def build_travel_model(name: str, mock_path: Optional[str] = None) -> TravelTimeModel:
    key = (name or "igp").strip().lower()
    if key == "igp":
        return IGPModel()
    if key in ("mock_api", "mock"):
        return MockAPIModel(mock_path)
    if key == "tomtom":
        raise ValueError("tomtom model must be built via runner with traffic_store.get_factor")
    raise ValueError(f"Unknown traffic model: {name}")


def default_travel_model() -> TravelTimeModel:
    return IGPModel()


# --- Backward-compatible module-level helpers (tests, baselines, generator) ---

def igp_travel_time(distance_km: float, depart_h: float) -> float:
    """Historical API: same as `IGPModel().duration_h(0, 0, depart_h, distance_km)`."""
    return _igp_travel_time_core(distance_km, depart_h, DEFAULT_TRAFFIC_ZONES)


def igp_arrival_time(distance_km: float, depart_h: float) -> float:
    return depart_h + igp_travel_time(distance_km, depart_h)


def static_travel_time(distance_km: float, speed_kmh: float = 18.0) -> float:
    if distance_km <= 0.0:
        return 0.0
    return distance_km / speed_kmh


def precompute_travel_time_matrix(
    dist_matrix: np.ndarray,
    depart_h: float,
    model: Optional[TravelTimeModel] = None,
) -> np.ndarray:
    tm = model if model is not None else IGPModel()
    return tm.matrix_slice(dist_matrix, depart_h)


def precompute_static_travel_time_matrix(
    dist_matrix: np.ndarray,
    speed_kmh: float = 18.0,
) -> np.ndarray:
    tt_matrix = np.zeros_like(dist_matrix)
    mask = dist_matrix > 0
    tt_matrix[mask] = dist_matrix[mask] / speed_kmh
    return tt_matrix
