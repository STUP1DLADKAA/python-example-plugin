"""Administrative and player-facing ``/cps`` command handling."""

from __future__ import annotations

from typing import TYPE_CHECKING

from endstone import Player
from endstone.command import Command, CommandSender

if TYPE_CHECKING:
    from .plugin import CPSTrackerPlugin


class PluginCommandManager:
    """Keep command parsing and permission checks out of the plugin lifecycle."""

    def __init__(self, plugin: CPSTrackerPlugin) -> None:
        self._plugin = plugin

    def execute(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        del command  # The plugin declares only the cps command.
        if not args:
            if isinstance(sender, Player):
                self._send_current(sender, sender)
            else:
                sender.send_message(
                    "Usage: /cps <player> | /cps info <player> | /cps reload | "
                    "/cps reset <player>"
                )
            return True

        subcommand = args[0].casefold()
        if subcommand == "reload" and len(args) == 1:
            return self._reload(sender)
        if subcommand == "toggle" and len(args) == 1:
            return self._toggle(sender)
        if subcommand == "info" and len(args) == 2:
            return self._info(sender, args[1])
        if subcommand == "reset" and len(args) == 2:
            return self._reset(sender, args[1])
        if len(args) == 1:
            return self._view_other(sender, args[0])

        sender.send_error_message(
            "Usage: /cps [player] | /cps info <player> | /cps reload | "
            "/cps toggle | /cps reset <player>"
        )
        return False

    def _send_current(self, sender: CommandSender, target: Player) -> None:
        snapshot = self._plugin.cps_snapshot(target)
        sender.send_message(
            f"§7[CPS] §f{target.name}§7: current §f{snapshot.current_cps:.1f} CPS"
            f"§7, peak §f{snapshot.peak_cps:.1f} CPS§7."
        )

    def _view_other(self, sender: CommandSender, player_name: str) -> bool:
        target = self._find_player(player_name)
        if target is None:
            sender.send_error_message(f"Player {player_name!r} is not online.")
            return False
        if not self._same_player(sender, target) and not sender.has_permission("cps.view"):
            sender.send_error_message("You do not have permission to view another player's CPS.")
            return False
        if not self._staff_visibility_allows(sender, target):
            sender.send_message("§7CPS details for players with bypass are hidden by configuration.")
            return True
        self._send_current(sender, target)
        return True

    def _info(self, sender: CommandSender, player_name: str) -> bool:
        if not sender.has_permission("cps.admin"):
            sender.send_error_message("You do not have permission to view CPS violation details.")
            return False
        target = self._find_player(player_name)
        if target is None:
            sender.send_error_message(f"Player {player_name!r} is not online.")
            return False
        if not self._staff_visibility_allows(sender, target):
            sender.send_message("§7CPS details for players with bypass are hidden by configuration.")
            return True

        snapshot = self._plugin.cps_snapshot(target)
        status = "above limit" if snapshot.above_limit else "normal"
        sender.send_message(
            f"§7[CPS] §f{target.name}§7 — current: §f{snapshot.current_cps:.1f} CPS"
            f"§7; peak: §f{snapshot.peak_cps:.1f} CPS"
            f"§7; above-limit duration: §f{snapshot.violation_seconds:.2f}s"
            f"§7; state: §f{status}§7."
        )
        return True

    def _reload(self, sender: CommandSender) -> bool:
        if not sender.has_permission("cps.reload"):
            sender.send_error_message("You do not have permission to reload CPS Detector.")
            return False
        self._plugin.reload_settings()
        sender.send_message("§a[CPS] Configuration reloaded; CPS history and peaks were reset.")
        return True

    def _toggle(self, sender: CommandSender) -> bool:
        if not isinstance(sender, Player):
            sender.send_error_message("Only a player can toggle their CPS name-tag display.")
            return False
        if not sender.has_permission("cps.toggle"):
            sender.send_error_message("You do not have permission to toggle the CPS display.")
            return False
        if not self._plugin.settings.enabled or not self._plugin.settings.display.enabled:
            sender.send_error_message("The CPS name-tag display is disabled by server configuration.")
            return False

        enabled = self._plugin.toggle_display(sender)
        state = "enabled" if enabled else "disabled"
        sender.send_message(f"§a[CPS] Your name-tag CPS display is now {state}.")
        return True

    def _reset(self, sender: CommandSender, player_name: str) -> bool:
        if not sender.has_permission("cps.admin"):
            sender.send_error_message("You do not have permission to reset CPS history.")
            return False
        target = self._find_player(player_name)
        if target is None:
            sender.send_error_message(f"Player {player_name!r} is not online.")
            return False
        self._plugin.reset_player_cps(target)
        sender.send_message(f"§a[CPS] Reset CPS history and peak for {target.name}.")
        return True

    def _find_player(self, name: str) -> Player | None:
        folded = name.casefold()
        for player in self._plugin.server.online_players:
            if player.name.casefold() == folded:
                return player
        return None

    def _staff_visibility_allows(self, sender: CommandSender, target: Player) -> bool:
        if self._same_player(sender, target):
            return True
        return not (
            self._plugin.is_bypassed(target)
            and not self._plugin.settings.permissions.bypass_visible_to_staff
        )

    @staticmethod
    def _same_player(sender: CommandSender, target: Player) -> bool:
        return isinstance(sender, Player) and str(sender.unique_id) == str(target.unique_id)
