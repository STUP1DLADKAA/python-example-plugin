from __future__ import annotations

from dataclasses import dataclass

from endstone_cps_detector.config import DisplaySettings
from endstone_cps_detector.display import CPSDisplay


@dataclass
class FakePlayer:
    unique_id: str = "uuid-1"
    name: str = "Steve"
    name_tag: str = "Steve"


def test_display_appends_suffix_and_restores_latest_external_base() -> None:
    player = FakePlayer()
    display = CPSDisplay(DisplaySettings())
    display.track(player)

    assert display.update(player, 12.0, now=1.0)
    assert player.name_tag == "Steve §7[§f12 CPS§7]"
    assert not display.update(player, 12.0, now=1.1)

    # A different plugin's tag is adopted instead of being overwritten with
    # the initially captured name on cleanup.
    player.name_tag = "Staff Steve"
    assert display.update(player, 13.0, now=1.2)
    assert player.name_tag == "Staff Steve §7[§f13 CPS§7]"
    assert display.restore(player, now=1.4)
    assert player.name_tag == "Staff Steve"


def test_restore_strips_only_the_known_suffix_after_external_edit() -> None:
    player = FakePlayer()
    display = CPSDisplay(DisplaySettings())
    display.track(player)
    display.update(player, 8.0, now=1.0)
    player.name_tag = "Moderator §7[§f8 CPS§7]"

    display.update(player, 0.0, now=1.2, force=True)
    assert player.name_tag == "Moderator"


def test_show_zero_and_personal_toggle() -> None:
    player = FakePlayer()
    display = CPSDisplay(DisplaySettings(show_zero=True))
    display.track(player, now=1.0)
    assert player.name_tag == "Steve §7[§f0 CPS§7]"

    assert not display.toggle(player, 0.0, now=1.2)
    assert player.name_tag == "Steve"
    assert display.toggle(player, 0.0, now=1.4)
    assert player.name_tag == "Steve §7[§f0 CPS§7]"
