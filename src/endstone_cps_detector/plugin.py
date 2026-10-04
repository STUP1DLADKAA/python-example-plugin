"""Endstone plugin lifecycle and main-thread coordination."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.plugin import Plugin

from .commands import PluginCommandManager
from .config import ConfigurationManager, PluginSettings
from .cps_manager import CPSManager
from .display import CPSDisplay
from .listener import AttackEventListener, PlayerLifecycleListener
from .models import AttackSource, CPSSnapshot
from .punishment import PunishmentManager
from .warnings import WarningManager

if TYPE_CHECKING:
    from endstone.scheduler import Task


class CPSTrackerPlugin(Plugin):
    """Detect high-confidence melee/air attack actions and sustained CPS excess."""

    prefix = "CPS"
    api_version = "0.11"

    commands = {
        "cps": {
            "description": "View CPS or administer CPS Detector",
            "usages": [
                "/cps",
                "/cps <player: str>",
                "/cps info <player: str>",
                "/cps reload",
                "/cps toggle",
                "/cps reset <player: str>",
            ],
            "permissions": ["cps.command"],
        },
    }

    permissions = {
        "cps.command": {
            "description": "Allow use of the /cps command.",
            "default": True,
        },
        "cps.view": {
            "description": "Allow viewing another player's current CPS.",
            "default": "op",
        },
        "cps.admin": {
            "description": "Allow CPS administration, detailed inspection, and history reset.",
            "default": "op",
        },
        "cps.reload": {
            "description": "Allow reloading CPS Detector configuration.",
            "default": "op",
        },
        "cps.toggle": {
            "description": "Allow toggling the caller's CPS name-tag suffix.",
            "default": True,
        },
        "cps.notify": {
            "description": "Receive operator-only CPS warnings.",
            "default": "op",
        },
        "cps.bypass": {
            "description": "Skip automatic CPS kicks; tracking remains configurable for staff visibility.",
            "default": False,
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._settings = PluginSettings()
        self._online_players: dict[str, Player] = {}
        self._config_manager = ConfigurationManager(self._log_config_warning)
        self._cps_manager: CPSManager | None = None
        self._display: CPSDisplay | None = None
        self._warnings: WarningManager | None = None
        self._punishment: PunishmentManager | None = None
        self._attack_listener: AttackEventListener | None = None
        self._lifecycle_listener: PlayerLifecycleListener | None = None
        self._command_manager: PluginCommandManager | None = None
        self._task: Task | None = None

    @property
    def settings(self) -> PluginSettings:
        return self._settings

    @property
    def detection_enabled(self) -> bool:
        return self._settings.enabled

    def on_enable(self) -> None:
        self.save_default_config()
        self._settings = self._config_manager.load(self.reload_config())
        self._initialize_services()

        self._attack_listener = AttackEventListener(self)
        self._lifecycle_listener = PlayerLifecycleListener(self)
        self._command_manager = PluginCommandManager(self)
        self.register_events(self._attack_listener)
        self.register_events(self._lifecycle_listener)

        self._track_existing_players()
        self._schedule_processing()
        self.logger.info(
            "[CPS] Plugin enabled. Detection sources: explicit LEFT_CLICK_AIR and direct player melee damage."
        )

    def on_disable(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._display is not None:
            self._display.clear(tuple(self._online_players.values()))
        if self._cps_manager is not None:
            self._cps_manager.clear()
        if self._warnings is not None:
            self._warnings.clear()
        if self._punishment is not None:
            self._punishment.clear()
        if self._attack_listener is not None:
            self._attack_listener.clear()
        self._online_players.clear()
        self.logger.info("[CPS] Plugin disabled; cached CPS state was cleared and name tags restored where possible.")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if self._command_manager is None:
            sender.send_error_message("CPS Detector is still starting.")
            return False
        return self._command_manager.execute(sender, command, args)

    def reload_settings(self) -> None:
        """Reload TOML settings, reset per-session measurements, and reschedule."""
        self._settings = self._config_manager.load(self.reload_config())
        if self._cps_manager is None:
            self._initialize_services()
        else:
            self._cps_manager.configure(self._settings.cps)
            self._display.configure(self._settings.display)
            self._warnings.configure(
                self._settings.warnings,
                self._settings.cps,
                self._settings.permissions,
            )
            self._punishment.configure(self._settings.punishment, self._settings.cps.violation_seconds)
            if self._attack_listener is not None:
                self._attack_listener.clear()

        if not self._settings.enabled or not self._settings.display.enabled:
            self._display.restore_all(tuple(self._online_players.values()))
        else:
            for player in tuple(self._online_players.values()):
                self._display.track(player)
                self._display.update(player, 0.0, force=True)

        self._schedule_processing()
        self.logger.info("[CPS] Configuration loaded; per-session CPS history and peaks were reset.")

    def cps_snapshot(self, player: Player) -> CPSSnapshot:
        player_id = str(player.unique_id)
        if self._cps_manager is None:
            return CPSSnapshot(player_id=player_id)
        return self._cps_manager.snapshot(player_id)

    def is_bypassed(self, player: Player) -> bool:
        try:
            return bool(player.has_permission("cps.bypass"))
        except (AttributeError, RuntimeError, TypeError):
            # A permission-query failure must not turn into an automatic kick.
            return True

    def toggle_display(self, player: Player) -> bool:
        if self._display is None:
            return False
        snapshot = self.cps_snapshot(player)
        return self._display.toggle(player, snapshot.current_cps)

    def reset_player_cps(self, player: Player) -> None:
        player_id = str(player.unique_id)
        if self._cps_manager is not None:
            self._cps_manager.reset_player(player_id)
        if self._warnings is not None:
            self._warnings.clear_player(player_id)
        if self._punishment is not None:
            self._punishment.clear_player(player_id)
        if self._attack_listener is not None:
            self._attack_listener.remove_player(player_id)
        if self._display is not None:
            self._display.update(player, 0.0, force=True)

    def _initialize_services(self) -> None:
        self._cps_manager = CPSManager(self._settings.cps)
        self._display = CPSDisplay(self._settings.display)
        self._warnings = WarningManager(
            self._settings.warnings,
            self._settings.cps,
            self._settings.permissions,
            online_players=self._get_online_players,
            log_warning=self._log_warning,
        )
        self._punishment = PunishmentManager(self._settings.punishment, self._settings.cps.violation_seconds)

    def _track_existing_players(self) -> None:
        try:
            players = tuple(self.server.online_players)
        except (AttributeError, RuntimeError, TypeError):
            players = ()
        for player in players:
            self._on_player_join(player)

    def _on_player_join(self, player: Player) -> None:
        try:
            player_id = str(player.unique_id)
        except (AttributeError, RuntimeError, TypeError):
            return
        self._online_players[player_id] = player
        if self._cps_manager is not None:
            self._cps_manager.track_player(player_id)
        if self._display is not None:
            self._display.track(player)
            if not self._settings.enabled or not self._settings.display.enabled:
                self._display.restore(player)

    def _on_player_quit(self, player: Player) -> None:
        player_id = self._safe_player_id(player)
        if player_id is None:
            return
        self._online_players.pop(player_id, None)
        if self._display is not None:
            self._display.remove_player(player_id, player)
        if self._cps_manager is not None:
            self._cps_manager.remove_player(player_id)
        if self._warnings is not None:
            self._warnings.clear_player(player_id)
        if self._punishment is not None:
            self._punishment.clear_player(player_id)
        if self._attack_listener is not None:
            self._attack_listener.remove_player(player_id)

    def _reset_player_activity(self, player: Player) -> None:
        """Drop transient samples on death, respawn, teleport or dimension change."""
        player_id = self._safe_player_id(player)
        if player_id is None:
            return
        if self._cps_manager is not None:
            self._cps_manager.reset_player(player_id, reset_peak=False)
        if self._warnings is not None:
            self._warnings.clear_player(player_id)
        if self._punishment is not None:
            self._punishment.clear_player(player_id)
        if self._attack_listener is not None:
            self._attack_listener.remove_player(player_id)
        if self._display is not None:
            self._display.update(player, 0.0, force=True)

    def _record_attack(self, player: object, source: AttackSource, timestamp: float) -> None:
        del source  # Kept in the normalized interface for logging/extension points.
        if not self._settings.enabled or self._cps_manager is None:
            return
        try:
            if not bool(getattr(player, "is_valid")):
                return
            player_id = str(getattr(player, "unique_id"))
        except (AttributeError, RuntimeError, TypeError):
            return
        if player_id not in self._online_players:
            # Covers an attack arriving during the join-event hand-off.
            self._online_players[player_id] = player  # type: ignore[assignment]
            self._cps_manager.track_player(player_id)
        self._cps_manager.record_attack(player_id, timestamp)

    def _process_tick(self) -> None:
        """Run synchronously from Endstone's server scheduler (main thread)."""
        if not self._settings.enabled or self._cps_manager is None:
            return
        now = time.monotonic()
        for snapshot in self._cps_manager.active_snapshots(now):
            player = self._online_players.get(snapshot.player_id)
            if player is None or not self._player_is_valid(player):
                if player is not None:
                    self._on_player_quit(player)
                else:
                    self._cps_manager.remove_player(snapshot.player_id)
                continue

            if self._display is not None and self._settings.display.enabled:
                self._display.update(player, snapshot.current_cps, now=now)

            bypassed = self.is_bypassed(player)
            if self._warnings is not None:
                self._warnings.maybe_warn(player, snapshot, now, bypassed=bypassed)

            if self._punishment is not None and self._punishment.should_kick(snapshot, bypassed=bypassed):
                self._kick_if_online(player, snapshot, bypassed=bypassed)

    def _kick_if_online(self, player: Player, snapshot: CPSSnapshot, *, bypassed: bool) -> None:
        player_id = snapshot.player_id
        if not self._is_currently_online(player_id, player):
            self._on_player_quit(player)
            return

        if self._punishment is None:
            return
        self._punishment.mark_attempted(player_id)
        if self._warnings is not None:
            self._warnings.notify_kick(player, snapshot, bypassed=bypassed)
        try:
            player.kick(self._punishment.kick_reason)
        except Exception as exc:
            # A late disconnect or another Endstone runtime error is not fatal
            # to the scheduler; the single attempt remains rate-limited.
            self.logger.warning(f"[CPS] Could not safely kick {player.name}: {exc}")
            return
        if self._punishment.console_logging:
            self.logger.warning(
                f"[CPS] {player.name} was kicked after a sustained violation "
                f"({snapshot.current_cps:.1f} CPS for {snapshot.violation_seconds:.2f}s)."
            )

    def _is_currently_online(self, player_id: str, player: Player) -> bool:
        if not self._player_is_valid(player) or self._online_players.get(player_id) is None:
            return False
        try:
            return any(str(candidate.unique_id) == player_id for candidate in self.server.online_players)
        except (AttributeError, RuntimeError, TypeError):
            # If Endstone cannot enumerate the list at this point, fail closed.
            return False

    @staticmethod
    def _player_is_valid(player: Player) -> bool:
        try:
            return bool(player.is_valid)
        except (AttributeError, RuntimeError, TypeError):
            return False

    def _schedule_processing(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if not self._settings.enabled:
            return
        if not (
            self._settings.display.enabled
            or self._settings.warnings.enabled
            or self._settings.punishment.enabled
        ):
            return

        interval = min(
            self._settings.cps.processing_interval_seconds,
            self._settings.cps.lag_reset_gap_seconds / 2.0,
        )
        if self._settings.display.enabled:
            interval = min(interval, self._settings.display.update_interval_seconds)
        period_ticks = max(1, round(interval * 20.0))
        self._task = self.server.scheduler.run_task(
            self,
            self._process_tick,
            delay=period_ticks,
            period=period_ticks,
        )

    def _get_online_players(self) -> tuple[Player, ...]:
        try:
            return tuple(self.server.online_players)
        except (AttributeError, RuntimeError, TypeError):
            return tuple(self._online_players.values())

    def _log_config_warning(self, message: str) -> None:
        self.logger.warning(f"[CPS] {message}")

    def _log_warning(self, message: str) -> None:
        self.logger.warning(message)

    @staticmethod
    def _safe_player_id(player: object) -> str | None:
        try:
            return str(getattr(player, "unique_id"))
        except (AttributeError, RuntimeError, TypeError):
            return None
