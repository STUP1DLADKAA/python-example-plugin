"""Small domain models shared by the detector services."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class AttackSource(str, Enum):
    """An Endstone event that has been normalized to an attack observation."""

    AIR_MISS = "air_miss"
    ENTITY_HIT = "entity_hit"


@dataclass(frozen=True, slots=True)
class CPSSnapshot:
    """Immutable view of a player's recent attack rate and violation timer."""

    player_id: str
    current_cps: float = 0.0
    peak_cps: float = 0.0
    above_limit: bool = False
    violation_seconds: float = 0.0
    violation_peak_cps: float = 0.0

    @property
    def violation_active(self) -> bool:
        return self.above_limit and self.violation_seconds >= 0.0

    @property
    def highest_relevant_cps(self) -> float:
        """Peak in the active violation, or the session peak outside a violation."""
        return self.violation_peak_cps if self.above_limit else self.peak_cps


@dataclass(slots=True)
class PlayerCPSState:
    """Bounded mutable state retained only while the player is online."""

    timestamps: deque[float] = field(default_factory=deque)
    current_cps: float = 0.0
    peak_cps: float = 0.0
    violation_started_at: float | None = None
    violation_peak_cps: float = 0.0
    last_attack_at: float | None = None
    last_evaluated_at: float | None = None
