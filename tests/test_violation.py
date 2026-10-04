from __future__ import annotations

from endstone_cps_detector.config import CPSSettings, PunishmentSettings
from endstone_cps_detector.cps_manager import CPSManager
from endstone_cps_detector.punishment import PunishmentManager


def feed(manager: CPSManager, player_id: str, cps: float, start: float, duration: float) -> float:
    interval = 1.0 / cps
    count = int(duration * cps)
    for index in range(count + 1):
        manager.record_attack(player_id, start + index * interval)
    return start + count * interval


def test_brief_spike_does_not_kick_and_recovers() -> None:
    settings = CPSSettings(limit=16.0, violation_seconds=1.25)
    manager = CPSManager(settings)
    punishment = PunishmentManager(PunishmentSettings(), settings.violation_seconds)

    last_attack = feed(manager, "player", 17.0, 0.0, 0.8)
    kicked = False
    for step in range(1, 20):
        snapshot = manager.snapshot("player", last_attack + step * 0.05)
        kicked = kicked or punishment.should_kick(snapshot, bypassed=False)
    assert not kicked
    assert not manager.snapshot("player", last_attack + 0.5).above_limit


def test_sustained_rate_crossing_violation_duration_qualifies_for_kick() -> None:
    settings = CPSSettings(limit=16.0, violation_seconds=1.25)
    manager = CPSManager(settings)
    punishment = PunishmentManager(PunishmentSettings(), settings.violation_seconds)

    current = feed(manager, "player", 17.0, 0.0, 1.7)
    snapshot = manager.snapshot("player", current)
    assert snapshot.current_cps > 16.0
    assert snapshot.above_limit
    assert snapshot.violation_seconds >= settings.violation_seconds
    assert punishment.should_kick(snapshot, bypassed=False)


def test_bypass_never_auto_kicks() -> None:
    settings = CPSSettings(limit=16.0, violation_seconds=1.25)
    manager = CPSManager(settings)
    punishment = PunishmentManager(PunishmentSettings(), settings.violation_seconds)
    current = feed(manager, "player", 20.0, 0.0, 1.8)
    snapshot = manager.snapshot("player", current)
    assert snapshot.above_limit
    assert not punishment.should_kick(snapshot, bypassed=True)


def test_kick_setting_and_one_attempt_guard_are_respected() -> None:
    settings = CPSSettings(limit=16.0, violation_seconds=0.25)
    manager = CPSManager(settings)
    current = feed(manager, "player", 20.0, 0.0, 0.7)
    snapshot = manager.snapshot("player", current)

    disabled = PunishmentManager(PunishmentSettings(kick=False), settings.violation_seconds)
    assert not disabled.should_kick(snapshot, bypassed=False)

    punishment = PunishmentManager(PunishmentSettings(), settings.violation_seconds)
    assert punishment.should_kick(snapshot, bypassed=False)
    punishment.mark_attempted("player")
    assert not punishment.should_kick(snapshot, bypassed=False)
    punishment.clear_player("player")
    assert punishment.should_kick(snapshot, bypassed=False)


def test_falling_below_limit_resets_continuous_violation_timer() -> None:
    settings = CPSSettings(limit=16.0, violation_seconds=1.25)
    manager = CPSManager(settings)
    current = feed(manager, "player", 17.0, 0.0, 0.7)
    current = feed(manager, "player", 10.0, current + 0.02, 1.8)
    snapshot = manager.snapshot("player", current)
    assert snapshot.current_cps <= 16.0
    assert not snapshot.above_limit
    assert snapshot.violation_seconds == 0.0


def test_unobserved_lag_gap_restarts_violation_duration() -> None:
    settings = CPSSettings(
        limit=16.0,
        window_seconds=5.0,
        idle_timeout_seconds=2.0,
        lag_reset_gap_seconds=0.75,
    )
    manager = CPSManager(settings)
    current = feed(manager, "player", 17.0, 0.0, 1.0)
    before_gap = manager.snapshot("player", current)
    assert before_gap.above_limit
    assert before_gap.violation_seconds > 0.0

    after_gap = manager.snapshot("player", current + 1.0)
    assert after_gap.above_limit
    assert after_gap.violation_seconds == 0.0


def test_disconnect_cleans_history_violation_and_peak() -> None:
    manager = CPSManager(CPSSettings())
    current = feed(manager, "player", 20.0, 0.0, 0.8)
    assert manager.snapshot("player", current).peak_cps > 0.0
    manager.remove_player("player")
    snapshot = manager.snapshot("player", current + 0.1)
    assert snapshot.current_cps == 0.0
    assert snapshot.peak_cps == 0.0
    assert not snapshot.above_limit
    assert "player" not in manager.tracked_player_ids()


def test_clear_releases_all_player_state() -> None:
    manager = CPSManager(CPSSettings())
    feed(manager, "first", 10.0, 0.0, 0.8)
    feed(manager, "second", 12.0, 0.0, 0.8)
    manager.clear()
    assert list(manager.tracked_player_ids()) == []
    assert manager.active_snapshots(1.0) == []


def test_reset_can_preserve_session_peak_when_needed() -> None:
    manager = CPSManager(CPSSettings())
    current = feed(manager, "player", 10.0, 0.0, 0.8)
    peak = manager.snapshot("player", current).peak_cps
    assert peak > 0.0
    assert manager.reset_player("player", reset_peak=False)
    snapshot = manager.snapshot("player", current + 0.01)
    assert snapshot.current_cps == 0.0
    assert snapshot.peak_cps == peak
    assert not snapshot.above_limit
