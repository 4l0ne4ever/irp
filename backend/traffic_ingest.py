"""
TomTom Traffic Flow: batch fetch flowSegmentData per coordinate, aggregate per time slot.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from backend.traffic_state import DEFAULT_SLOT_HOURS, FACTOR_MAX, FACTOR_MIN, traffic_store

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_KEYS = _REPO_ROOT / "config" / "api_keys.env"


def _load_api_key() -> str:
    key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if key:
        return key
    if _ENV_KEYS.is_file():
        for line in _ENV_KEYS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "TOMTOM_API_KEY":
                    return v.strip().strip('"').strip("'")
    return ""


def compute_factor(current_speed: float, free_flow_speed: float) -> float:
    if free_flow_speed is None or free_flow_speed <= 1e-6:
        return FACTOR_MAX
    r = float(current_speed) / float(free_flow_speed)
    return max(FACTOR_MIN, min(FACTOR_MAX, r))


def _fetch_one_point(lat: float, lon: float, api_key: str) -> Tuple[float, float]:
    """Return (current_speed, free_flow_speed) km/h."""
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    params = {"point": f"{lat},{lon}", "unit": "KMPH", "key": api_key}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    fsd = data.get("flowSegmentData") or data.get("flowSegmentData".lower())
    if isinstance(fsd, list) and fsd:
        fsd = fsd[0]
    if not isinstance(fsd, dict):
        raise RuntimeError("TomTom response missing flowSegmentData")
    cs = float(fsd.get("currentSpeed") or fsd.get("current_speed") or 0.0)
    ff = float(fsd.get("freeFlowSpeed") or fsd.get("free_flow_speed") or 0.0)
    return cs, ff


def fetch_day_profile(
    coords_lonlat: Any,
    *,
    api_key: Optional[str] = None,
    slots: Tuple[float, ...] = DEFAULT_SLOT_HOURS,
    pause_s: float = 0.05,
) -> Dict[str, Any]:
    """
    For each slot hour, average congestion factors over all waypoints.
    Does not fall back on failure — raises so the caller can surface the error.
    """
    key = api_key if api_key is not None else _load_api_key()
    if not key:
        raise RuntimeError("TOMTOM_API_KEY is not set (env or config/api_keys.env)")

    n = int(coords_lonlat.shape[0])
    if n < 1:
        raise ValueError("coords empty")

    slot_factors: Dict[float, float] = {}
    request_id = f"ingest-{int(time.time())}"

    for slot in slots:
        factors: List[float] = []
        for i in range(n):
            lon = float(coords_lonlat[i, 0])
            lat = float(coords_lonlat[i, 1])
            cs, ff = _fetch_one_point(lat, lon, key)
            factors.append(compute_factor(cs, ff))
            time.sleep(pause_s)
        slot_factors[float(slot)] = float(sum(factors) / max(1, len(factors)))

    meta = {
        "provider": "tomtom",
        "request_id": request_id,
        "slots": list(slot_factors.keys()),
        "n_points": n,
    }
    traffic_store.load_profile(
        slot_factors,
        source="tomtom",
        confidence=1.0,
        valid_until=time.time() + 86400.0,
        metadata=meta,
    )
    return {"slot_factors": slot_factors, "metadata": meta}
