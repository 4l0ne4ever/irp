"""
In-memory traffic profile store: day slots, baseline for auto-replan, optional injections.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MOCK = _REPO_ROOT / "config" / "traffic_mock.json"

DEFAULT_SLOT_HOURS = (6.0, 8.0, 10.0, 12.0, 14.0, 17.0, 19.0)
FACTOR_MIN = 0.3
FACTOR_MAX = 1.0


@dataclass
class TrafficObservation:
    source: str
    timestamp: float
    valid_until: Optional[float]
    data: Dict[str, Any]
    confidence: float


class TrafficStateStore:
    """
    Day congestion profile: slot hour -> factor in [FACTOR_MIN, FACTOR_MAX].
    Baseline copy used for auto-replan (factor drop vs initial ingest).
    """

    def __init__(self) -> None:
        self._obs: Optional[TrafficObservation] = None
        self._profile: Dict[float, float] = {}
        self._baseline: Dict[float, float] = {}
        self._injections: List[Tuple[float, float, float, str]] = []

    def clear(self) -> None:
        self._obs = None
        self._profile = {}
        self._baseline = {}
        self._injections = []

    def set_observation(self, obs: TrafficObservation) -> None:
        self._obs = obs

    def get_active(self) -> Optional[TrafficObservation]:
        o = self._obs
        if o is None:
            return None
        if o.valid_until is not None and time.time() > o.valid_until:
            return None
        return o

    def snapshot_dict(self) -> Dict[str, Any]:
        o = self.get_active()
        if o is None:
            return {"source": "none", "confidence": 0.0, "factor": self.get_factor(8.0)}
        return {
            "source": o.source,
            "timestamp": o.timestamp,
            "valid_until": o.valid_until,
            "confidence": o.confidence,
            "data": o.data,
            "factor": self.get_factor(8.0),
        }

    def load_profile(
        self,
        slot_to_factor: Dict[float, float],
        *,
        source: str,
        confidence: float = 1.0,
        valid_until: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Replace day profile and snapshot baseline for auto-replan."""
        self._profile = {float(k): float(max(FACTOR_MIN, min(FACTOR_MAX, v))) for k, v in slot_to_factor.items()}
        self._baseline = dict(self._profile)
        now = time.time()
        meta = dict(metadata or {})
        meta["slots"] = list(self._profile.keys())
        self._obs = TrafficObservation(
            source=source,
            timestamp=now,
            valid_until=valid_until,
            data=meta,
            confidence=float(confidence),
        )

    def get_factor(self, sim_time_h: float) -> float:
        """Effective congestion factor at sim time (injections override, else interpolate profile)."""
        t = float(sim_time_h) % 24.0
        for lo, hi, fac, _lab in self._injections:
            if lo <= t < hi:
                return float(max(FACTOR_MIN, min(FACTOR_MAX, fac)))
        return self._interpolate_profile(self._profile, t)

    def get_baseline_factor(self, sim_time_h: float) -> float:
        t = float(sim_time_h) % 24.0
        return self._interpolate_profile(self._baseline, t)

    @staticmethod
    def _interpolate_profile(profile: Dict[float, float], t: float) -> float:
        if not profile:
            return 1.0
        keys = sorted(profile.keys())
        if t <= keys[0]:
            return float(profile[keys[0]])
        if t >= keys[-1]:
            return float(profile[keys[-1]])
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            if a <= t <= b:
                fa, fb = profile[a], profile[b]
                if abs(b - a) < 1e-9:
                    return float(fa)
                w = (t - a) / (b - a)
                return float(fa + w * (fb - fa))
        return 1.0

    def inject_event(self, from_h: float, to_h: float, factor: float, label: str) -> None:
        fac = float(max(FACTOR_MIN, min(FACTOR_MAX, factor)))
        self._injections.append((float(from_h), float(to_h), fac, label))

    def clear_injections(self) -> None:
        self._injections = []

    def get_current_observation(self) -> Dict[str, Any]:
        snap = self.snapshot_dict()
        t = time.localtime().tm_hour + time.localtime().tm_min / 60.0
        f = self.get_factor(t)
        snap["current_factor"] = f
        snap["baseline_factor"] = self.get_baseline_factor(t)
        return snap

    def apply_model_key(self, key: str) -> None:
        """Planning / monitoring label for UI when not using TomTom ingest."""
        now = time.time()
        if key in ("mock_api", "mock"):
            path = _DEFAULT_MOCK
            if not path.is_file():
                raise FileNotFoundError(str(path))
            raw = json.loads(path.read_text(encoding="utf-8"))
            vu = raw.get("valid_until")
            exp = None
            if vu is not None:
                try:
                    from datetime import datetime, timezone

                    dt = datetime.fromisoformat(str(vu).replace("Z", "+00:00"))
                    exp = dt.timestamp()
                except Exception:
                    exp = None
            dp = raw.get("day_profile")
            if isinstance(dp, dict) and dp:
                slot_map = {float(k): float(v) for k, v in dp.items()}
                self.load_profile(
                    slot_map,
                    source="mock_api",
                    confidence=float(raw.get("confidence", 0.9)),
                    valid_until=exp,
                    metadata={"traffic_zones": raw.get("traffic_zones", [])},
                )
            else:
                self._obs = TrafficObservation(
                    source=str(raw.get("source", "mock_api")),
                    timestamp=now,
                    valid_until=exp,
                    data={"traffic_zones": raw.get("traffic_zones", [])},
                    confidence=float(raw.get("confidence", 0.0)),
                )
                self._profile = {h: 1.0 for h in DEFAULT_SLOT_HOURS}
                self._baseline = dict(self._profile)
        elif key == "tomtom":
            self._obs = TrafficObservation(
                source="tomtom_pending",
                timestamp=now,
                valid_until=None,
                data={},
                confidence=0.0,
            )
        else:
            self._obs = TrafficObservation(
                source="igp",
                timestamp=now,
                valid_until=None,
                data={},
                confidence=1.0,
            )
            self._profile = {h: 1.0 for h in DEFAULT_SLOT_HOURS}
            self._baseline = dict(self._profile)


traffic_store = TrafficStateStore()
