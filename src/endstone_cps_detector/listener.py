"""Thin Endstone event adapters; gameplay decisions live in service classes.

Do not enable postponed annotations here: Endstone's ``register_events``
inspects each handler's parameter annotation as a concrete event class.
"""

from endstone import Player
from endstone.event import (
    ActorDamageEvent,
    EventPriority,
    PlayerDeathEvent,
    PlayerDimensionChangeEvent,
    PlayerInteractEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerRespawnEvent,
    PlayerTeleportEvent,
    event_handler,
)

from .detector import AttackDetector
from .models import AttackSource


class AttackEventListener:
    """Subscribe only to the two Endstone events used as attack evidence."""

    def __init__(self, plugin: object) -> None:
        self._plugin = plugin
        self.detector = AttackDetector(
            on_attack=self._record_attack,
            is_player=lambda actor: isinstance(actor, Player),
        )

    def _record_attack(self, player: object, source: AttackSource, timestamp: float) -> None:
        callback = getattr(self._plugin, "_record_attack")
        callback(player, source, timestamp)

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=False)
    def on_player_interact(self, event: PlayerInteractEvent) -> None:
        """Count Endstone's explicit LEFT_CLICK_AIR action, never block/right clicks."""
        if getattr(self._plugin, "detection_enabled"):
            self.detector.on_interaction(event.player, event.action)

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=False)
    def on_actor_damage(self, event: ActorDamageEvent) -> None:
        """Count direct melee damage by a player, not projectiles or world damage."""
        if getattr(self._plugin, "detection_enabled"):
            self.detector.on_damage(event.damage_source)

    def remove_player(self, player_id: object) -> None:
        self.detector.remove_player(player_id)

    def clear(self) -> None:
        self.detector.clear()


class PlayerLifecycleListener:
    """Maintain per-session state across joins, leaves and world transitions."""

    def __init__(self, plugin: object) -> None:
        self._plugin = plugin

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_join(self, event: PlayerJoinEvent) -> None:
        getattr(self._plugin, "_on_player_join")(event.player)

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_quit(self, event: PlayerQuitEvent) -> None:
        getattr(self._plugin, "_on_player_quit")(event.player)

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_death(self, event: PlayerDeathEvent) -> None:
        getattr(self._plugin, "_reset_player_activity")(event.player)

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_respawn(self, event: PlayerRespawnEvent) -> None:
        getattr(self._plugin, "_reset_player_activity")(event.player)

    @event_handler(priority=EventPriority.MONITOR)
    def on_player_dimension_change(self, event: PlayerDimensionChangeEvent) -> None:
        getattr(self._plugin, "_reset_player_activity")(event.player)

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=True)
    def on_player_teleport(self, event: PlayerTeleportEvent) -> None:
        getattr(self._plugin, "_reset_player_activity")(event.player)
