from __future__ import annotations

from lifeos_windows_agent.collector import ActivityCollector, RawWindowsSample


class FakeSensor:
    def collect(self) -> RawWindowsSample:
        return RawWindowsSample(
            process_id=None,
            window_title="x" * 400,
            idle_seconds=12,
            is_locked=False,
        )


class FailingSensor:
    def collect(self) -> RawWindowsSample:
        raise OSError("sensor unavailable")


def test_collector_emits_only_approved_truncated_fields() -> None:
    payload, reasons = ActivityCollector(FakeSensor()).collect()

    assert payload.window_title == "x" * 256
    assert payload.idle_seconds == 12
    assert payload.is_locked is False
    assert payload.sensor_ok is True
    assert reasons == ["SENSOR_SAMPLE"]
    assert set(payload.model_dump()) == {
        "foreground_process",
        "window_title",
        "idle_seconds",
        "is_locked",
        "manual_presence",
        "sensor_ok",
        "client_session_state",
    }


def test_sensor_failure_is_unknown_evidence_not_activity() -> None:
    payload, reasons = ActivityCollector(FailingSensor()).collect()

    assert payload.sensor_ok is False
    assert payload.foreground_process is None
    assert reasons == ["SENSOR_FAILURE"]
