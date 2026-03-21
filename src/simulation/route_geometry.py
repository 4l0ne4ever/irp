"""
Shared OSRM / straight-line leg geometry for replay and monitoring map polylines.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from math import atan2, cos, radians, sin, sqrt
import threading
from typing import List, Optional, Tuple

import numpy as np

from src.data.distances import get_osrm_route_geometry

logger = logging.getLogger(__name__)

# Replay calls the same leg many times; avoid hammering public OSRM (rate limits).
_LEG_CACHE_MAX = 512
_leg_geom_cache: "OrderedDict[tuple[int, int, int], List[Tuple[float, float]]]" = OrderedDict()
_leg_cache_lock = threading.Lock()


def _leg_cache_get(coords: np.ndarray, a: int, b: int) -> Optional[List[Tuple[float, float]]]:
    key = (id(coords), int(a), int(b))
    with _leg_cache_lock:
        hit = _leg_geom_cache.pop(key, None)
        if hit is not None:
            _leg_geom_cache[key] = hit
            return [tuple(p) for p in hit]
    return None


def _leg_cache_put(coords: np.ndarray, a: int, b: int, wps: List[Tuple[float, float]]) -> None:
    key = (id(coords), int(a), int(b))
    with _leg_cache_lock:
        if key in _leg_geom_cache:
            _leg_geom_cache.pop(key, None)
        _leg_geom_cache[key] = list(wps)
        while len(_leg_geom_cache) > _LEG_CACHE_MAX:
            _leg_geom_cache.popitem(last=False)


def _dedupe_consecutive_indices(indices: List[int]) -> List[int]:
    out: List[int] = []
    for x in indices:
        ix = int(x)
        if not out or out[-1] != ix:
            out.append(ix)
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    rlat1, rlon1 = radians(lat1), radians(lon1)
    rlat2, rlon2 = radians(lat2), radians(lon2)
    dlat, dlon = rlat2 - rlat1, rlon2 - rlon1
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    a = min(1.0, max(0.0, a))
    c = 2 * atan2(sqrt(a), sqrt(max(0.0, 1.0 - a)))
    return 6371.0088 * c


def waypoints_for_leg(
    coords: np.ndarray,
    a: int,
    b: int,
    stop_event: Optional[threading.Event] = None,
) -> List[Tuple[float, float]]:
    """Ordered (lat, lon) points along one leg: OSRM route or straight segment."""
    if stop_event is not None and stop_event.is_set():
        return [
            (float(coords[a, 1]), float(coords[a, 0])),
            (float(coords[b, 1]), float(coords[b, 0])),
        ]
    cached = _leg_cache_get(coords, a, b)
    if cached is not None:
        return cached
    if os.environ.get("IRP_E2E_REPLAY_NO_OSRM") == "1":
        geom = None
    else:
        try:
            _t = float(os.environ.get("IRP_OSRM_GEOMETRY_TIMEOUT", "60"))
        except ValueError:
            _t = 60.0
        geom = get_osrm_route_geometry(coords, [a, b], timeout=_t)
    if geom:
        out = [(float(p[0]), float(p[1])) for p in geom]
        _leg_cache_put(coords, a, b, out)
        return out
    if os.environ.get("IRP_E2E_REPLAY_NO_OSRM") != "1":
        logger.warning("OSRM geometry None for leg %s→%s — straight line", a, b)
    out = [
        (float(coords[a, 1]), float(coords[a, 0])),
        (float(coords[b, 1]), float(coords[b, 0])),
    ]
    _leg_cache_put(coords, a, b, out)
    return out


def _build_routed_latlon_path_leg_by_leg(coords: np.ndarray, indices: List[int]) -> List[List[float]]:
    """Stitch per-leg OSRM calls (many HTTP requests; fallback when full-route fails)."""
    full: List[List[float]] = []
    for i in range(len(indices) - 1):
        a, b = int(indices[i]), int(indices[i + 1])
        wps = waypoints_for_leg(coords, a, b)
        if not wps:
            continue
        if full:
            la0, lo0 = wps[0]
            la1, lo1 = full[-1]
            if abs(la0 - la1) < 1e-7 and abs(lo0 - lo1) < 1e-7:
                wps = wps[1:]
        for lat, lon in wps:
            full.append([float(lat), float(lon)])
    return full


def build_routed_latlon_path(coords: np.ndarray, indices: List[int]) -> List[List[float]]:
    """Full path [lat, lon] along the solution sequence (roads when OSRM returns geometry).

    Uses the same strategy as planning folium maps: **one OSRM Route request** for the full
    ordered waypoint list when possible. That matches ``visualize.py`` and avoids the public
    demo rate-limit / burst failures from issuing one Route call per leg (monitoring used to
    do only leg-by-leg, unlike the solver which uses the Table API for distances).
    """
    idx = _dedupe_consecutive_indices(indices)
    if len(idx) < 2:
        return []

    if os.environ.get("IRP_E2E_REPLAY_NO_OSRM") == "1":
        return _build_routed_latlon_path_leg_by_leg(coords, idx)

    try:
        _t = float(os.environ.get("IRP_OSRM_GEOMETRY_TIMEOUT", "60"))
    except ValueError:
        _t = 60.0

    geom = get_osrm_route_geometry(coords, idx, timeout=_t)
    if geom:
        return [[float(p[0]), float(p[1])] for p in geom]

    logger.info("OSRM full-route geometry failed for %s stops — falling back to per-leg requests", len(idx))
    return _build_routed_latlon_path_leg_by_leg(coords, idx)
