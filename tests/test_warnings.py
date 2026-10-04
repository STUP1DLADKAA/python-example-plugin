from __future__ import annotations

from dataclasses import dataclass, field

from endstone_cps_detector.config import CPSSettings, PermissionSettings, WarningSettings
from endstone_cps_detector.models import CPSSnapshot
from endstone_cps_detector.warnings import WarningManager


@dataclass
class FakeRecipient:
    is_op: bool = False
    permissions: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions

    def send_message(self, message: str) -> None:
        self.messages.append(message)


@dataclass
class FakePlayer:
    name: str = "Clicker"


def test_warning_cooldown_and_staff_only_delivery() -> None:
    operator = FakeRecipient(is_op=True)
    custom_staff = FakeRecipient(permissions={"cps.notify"})
    ordinary = FakeRecipient()
    logs: list[str] = []
    settings = CPSSettings(warning_interval_seconds=2.0)
    manager = WarningManager(
        WarningSettings(),
        settings,
        PermissionSettings(),
        online_players=lambda: (operator, custom_staff, ordinary),
        log_warning=logs.append,
    )
    snapshot = CPSSnapshot(
        "clicker",
        current_cps=17.4,
        peak_cps=18.2,
        above_limit=True,
        violation_seconds=0.4,
        violation_peak_cps=18.2,
    )

    assert manager.maybe_warn(FakePlayer(), snapshot, 1.0, bypassed=False)
    assert not manager.maybe_warn(FakePlayer(), snapshot, 2.5, bypassed=False)
    assert manager.maybe_warn(FakePlayer(), snapshot, 3.0, bypassed=False)
    assert len(operator.messages) == 2
    assert len(custom_staff.messages) == 2
    assert ordinary.messages == []
    assert logs == []
    assert "17.4 CPS" in operator.messages[0]
    assert "18.2 CPS" in operator.messages[0]


def test_hidden_bypass_player_does_not_generate_staff_warning() -> None:
    operator = FakeRecipient(is_op=True)
    manager = WarningManager(
        WarningSettings(),
        CPSSettings(),
        PermissionSettings(bypass_visible_to_staff=False),
        online_players=lambda: (operator,),
        log_warning=lambda _message: None,
    )
    snapshot = CPSSnapshot("bypassed", current_cps=25.0, peak_cps=25.0)
    assert not manager.maybe_warn(FakePlayer(), snapshot, 1.0, bypassed=True)
    assert operator.messages == []
