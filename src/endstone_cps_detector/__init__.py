"""Endstone CPS Detector package.

The plugin entry point is loaded lazily so the pure calculation modules can
also be imported by unit tests without a running Endstone server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .plugin import CPSTrackerPlugin

__all__ = ["CPSTrackerPlugin"]


def __getattr__(name: str) -> Any:
    if name == "CPSTrackerPlugin":
        from .plugin import CPSTrackerPlugin

        return CPSTrackerPlugin
    raise AttributeError(name)
