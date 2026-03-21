"""
Kafka consumer thread: forward convergence-log, vehicle-telemetry, irp-alerts
to a queue for the FastAPI WebSocket broadcaster.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from backend.realtime import outbound_queue

logger = logging.getLogger(__name__)

DEFAULT_BOOTSTRAP = "localhost:9092"
TOPICS = ("convergence-log", "vehicle-telemetry", "irp-alerts", "replan-events", "traffic-updates")


def _normalize_message(topic: str, value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if topic == "convergence-log":
        if value.get("kind") == "solver_progress":
            return {
                "type": "solver_progress",
                "run_id": value.get("run_id"),
                "message": value.get("message", ""),
            }
        return {"type": "convergence", **value}
    if topic == "vehicle-telemetry":
        return {"type": "telemetry", **value}
    if topic == "irp-alerts":
        return {"type": "alert", "data": value}
    if topic == "replan-events":
        return dict(value)
    if topic == "traffic-updates":
        return {"type": "traffic_update", **value}
    return None


def start_kafka_forwarder() -> threading.Thread:
    """
    Start daemon thread consuming Kafka topics; push normalized dicts to outbound_queue.
    If Kafka is unavailable, logs warning and exits thread early.
    """

    def _run():
        try:
            from kafka import KafkaConsumer
        except ImportError:
            logger.warning("kafka-python not installed; Kafka forwarder disabled")
            return
        servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_BOOTSTRAP).split(",")
        try:
            consumer = KafkaConsumer(
                *TOPICS,
                bootstrap_servers=servers,
                value_deserializer=lambda b: json.loads(b.decode("utf-8")),
                consumer_timeout_ms=1200,
                auto_offset_reset="latest",
                group_id="irp-fastapi-bridge",
                enable_auto_commit=True,
            )
        except Exception as e:
            logger.warning("Kafka consumer not started: %s", e)
            return
        logger.info("Kafka forwarder listening on %s", TOPICS)
        while True:
            try:
                pack = consumer.poll(timeout_ms=1000)
                for _tp, messages in pack.items():
                    for msg in messages:
                        wrapped = _normalize_message(msg.topic, msg.value)
                        if wrapped:
                            outbound_queue.put(wrapped)
            except Exception as e:
                logger.warning("Kafka poll error: %s", e)
                continue

    t = threading.Thread(target=_run, daemon=True, name="kafka-forwarder")
    t.start()
    return t
