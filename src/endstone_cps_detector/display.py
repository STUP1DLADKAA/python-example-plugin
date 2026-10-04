"""Low-frequency CPS name-tag suffix updates with compatibility-safe restore."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable

from .config import DisplaySettings


@dataclass(slots=True)
class _NametagState:
    original_name_tag: str
    base_name_tag: str
    last_applied_tag: str | None = None
    last_suffix: str | None = None
    last_display_key: str | None = None
    enabled_for_player: bool = True
    last_update_at: float | None = None


class CPSDisplay:
    """Append a CPS suffix while preserving and tracking the current base tag.

    If another plugin changes the name tag while our suffix is present, that
    new value is adopted as the base on the next refresh. Restores only remove
    the suffix we applied; they do not blindly replace another plugin's tag.
    """

    def __init__(self, settings: DisplaySettings, clock: Callable[[], float] = time.monotonic) -> None:
        self._settings = settings
        self._clock = clock
        self._states: dict[str, _NametagState] = {}

    def configure(self, settings: DisplaySettings) -> None:
        self._settings = settings
        for state in self._states.values():
            state.last_update_at = None
            state.last_display_key = None

    def track(self, player: object, *, now: float | None = None) -> None:
        """Capture a player's original tag on join, without replacing it."""
        try:
            key = self._player_id(player)
            original = str(getattr(player, "name_tag"))
        except (AttributeError, RuntimeError, TypeError):
            return
        self._states.setdefault(key, _NametagState(original_name_tag=original, base_name_tag=original))
        if self._settings.enabled and self._settings.show_zero:
            self.update(player, 0.0, now=now, force=True)

    def update(
        self,
        player: object,
        cps: float,
        *,
        now: float | None = None,
        force: bool = False,
    ) -> bool:
        """Update a player's suffix only when the displayed value needs changing."""
        try:
            key = self._player_id(player)
            current = str(getattr(player, "name_tag"))
        except (AttributeError, RuntimeError, TypeError):
            return False
        state = self._state_for(key, current)
        sampled_at = self._clock() if now is None else now
        if not force and state.last_update_at is not None:
            if sampled_at - state.last_update_at + 1e-6 < self._settings.update_interval_seconds:
                return False
        state.last_update_at = sampled_at

        self._adopt_external_tag(state, current)
        show = self._settings.enabled and state.enabled_for_player and (cps > 0.0 or self._settings.show_zero)
        if not show:
            return self._restore_known_base(player, state, current)

        cps_text = f"{max(0.0, cps):.{self._settings.precision}f}"
        suffix = self._settings.format.format(cps=cps_text)
        if state.last_display_key == suffix and state.last_applied_tag == current:
            return False

        base_for_display = state.base_name_tag or str(getattr(player, "name", ""))
        desired = f"{base_for_display}{suffix}"
        if current != desired:
            try:
                setattr(player, "name_tag", desired)
            except (AttributeError, RuntimeError, TypeError):
                return False
        state.last_applied_tag = desired
        state.last_suffix = suffix
        state.last_display_key = suffix
        return current != desired

    def toggle(self, player: object, cps: float = 0.0, *, now: float | None = None) -> bool:
        """Toggle the player's CPS suffix; return its new visibility state."""
        if not self._settings.enabled:
            return False
        try:
            key = self._player_id(player)
            current = str(getattr(player, "name_tag"))
        except (AttributeError, RuntimeError, TypeError):
            return False
        state = self._state_for(key, current)
        state.enabled_for_player = not state.enabled_for_player
        state.last_update_at = None
        self.update(player, cps, now=now, force=True)
        return state.enabled_for_player

    def restore(self, player: object, *, now: float | None = None) -> bool:
        """Restore the latest adopted base tag, if this instance owns the suffix."""
        try:
            key = self._player_id(player)
            current = str(getattr(player, "name_tag"))
        except (AttributeError, RuntimeError, TypeError):
            return False
        state = self._states.get(key)
        if state is None:
            return False
        state.last_update_at = self._clock() if now is None else now
        self._adopt_external_tag(state, current)
        return self._restore_known_base(player, state, current)

    def restore_all(self, players: Iterable[object]) -> None:
        for player in players:
            self.restore(player)

    def remove_player(self, player_id: object, player: object | None = None) -> None:
        key = str(player_id)
        if player is not None:
            self.restore(player)
        self._states.pop(key, None)

    def clear(self, players: Iterable[object] = ()) -> None:
        """Restore online tags and discard cached session state."""
        self.restore_all(players)
        self._states.clear()

    @staticmethod
    def _player_id(player: object) -> str:
        return str(getattr(player, "unique_id"))

    def _state_for(self, key: str, current_tag: str) -> _NametagState:
        state = self._states.get(key)
        if state is None:
            state = _NametagState(original_name_tag=current_tag, base_name_tag=current_tag)
            self._states[key] = state
        return state

    @staticmethod
    def _adopt_external_tag(state: _NametagState, current: str) -> None:
        if state.last_applied_tag is None:
            if current != state.base_name_tag:
                state.base_name_tag = current
            return
        if current == state.last_applied_tag:
            return

        suffix = state.last_suffix
        if suffix and current.endswith(suffix):
            state.base_name_tag = current[: -len(suffix)]
        else:
            state.base_name_tag = current
        state.last_applied_tag = None
        state.last_suffix = None
        state.last_display_key = None

    @staticmethod
    def _restore_known_base(player: object, state: _NametagState, current: str) -> bool:
        base = state.base_name_tag
        if current != base:
            try:
                setattr(player, "name_tag", base)
            except (AttributeError, RuntimeError, TypeError):
                return False
        state.last_applied_tag = None
        state.last_suffix = None
        state.last_display_key = None
        return current != base
