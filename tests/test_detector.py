from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from endstone_cps_detector.detector import AttackDetector
from endstone_cps_detector.models import AttackSource


class Action(Enum):
    LEFT_CLICK_AIR = 1
    LEFT_CLICK_BLOCK = 2
    RIGHT_CLICK_AIR = 3
    RIGHT_CLICK_BLOCK = 4


@dataclass
class FakePlayer:
    unique_id: str
    name: str = "TestPlayer"


@dataclass
class FakeDamageSource:
    type: str
    damaging_actor: object
    is_indirect: bool = False


def test_only_explicit_left_click_air_is_normalized_as_an_air_attack() -> None:
    assert AttackDetector.classify_interaction(Action.LEFT_CLICK_AIR) is AttackSource.AIR_MISS
    assert AttackDetector.classify_interaction(Action.LEFT_CLICK_BLOCK) is None
    assert AttackDetector.classify_interaction(Action.RIGHT_CLICK_AIR) is None
    assert AttackDetector.classify_interaction(Action.RIGHT_CLICK_BLOCK) is None
    assert AttackDetector.classify_interaction(object()) is None


def test_only_direct_player_melee_damage_is_counted_as_entity_hit() -> None:
    player = FakePlayer("player-1")
    def is_player(actor: object) -> bool:
        return isinstance(actor, FakePlayer)

    assert AttackDetector.classify_damage_source(
        FakeDamageSource("entity_attack", player), is_player=is_player
    ) == (player, AttackSource.ENTITY_HIT)
    assert AttackDetector.classify_damage_source(
        FakeDamageSource("mace_smash", player), is_player=is_player
    ) == (player, AttackSource.ENTITY_HIT)
    assert AttackDetector.classify_damage_source(
        FakeDamageSource("projectile", player), is_player=is_player
    ) is None
    assert AttackDetector.classify_damage_source(
        FakeDamageSource("entity_attack", object()), is_player=is_player
    ) is None
    assert AttackDetector.classify_damage_source(
        FakeDamageSource("entity_attack", player, is_indirect=True), is_player=is_player
    ) is None
    assert AttackDetector.classify_damage_source(
        FakeDamageSource("fall", player), is_player=is_player
    ) is None


def test_cross_source_duplicate_guard_is_narrow_and_player_scoped() -> None:
    times = iter([10.0, 10.002, 10.010, 10.011])
    recorded: list[tuple[str, AttackSource, float]] = []
    first = FakePlayer("first")
    second = FakePlayer("second")
    detector = AttackDetector(
        on_attack=lambda player, source, timestamp: recorded.append((player.unique_id, source, timestamp)),
        is_player=lambda actor: isinstance(actor, FakePlayer),
        clock=lambda: next(times),
    )

    assert detector.on_interaction(first, Action.LEFT_CLICK_AIR)
    # Same player, within 5 ms: treated as a duplicate/cross-event observation.
    assert not detector.on_damage(FakeDamageSource("entity_attack", first))
    # Separate player and later input are preserved.
    assert detector.on_interaction(second, Action.LEFT_CLICK_AIR)
    assert detector.on_interaction(first, Action.LEFT_CLICK_AIR)
    assert [entry[1] for entry in recorded] == [
        AttackSource.AIR_MISS,
        AttackSource.AIR_MISS,
        AttackSource.AIR_MISS,
    ]

    detector.remove_player(first.unique_id)
    assert first.unique_id not in detector._last_attack_at
