"""Optional Kafka convergence emit for HGA (non-fatal if broker down)."""

from src.messaging.kafka_convergence import (
    clear_convergence_run_id,
    emit_convergence_step,
    emit_irp_alert,
    emit_vehicle_telemetry,
    set_convergence_run_id,
)

__all__ = [
    "set_convergence_run_id",
    "clear_convergence_run_id",
    "emit_convergence_step",
    "emit_vehicle_telemetry",
    "emit_irp_alert",
]
