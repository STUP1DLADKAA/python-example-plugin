"""Rate-limited operator warnings for sustained high CPS."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .config import CPSSettings, PermissionSettings, WarningSettings
from .models import CPSSnapshot


class WarningManager:
    """Send staff-only warnings, with a per-player cooldown."""

    def __init__(
        self,
        warning_settings: WarningSettings,
        cps_settings: CPSSettings,
        permission_settings: PermissionSettings,
        *,
        online_players: Callable[[], Iterable[object]],
        log_warning: Callable[[str], None],
    ) -> None:
        self._warning_settings = warning_settings
        self._cps_settings = cps_settings
        self._permission_settings = permission_settings
        self._online_players = online_players
        self._log_warning = log_warning
        self._last_warning_at: dict[str, float] = {}

    def configure(
        self,
        warning_settings: WarningSettings,
        cps_settings: CPSSettings,
        permission_settings: PermissionSettings,
    ) -> None:
        self._warning_settings = warning_settings
        self._cps_settings = cps_settings
        self._permission_settings = permission_settings
        self._last_warning_at.clear()

    def maybe_warn(self, player: object, snapshot: CPSSnapshot, now: float, *, bypassed: bool) -> bool:
        """Warn if the configured threshold is still exceeded and cooldown elapsed."""
        if not self._warning_settings.enabled:
            return False
        if bypassed and not self._permission_settings.bypass_visible_to_staff:
            return False
        if snapshot.current_cps <= self._cps_settings.warning_threshold + 1e-6:
            return False

        player_id = snapshot.player_id
        previous = self._last_warning_at.get(player_id)
        if previous is not None and now - previous < self._cps_settings.warning_interval_seconds:
            return False

        name = str(getattr(player, "name", "Unknown"))
        peak = snapshot.highest_relevant_cps
        message = (
            f"§c[CPS] §f{name} §7is clicking at §c{snapshot.current_cps:.1f} CPS"
            f"§7 (highest: §c{peak:.1f} CPS§7)"
        )
        if snapshot.above_limit:
            message += f" and has been above the limit for §c{snapshot.violation_seconds:.1f}s§7"
        message += "."

        self._send_to_staff(message)
        if self._warning_settings.console_logging:
            self._log_warning(
                f"[CPS] {name} is at {snapshot.current_cps:.1f} CPS (highest: {peak:.1f} CPS)."
            )
        self._last_warning_at[player_id] = now
        return True

    def notify_kick(self, player: object, snapshot: CPSSnapshot, *, bypassed: bool = False) -> None:
        """Send a one-time staff notification immediately before a kick."""
        if not self._warning_settings.enabled:
            return
        if bypassed and not self._permission_settings.bypass_visible_to_staff:
            return
        name = str(getattr(player, "name", "Unknown"))
        message = (
            f"§c[CPS] §f{name} §7is being kicked for sustained high CPS "
            f"§c({snapshot.current_cps:.1f} CPS)§7."
        )
        self._send_to_staff(message)
        if self._warning_settings.console_logging:
            self._log_warning(f"[CPS] {name} was kicked for sustained high CPS ({snapshot.current_cps:.1f} CPS).")

    def clear_player(self, player_id: object) -> None:
        self._last_warning_at.pop(str(player_id), None)

    def clear(self) -> None:
        self._last_warning_at.clear()

    def _send_to_staff(self, message: str) -> None:
        for recipient in self._online_players():
            if not self._is_staff(recipient):
                continue
            try:
                recipient.send_message(message)
            except (AttributeError, RuntimeError, TypeError):
                # A recipient may have disconnected between enumeration and send.
                continue

    @staticmethod
    def _is_staff(recipient: object) -> bool:
        try:
            if bool(getattr(recipient, "is_op")):
                return True
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            has_permission = getattr(recipient, "has_permission")
            return bool(has_permission("cps.notify") or has_permission("cps.admin"))
        except (AttributeError, RuntimeError, TypeError):
            return False
