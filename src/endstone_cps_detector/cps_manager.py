"""Timestamp-based CPS measurement and sustained-threshold state machine."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Iterable
from math import ceil
from typing import Callable

from .config import CPSSettings
from .models import CPSSnapshot, PlayerCPSState

_FLOAT_EPSILON = 1e-6
_MIN_SAMPLE_EVENTS = 3
_MIN_SAMPLE_SPAN_SECONDS = 0.25


class CPSManager:
    """Keeps a bounded rolling timestamp buffer for each online player.

    The rate is estimated from actual intervals between at least three attack
    timestamps in the configured window. A lone click is never extrapolated
    into a CPS value. Only players with recent attack activity are polled.
    """

    def __init__(self, settings: CPSSettings, clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        self._clock = clock
        self._states: dict[str, PlayerCPSState] = {}
        self._active: set[str] = set()
        self._history_capacity = self._capacity_for(settings)

    @staticmethod
    def _capacity_for(settings: CPSSettings) -> int:
        return max(4, ceil(settings.max_measurement_cps * settings.window_seconds) + 2)

    @property
    def history_capacity(self) -> int:
        """Maximum timestamp count held for one player."""
        return self._history_capacity

    def configure(self, settings: CPSSettings) -> None:
        """Apply settings and reset per-session measurements and peaks."""
        player_ids = tuple(self._states)
        self.settings = settings
        self._history_capacity = self._capacity_for(settings)
        self._states = {player_id: self._new_state() for player_id in player_ids}
        self._active.clear()

    def track_player(self, player_id: object) -> None:
        """Create empty bounded state for a newly joined player."""
        key = str(player_id)
        if key not in self._states:
            self._states[key] = self._new_state()

    def record_attack(self, player_id: object, timestamp: float | None = None) -> bool:
        """Record one normalized attack timestamp; return False for duplicates.

        Endstone does not attach packet sequence numbers to the high-level
        events. Identical/non-monotonic timestamps are therefore discarded as
        duplicates instead of being counted twice.
        """
        key = str(player_id)
        now = self._clock() if timestamp is None else float(timestamp)
        if not math.isfinite(now):
            return False

        state = self._states.get(key)
        if state is None:
            state = self._new_state()
            self._states[key] = state
        if state.last_attack_at is not None:
            if now <= state.last_attack_at:
                return False
            if now - state.last_attack_at > self.settings.idle_timeout_seconds:
                self._clear_burst(state, now)

        state.timestamps.append(now)
        state.last_attack_at = now
        self._active.add(key)
        self._evaluate(key, state, now)
        return True

    def snapshot(self, player_id: object, now: float | None = None) -> CPSSnapshot:
        """Return the latest view, expiring old events as needed."""
        key = str(player_id)
        state = self._states.get(key)
        if state is None:
            return CPSSnapshot(player_id=key)
        sampled_at = self._clock() if now is None else float(now)
        if math.isfinite(sampled_at):
            return self._evaluate(key, state, sampled_at)
        return self._snapshot_from_state(key, state, state.last_evaluated_at or 0.0)

    def active_snapshots(self, now: float | None = None) -> list[CPSSnapshot]:
        """Evaluate only players with recent clicks or an active violation."""
        sampled_at = self._clock() if now is None else float(now)
        if not math.isfinite(sampled_at):
            return []
        snapshots: list[CPSSnapshot] = []
        for key in tuple(self._active):
            state = self._states.get(key)
            if state is not None:
                snapshots.append(self._evaluate(key, state, sampled_at))
        return snapshots

    def reset_player(self, player_id: object, *, reset_peak: bool = True) -> bool:
        """Clear an online player's attack window and violation state."""
        key = str(player_id)
        state = self._states.get(key)
        if state is None:
            return False
        self._reset_state(state, reset_peak=reset_peak)
        self._active.discard(key)
        return True

    def reset_all(self, *, reset_peak: bool = True) -> None:
        """Reset all retained player sessions, used for config reloads."""
        for state in self._states.values():
            self._reset_state(state, reset_peak=reset_peak)
        self._active.clear()

    def remove_player(self, player_id: object) -> None:
        """Immediately release all click and violation state for a leaver."""
        key = str(player_id)
        self._active.discard(key)
        self._states.pop(key, None)

    def clear(self) -> None:
        """Release all player state when the plugin is disabled."""
        self._active.clear()
        self._states.clear()

    def tracked_player_ids(self) -> Iterable[str]:
        return self._states.keys()

    def _new_state(self) -> PlayerCPSState:
        return PlayerCPSState(timestamps=deque(maxlen=self._history_capacity))

    def _evaluate(self, key: str, state: PlayerCPSState, now: float) -> CPSSnapshot:
        if state.last_evaluated_at is not None and now < state.last_evaluated_at:
            # A monotonic clock should not move backwards. Do not let a bad
            # caller value preserve or lengthen a violation.
            now = state.last_evaluated_at

        long_gap = (
            state.last_evaluated_at is not None
            and now - state.last_evaluated_at > self.settings.lag_reset_gap_seconds
        )
        if state.last_attack_at is not None and now - state.last_attack_at > self.settings.idle_timeout_seconds:
            self._clear_burst(state, now)
        else:
            cutoff = now - self.settings.window_seconds
            while state.timestamps and state.timestamps[0] <= cutoff:
                state.timestamps.popleft()

        cps = self._calculate_cps(state.timestamps)
        state.current_cps = cps
        if cps > state.peak_cps:
            state.peak_cps = cps

        over_limit = cps > self.settings.limit + _FLOAT_EPSILON
        if not over_limit:
            state.violation_started_at = None
            state.violation_peak_cps = 0.0
        elif long_gap or state.violation_started_at is None:
            # Do not credit time for which the server was not sampling. Keep
            # measuring the player, but restart the continuous-duration clock.
            state.violation_started_at = now
            state.violation_peak_cps = cps
        elif cps > state.violation_peak_cps:
            state.violation_peak_cps = cps

        state.last_evaluated_at = now
        if state.timestamps or state.violation_started_at is not None:
            self._active.add(key)
        else:
            self._active.discard(key)
        return self._snapshot_from_state(key, state, now)

    def _calculate_cps(self, timestamps: deque[float]) -> float:
        if len(timestamps) < _MIN_SAMPLE_EVENTS:
            return 0.0
        elapsed = timestamps[-1] - timestamps[0]
        minimum_span = min(_MIN_SAMPLE_SPAN_SECONDS, self.settings.window_seconds * 0.5)
        if elapsed < minimum_span or elapsed <= 0.0:
            return 0.0
        raw_cps = (len(timestamps) - 1) / elapsed
        if not math.isfinite(raw_cps) or raw_cps <= 0.0:
            return 0.0
        return min(raw_cps, self.settings.max_measurement_cps)

    @staticmethod
    def _snapshot_from_state(key: str, state: PlayerCPSState, now: float) -> CPSSnapshot:
        started_at = state.violation_started_at
        violation_seconds = max(0.0, now - started_at) if started_at is not None else 0.0
        return CPSSnapshot(
            player_id=key,
            current_cps=state.current_cps,
            peak_cps=state.peak_cps,
            above_limit=started_at is not None,
            violation_seconds=violation_seconds,
            violation_peak_cps=state.violation_peak_cps,
        )

    @staticmethod
    def _clear_burst(state: PlayerCPSState, now: float) -> None:
        state.timestamps.clear()
        state.current_cps = 0.0
        state.violation_started_at = None
        state.violation_peak_cps = 0.0
        state.last_attack_at = None
        state.last_evaluated_at = now

    @staticmethod
    def _reset_state(state: PlayerCPSState, *, reset_peak: bool) -> None:
        state.timestamps.clear()
        state.current_cps = 0.0
        state.violation_started_at = None
        state.violation_peak_cps = 0.0
        state.last_attack_at = None
        state.last_evaluated_at = None
        if reset_peak:
            state.peak_cps = 0.0
