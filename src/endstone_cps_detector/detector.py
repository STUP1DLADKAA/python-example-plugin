"""Normalize only high-confidence Bedrock attack events into CPS samples.

This layer intentionally ignores generic arm animations, right-click events,
block interactions, projectile damage and environmental damage.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .models import AttackSource

# Endstone maps melee damage to ``entity_attack``. A direct player mace impact
# has its own Bedrock cause, ``mace_smash``; other causes are deliberately not
# treated as a CPS click.
_MELEE_DAMAGE_TYPES = frozenset({"entity_attack", "mace_smash"})
_DUPLICATE_EVENT_WINDOW_SECONDS = 0.005


class AttackDetector:
    """Convert official Endstone events into one normalized attack callback.

    Air misses come only from ``PlayerInteractEvent.Action.LEFT_CLICK_AIR``
    (Endstone maps Bedrock's ``MissedSwing`` input bit to this action). Entity
    hits come only from a direct player ``ActorDamageEvent`` with a melee
    damage cause. ``PlayerArmSwingEvent`` is intentionally not accepted: it
    does not distinguish an attack from a generic swing.
    """

    def __init__(
        self,
        on_attack: Callable[[Any, AttackSource, float], None],
        *,
        is_player: Callable[[object], bool],
        clock: Callable[[], float] = time.monotonic,
        duplicate_window_seconds: float = _DUPLICATE_EVENT_WINDOW_SECONDS,
    ) -> None:
        self._on_attack = on_attack
        self._is_player = is_player
        self._clock = clock
        self._duplicate_window_seconds = max(0.0, duplicate_window_seconds)
        self._last_attack_at: dict[str, float] = {}

    @staticmethod
    def classify_interaction(action: object) -> AttackSource | None:
        """Return AIR_MISS only for Endstone's explicit left-click-air action."""
        if getattr(action, "name", None) == "LEFT_CLICK_AIR":
            return AttackSource.AIR_MISS
        return None

    @staticmethod
    def classify_damage_source(
        damage_source: object,
        *,
        is_player: Callable[[object], bool],
    ) -> tuple[object, AttackSource] | None:
        """Accept direct melee hurt from a player; reject indirect/projectiles."""
        try:
            damage_type = getattr(damage_source, "type")
            is_indirect = getattr(damage_source, "is_indirect")
            attacker = getattr(damage_source, "damaging_actor")
        except (AttributeError, RuntimeError, TypeError):
            return None
        if damage_type not in _MELEE_DAMAGE_TYPES or is_indirect or not is_player(attacker):
            return None
        return attacker, AttackSource.ENTITY_HIT

    def on_interaction(self, player: object, action: object) -> bool:
        """Handle a PlayerInteractEvent without treating block/right clicks as attacks."""
        source = self.classify_interaction(action)
        return self._emit(player, source) if source is not None else False

    def on_damage(self, damage_source: object) -> bool:
        """Handle an ActorDamageEvent's source, if it is a direct player melee hit."""
        classified = self.classify_damage_source(damage_source, is_player=self._is_player)
        if classified is None:
            return False
        player, source = classified
        return self._emit(player, source)

    def remove_player(self, player_id: object) -> None:
        """Release duplicate-suppression state when a player leaves."""
        self._last_attack_at.pop(str(player_id), None)

    def clear(self) -> None:
        """Reset duplicate-suppression state on reload."""
        self._last_attack_at.clear()

    def _emit(self, player: object, source: AttackSource) -> bool:
        try:
            key = str(getattr(player, "unique_id"))
            timestamp = float(self._clock())
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return False
        if not key:
            return False
        previous = self._last_attack_at.get(key)
        if previous is not None and timestamp - previous < self._duplicate_window_seconds:
            return False
        if previous is not None and timestamp <= previous:
            return False
        self._last_attack_at[key] = timestamp
        self._on_attack(player, source, timestamp)
        return True
