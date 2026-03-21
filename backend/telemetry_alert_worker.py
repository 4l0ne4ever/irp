"""
Second Kafka consumer on `vehicle-telemetry`: detect TW violations and emit `irp-alerts`.
Separate consumer group from the FastAPI→WS forwarder.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Set, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BOOTSTRAP = "localhost:9092"
_TOPIC = "vehicle-telemetry"
# Dedupe: one TW alert per (run_id, vehicle, day, next_customer) until process restart
_fired_tw: Set[Tuple[str, int, int, int]] = set()
_lock = threading.Lock()


def _maybe_emit_tw_violation(payload: Dict[str, Any]) -> None:
    eta = payload.get("eta_h")
    plan = payload.get("planned_arrival_h")
    run_id = payload.get("run_id")
    vid = payload.get("vehicle_id")
    day = payload.get("day")
    nid = payload.get("next_customer_id")
    if eta is None or plan is None or run_id is None or vid is None or day is None or nid is None:
        return
    if float(eta) <= float(plan) + 0.25:
        return
    key = (str(run_id), int(vid), int(day), int(nid))
    with _lock:
        if key in _fired_tw:
            return
        _fired_tw.add(key)
    try:
        from datetime import datetime, timezone

        from src.messaging.kafka_convergence import emit_irp_alert

        emit_irp_alert(
            {
                "run_id": str(run_id),
                "type": "tw_violation",
                "vehicle_id": int(vid),
                "day": int(day),
                "customer_id": int(nid),
                "eta_h": float(eta),
                "planned_arrival_h": float(plan),
                "message": f"ETA {eta:.2f}h > planned {plan:.2f}h + 0.25h",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.warning("TW alert emit failed: %s", e)
        with _lock:
            _fired_tw.discard(key)


def start_telemetry_alert_worker() -> threading.Thread:
    def _run() -> None:
        try:
            from kafka import KafkaConsumer
        except ImportError:
            logger.warning("kafka-python not installed; telemetry alert worker disabled")
            return
        servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_BOOTSTRAP).split(",")
        try:
            consumer = KafkaConsumer(
                _TOPIC,
                bootstrap_servers=servers,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                consumer_timeout_ms=1200,
                auto_offset_reset="latest",
                group_id="irp-telemetry-tw-checker",
                enable_auto_commit=True,
            )
        except Exception as e:
            logger.warning("Telemetry alert consumer not started: %s", e)
            return
        logger.info("Telemetry TW checker listening on %s", _TOPIC)
        while True:
            try:
                pack = consumer.poll(timeout_ms=1000)
                for _tp, messages in pack.items():
                    for msg in messages:
                        _maybe_emit_tw_violation(msg.value)
            except Exception as e:
                logger.warning("Telemetry alert poll error: %s", e)
                continue

    t = threading.Thread(target=_run, daemon=True, name="kafka-tw-alerts")
    t.start()
    return t
