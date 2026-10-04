from __future__ import annotations

import pytest

from endstone_cps_detector.config import CPSSettings
from endstone_cps_detector.cps_manager import CPSManager


def measure_steady_rate(target_cps: float, *, duration: float = 2.0) -> float:
    manager = CPSManager(CPSSettings())
    interval = 1.0 / target_cps
    count = int(duration * target_cps)
    for index in range(count + 1):
        manager.record_attack("player", index * interval)
    return manager.snapshot("player", count * interval).current_cps


@pytest.mark.parametrize("rate", [5.0, 10.0, 16.0, 16.1, 17.0, 20.0])
def test_rolling_timestamp_rate(rate: float) -> None:
    assert measure_steady_rate(rate) == pytest.approx(rate, abs=0.02)


def test_empty_and_insufficient_attack_history_is_zero() -> None:
    manager = CPSManager(CPSSettings())
    assert manager.snapshot("player", 0.0).current_cps == 0.0
    assert manager.record_attack("player", 0.0)
    assert manager.snapshot("player", 0.0).current_cps == 0.0
    assert manager.record_attack("player", 0.05)
    assert manager.snapshot("player", 0.05).current_cps == 0.0


def test_duplicate_or_non_monotonic_timestamps_are_ignored() -> None:
    manager = CPSManager(CPSSettings())
    assert manager.record_attack("player", 1.0)
    assert not manager.record_attack("player", 1.0)
    assert not manager.record_attack("player", 0.9)
    assert manager.record_attack("player", 1.1)
    state = manager._states["player"]
    assert list(state.timestamps) == [1.0, 1.1]


def test_history_is_bounded_for_very_fast_input() -> None:
    manager = CPSManager(CPSSettings(window_seconds=1.0, max_measurement_cps=80.0))
    for index in range(10_000):
        manager.record_attack("player", index / 1000.0)
    assert len(manager._states["player"].timestamps) <= manager.history_capacity
    assert manager.history_capacity == 82
