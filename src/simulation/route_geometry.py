"""
Shared OSRM / straight-line leg geometry for replay and monitoring map polylines.
"""

from __future__ import annotations

import logging
import os
from math import atan2, cos, radians, sin, sqrt
import threading
from typing import List, Optional, Tuple

import numpy as np

from src.data.distances import get_osrm_route_geometry

logger = logging.getLogger(__name__)


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
    if os.environ.get("IRP_E2E_REPLAY_NO_OSRM") == "1":
        geom = None
    else:
        try:
            _t = float(os.environ.get("IRP_OSRM_GEOMETRY_TIMEOUT", "60"))
        except ValueError:
            _t = 60.0
        geom = get_osrm_route_geometry(coords, [a, b], timeout=_t)
    if geom:
        return [(float(p[0]), float(p[1])) for p in geom]
    if os.environ.get("IRP_E2E_REPLAY_NO_OSRM") != "1":
        logger.warning("OSRM geometry None for leg %s→%s — straight line", a, b)
    return [
        (float(coords[a, 1]), float(coords[a, 0])),
        (float(coords[b, 1]), float(coords[b, 0])),
    ]


def build_routed_latlon_path(coords: np.ndarray, indices: List[int]) -> List[List[float]]:
    """Full path [lat, lon] along the solution sequence (roads when OSRM returns geometry)."""
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
