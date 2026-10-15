from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


class EconomicBridge:
    RATE_CPU_SECOND_SATS = Decimal("10")
    RATE_PEAK_MB_SATS = Decimal("0.05")
    RATE_IO_MB_SATS = Decimal("2")
    BYTES_PER_MB = Decimal("1048576")

    def __init__(self, wallet: Any = None, frugal_engine: Any = None):
        self.wallet = wallet
        self.frugal_engine = frugal_engine

    def settle_execution_cost(self, resource_meter_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            cpu_seconds = Decimal(str(resource_meter_payload.get("cpu_seconds", 0)))
            peak_memory_bytes = Decimal(str(resource_meter_payload.get("peak_memory_bytes", 0)))
            io_read_bytes = Decimal(str(resource_meter_payload.get("io_read_bytes", 0)))
            io_write_bytes = Decimal(str(resource_meter_payload.get("io_write_bytes", 0)))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("resource measurements must be numeric") from exc
        measurements = (cpu_seconds, peak_memory_bytes, io_read_bytes, io_write_bytes)
        if any(not value.is_finite() or value < 0 for value in measurements):
            raise ValueError("resource measurements must be finite and non-negative")
        byte_measurements = (peak_memory_bytes, io_read_bytes, io_write_bytes)
        if any(value != value.to_integral_value() for value in byte_measurements):
            raise ValueError("memory and I/O measurements must be whole bytes")

        io_bytes = io_read_bytes + io_write_bytes
        peak_mb = peak_memory_bytes / self.BYTES_PER_MB
        io_mb = io_bytes / self.BYTES_PER_MB
        cost_sats = (
            cpu_seconds * self.RATE_CPU_SECOND_SATS
            + peak_mb * self.RATE_PEAK_MB_SATS
            + io_mb * self.RATE_IO_MB_SATS
        )
        settled_sats = int(cost_sats.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        task_id = resource_meter_payload.get("task_id", "unnamed_task")
        settlement_receipt = {
            "task_id": task_id,
            "cpu_seconds": float(cpu_seconds),
            "peak_mb": float(peak_mb),
            "io_mb": float(io_mb),
            "estimated_cost_sats": settled_sats,
            "settled": True,
        }
        if self.wallet is not None:
            self.wallet.debit_sats(settled_sats, reason=f"ResourceMeter:{task_id}")
        return settlement_receipt
