import time

import pytest

from synthetic_ds.circuit import CircuitBreaker, CircuitOpenError


def test_circuit_stays_closed_below_threshold() -> None:
    cb = CircuitBreaker(name="t", window_size=10, failure_threshold=0.6, min_calls=5)
    for _ in range(6):
        cb.before_call()
        cb.on_success()
    for _ in range(3):
        cb.before_call()
        cb.on_failure()
    assert cb.state == "closed"


def test_circuit_opens_over_threshold_and_rejects_calls() -> None:
    cb = CircuitBreaker(
        name="t", window_size=10, failure_threshold=0.5, min_calls=4, cooldown_seconds=1.0
    )
    for _ in range(5):
        try:
            cb.before_call()
        except CircuitOpenError:
            break
        cb.on_failure()
    assert cb.state == "open"

    with pytest.raises(CircuitOpenError):
        cb.before_call()


def test_circuit_half_open_closes_after_successes() -> None:
    cb = CircuitBreaker(
        name="t",
        window_size=6,
        failure_threshold=0.4,
        min_calls=3,
        cooldown_seconds=0.2,
        success_threshold=2,
    )
    for _ in range(4):
        try:
            cb.before_call()
        except CircuitOpenError:
            break
        cb.on_failure()
    assert cb.state == "open"

    time.sleep(0.25)
    # Al volver a llamar debería pasar a half_open y luego a closed tras 2 éxitos
    cb.before_call()
    cb.on_success()
    assert cb.state == "half_open"
    cb.before_call()
    cb.on_success()
    assert cb.state == "closed"


def test_snapshot_reports_rates() -> None:
    cb = CircuitBreaker(name="t", window_size=10, failure_threshold=0.75, min_calls=4)
    for _ in range(2):
        cb.before_call()
        cb.on_success()
    for _ in range(2):
        cb.before_call()
        cb.on_failure()
    snap = cb.snapshot()
    assert snap["state"] == "closed"  # 50% < 75% threshold
    assert snap["failures"] == 2
    assert snap["window_size"] == 4
    assert snap["failure_rate"] == 0.5
