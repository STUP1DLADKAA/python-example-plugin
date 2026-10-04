"""Conservative kick-only decision logic."""

from __future__ import annotations

from .config import PunishmentSettings
from .models import CPSSnapshot


class PunishmentManager:
    """Apply a kick only after one continuous over-limit interval."""

    def __init__(self, settings: PunishmentSettings, violation_seconds: float) -> None:
        self._settings = settings
        self._violation_seconds = violation_seconds
        self._handled_players: set[str] = set()

    def configure(self, settings: PunishmentSettings, violation_seconds: float) -> None:
        self._settings = settings
        self._violation_seconds = violation_seconds
        self._handled_players.clear()

    def should_kick(self, snapshot: CPSSnapshot, *, bypassed: bool) -> bool:
        """Return whether this snapshot qualifies for one kick attempt."""
        return (
            self._settings.enabled
            and self._settings.kick
            and not bypassed
            and snapshot.player_id not in self._handled_players
            and snapshot.above_limit
            and snapshot.violation_seconds + 1e-6 >= self._violation_seconds
        )

    @property
    def kick_reason(self) -> str:
        return self._settings.kick_reason

    @property
    def console_logging(self) -> bool:
        return self._settings.console_logging

    def mark_attempted(self, player_id: object) -> None:
        """Prevent repeated kick calls if a server-side kick raises or is delayed."""
        self._handled_players.add(str(player_id))

    def clear_player(self, player_id: object) -> None:
        self._handled_players.discard(str(player_id))

    def clear(self) -> None:
        self._handled_players.clear()
