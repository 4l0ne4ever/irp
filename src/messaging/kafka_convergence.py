"""
Emit HGA convergence rows to Kafka topic `convergence-log`.
Failures are non-fatal: solver continues if the broker is down.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _json_safe(x: Any) -> Any:
    """Recursively convert numpy scalars and nested structures for json.dumps."""
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return int(x)
    if isinstance(x, float):
        return float(x)
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if hasattr(x, "item") and callable(getattr(x, "item")):
        try:
            return _json_safe(x.item())
        except Exception:
            pass
    try:
        return float(x)
    except (TypeError, ValueError):
        return str(x)

_tls = threading.local()
_producer_lock = threading.Lock()
_producer = None  # lazy singleton

TOPIC = "convergence-log"
DEFAULT_BOOTSTRAP = "localhost:9092"


def set_convergence_run_id(run_id: Optional[str]) -> None:
    """Call before HGA.run() when a run_id is known (e.g. FastAPI job)."""
    _tls.run_id = run_id


def clear_convergence_run_id() -> None:
    _tls.run_id = None


def _get_run_id() -> Optional[str]:
    return getattr(_tls, "run_id", None)


def _get_producer():
    global _producer
    if _producer is False:
        return None
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is False:
            return None
        if _producer is not None:
            return _producer
        try:
            import os
            from kafka import KafkaProducer

            servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_BOOTSTRAP)
            _producer = KafkaProducer(
                bootstrap_servers=servers.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                linger_ms=5,
            )
        except Exception as e:
            logger.warning("Kafka producer not available: %s", e)
            _producer = False
    return None if _producer is False else _producer


def emit_convergence_step(
    generation: int,
    best_fitness: float,
    avg_fitness: float,
    feasible_count: int,
    elapsed_sec: float,
) -> None:
    """Send one convergence row; no-op if no run_id or Kafka unavailable."""
    run_id = _get_run_id()
    if not run_id:
        return
    payload: Dict[str, Any] = {
        "run_id": run_id,
        "generation": generation,
        "best_fitness": float(best_fitness),
        "avg_fitness": float(avg_fitness),
        "feasible_count": int(feasible_count),
        "elapsed_sec": float(elapsed_sec),
    }
    try:
        prod = _get_producer()
        if prod:
            prod.send(TOPIC, value=payload)
    except Exception as e:
        logger.warning("Kafka convergence emit failed (non-fatal): %s", e)


TOPIC_TELEMETRY = "vehicle-telemetry"
TOPIC_ALERT = "irp-alerts"


def emit_vehicle_telemetry(payload: Dict[str, Any]) -> None:
    try:
        prod = _get_producer()
        if prod:
            prod.send(TOPIC_TELEMETRY, value=_json_safe(payload))
    except Exception as e:
        logger.warning("Kafka telemetry emit failed (non-fatal): %s", e)


def emit_irp_alert(payload: Dict[str, Any]) -> None:
    try:
        prod = _get_producer()
        if prod:
            prod.send(TOPIC_ALERT, value=_json_safe(payload))
    except Exception as e:
        logger.warning("Kafka alert emit failed (non-fatal): %s", e)
