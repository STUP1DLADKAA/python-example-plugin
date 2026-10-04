from __future__ import annotations

import inspect

from endstone.event import (
    ActorDamageEvent,
    Event,
    PlayerDeathEvent,
    PlayerDimensionChangeEvent,
    PlayerInteractEvent,
    PlayerJoinEvent,
    PlayerQuitEvent,
    PlayerRespawnEvent,
    PlayerTeleportEvent,
)

from endstone_cps_detector.listener import AttackEventListener, PlayerLifecycleListener


def test_listener_handlers_use_concrete_endstone_event_annotations() -> None:
    listeners = (AttackEventListener(object()), PlayerLifecycleListener(object()))
    registered: dict[type[object], set[type[Event]]] = {}

    for listener in listeners:
        event_types: set[type[Event]] = set()
        for name in dir(listener):
            callback = getattr(listener, name)
            if not callable(callback) or not getattr(callback, "_is_event_handler", False):
                continue
            parameters = list(inspect.signature(callback).parameters.values())
            assert len(parameters) == 1
            event_type = parameters[0].annotation
            assert inspect.isclass(event_type)
            assert issubclass(event_type, Event)
            event_types.add(event_type)
        registered[type(listener)] = event_types

    assert registered[AttackEventListener] == {PlayerInteractEvent, ActorDamageEvent}
    assert PlayerInteractEvent.Action.LEFT_CLICK_AIR.name == "LEFT_CLICK_AIR"
    assert registered[PlayerLifecycleListener] == {
        PlayerJoinEvent,
        PlayerQuitEvent,
        PlayerDeathEvent,
        PlayerRespawnEvent,
        PlayerDimensionChangeEvent,
        PlayerTeleportEvent,
    }
