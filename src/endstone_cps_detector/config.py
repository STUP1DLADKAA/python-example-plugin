"""Typed and validated configuration for the CPS detector.

Endstone loads plugin configuration from TOML.  This module deliberately has
no Endstone imports so its validation rules can be tested outside a server.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from string import Formatter
from typing import Any

DEFAULT_KICK_REASON = (
    "Unusually high CPS detected. Please avoid excessive clicking and reconnect if this was a mistake."
)
DEFAULT_DISPLAY_FORMAT = " §7[§f{cps} CPS§7]"


@dataclass(frozen=True, slots=True)
class CPSSettings:
    limit: float = 16.0
    warning_threshold: float = 16.0
    window_seconds: float = 1.0
    processing_interval_seconds: float = 0.10
    violation_seconds: float = 1.25
    warning_interval_seconds: float = 2.0
    idle_timeout_seconds: float = 0.30
    lag_reset_gap_seconds: float = 1.0
    max_measurement_cps: float = 80.0


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    enabled: bool = True
    update_interval_seconds: float = 0.15
    format: str = DEFAULT_DISPLAY_FORMAT
    precision: int = 0
    show_zero: bool = False


@dataclass(frozen=True, slots=True)
class WarningSettings:
    enabled: bool = True
    operators_only: bool = True
    console_logging: bool = False


@dataclass(frozen=True, slots=True)
class PunishmentSettings:
    enabled: bool = True
    kick: bool = True
    kick_reason: str = DEFAULT_KICK_REASON
    console_logging: bool = True


@dataclass(frozen=True, slots=True)
class PermissionSettings:
    bypass_visible_to_staff: bool = True


@dataclass(frozen=True, slots=True)
class PluginSettings:
    enabled: bool = True
    cps: CPSSettings = CPSSettings()
    display: DisplaySettings = DisplaySettings()
    warnings: WarningSettings = WarningSettings()
    punishment: PunishmentSettings = PunishmentSettings()
    permissions: PermissionSettings = PermissionSettings()


class ConfigurationManager:
    """Converts Endstone's TOML-backed mapping into safe, typed settings."""

    def __init__(self, warn: Callable[[str], None] | None = None) -> None:
        self._warn = warn or (lambda _message: None)

    def load(self, raw: Mapping[str, Any] | None) -> PluginSettings:
        """Validate a raw config mapping, falling back field-by-field to defaults."""
        if not isinstance(raw, Mapping):
            self._warn("The configuration root is not a table; all values use safe defaults.")
            raw = {}

        cps_raw = self._section(raw, "cps")
        display_raw = self._section(raw, "display")
        warnings_raw = self._section(raw, "warnings")
        punishment_raw = self._section(raw, "punishment")
        permissions_raw = self._section(raw, "permissions")

        cps = CPSSettings(
            limit=self._number(cps_raw, "limit", 16.0, 0.1, 200.0),
            warning_threshold=self._number(cps_raw, "warning_threshold", 16.0, 0.1, 200.0),
            window_seconds=self._number(cps_raw, "window_seconds", 1.0, 0.1, 5.0),
            processing_interval_seconds=self._number(
                cps_raw, "processing_interval_seconds", 0.10, 0.05, 1.0
            ),
            violation_seconds=self._number(cps_raw, "violation_seconds", 1.25, 0.25, 30.0),
            warning_interval_seconds=self._number(cps_raw, "warning_interval_seconds", 2.0, 0.25, 600.0),
            idle_timeout_seconds=self._number(cps_raw, "idle_timeout_seconds", 0.30, 0.1, 2.0),
            lag_reset_gap_seconds=self._number(cps_raw, "lag_reset_gap_seconds", 1.0, 0.25, 10.0),
            max_measurement_cps=self._number(cps_raw, "max_measurement_cps", 80.0, 1.0, 250.0),
        )
        ceiling_floor = max(cps.limit, cps.warning_threshold)
        if cps.max_measurement_cps <= ceiling_floor:
            measurement_ceiling = ceiling_floor + 1.0
            self._warn(
                "cps.max_measurement_cps must be greater than cps.limit and cps.warning_threshold; "
                f"the measurement ceiling was raised to {measurement_ceiling:g}."
            )
            cps = CPSSettings(
                limit=cps.limit,
                warning_threshold=cps.warning_threshold,
                window_seconds=cps.window_seconds,
                processing_interval_seconds=cps.processing_interval_seconds,
                violation_seconds=cps.violation_seconds,
                warning_interval_seconds=cps.warning_interval_seconds,
                idle_timeout_seconds=cps.idle_timeout_seconds,
                lag_reset_gap_seconds=cps.lag_reset_gap_seconds,
                max_measurement_cps=measurement_ceiling,
            )

        display_format = self._text(
            display_raw,
            "format",
            DEFAULT_DISPLAY_FORMAT,
            maximum_length=128,
        )
        if not self._valid_display_format(display_format):
            self._warn("display.format must contain only the {cps} placeholder; the default format is being used.")
            display_format = DEFAULT_DISPLAY_FORMAT

        precision_value = display_raw.get("precision", 0)
        if isinstance(precision_value, bool) or not isinstance(precision_value, int) or not 0 <= precision_value <= 2:
            self._warn("Invalid display.precision; using the default value 0.")
            precision_value = 0

        operators_only = self._boolean(warnings_raw, "operators_only", True)
        if not operators_only:
            self._warn("Operator warnings are always staff-only; warnings.operators_only remains true for safety.")
            operators_only = True

        return PluginSettings(
            enabled=self._boolean(raw, "enabled", True),
            cps=cps,
            display=DisplaySettings(
                enabled=self._boolean(display_raw, "enabled", True),
                update_interval_seconds=self._number(
                    display_raw, "update_interval_seconds", 0.15, 0.05, 1.0
                ),
                format=display_format,
                precision=precision_value,
                show_zero=self._boolean(display_raw, "show_zero", False),
            ),
            warnings=WarningSettings(
                enabled=self._boolean(warnings_raw, "enabled", True),
                operators_only=operators_only,
                console_logging=self._boolean(warnings_raw, "console_logging", False),
            ),
            punishment=PunishmentSettings(
                enabled=self._boolean(punishment_raw, "enabled", True),
                kick=self._boolean(punishment_raw, "kick", True),
                kick_reason=self._text(
                    punishment_raw,
                    "kick_reason",
                    DEFAULT_KICK_REASON,
                    maximum_length=256,
                ),
                console_logging=self._boolean(punishment_raw, "console_logging", True),
            ),
            permissions=PermissionSettings(
                bypass_visible_to_staff=self._boolean(permissions_raw, "bypass_visible_to_staff", True)
            ),
        )

    def _section(self, root: Mapping[str, Any], name: str) -> Mapping[str, Any]:
        value = root.get(name, {})
        if isinstance(value, Mapping):
            return value
        self._warn(f"Configuration section [{name}] is not a table; its values use safe defaults.")
        return {}

    def _boolean(self, section: Mapping[str, Any], key: str, default: bool) -> bool:
        value = section.get(key, default)
        if isinstance(value, bool):
            return value
        self._warn(f"Invalid {key!r} boolean value; using {default!r}.")
        return default

    def _number(
        self,
        section: Mapping[str, Any],
        key: str,
        default: float,
        minimum: float,
        maximum: float,
    ) -> float:
        value = section.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._warn(f"Invalid {key!r} number; using {default}.")
            return default
        try:
            result = float(value)
        except (OverflowError, ValueError):
            self._warn(f"Invalid {key!r} number; using {default}.")
            return default
        if not math.isfinite(result) or not minimum <= result <= maximum:
            self._warn(f"Invalid {key!r} value {value!r}; expected {minimum}..{maximum}, using {default}.")
            return default
        return result

    def _text(
        self,
        section: Mapping[str, Any],
        key: str,
        default: str,
        *,
        maximum_length: int,
    ) -> str:
        value = section.get(key, default)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum_length:
            self._warn(f"Invalid {key!r} text; using the safe default.")
            return default
        return value

    @staticmethod
    def _valid_display_format(value: str) -> bool:
        try:
            fields = list(Formatter().parse(value))
        except ValueError:
            return False
        if not fields:
            return False
        placeholders = [
            field_name for _literal, field_name, format_spec, conversion in fields if field_name is not None
        ]
        return placeholders == ["cps"] and all(
            format_spec == "" and conversion is None
            for _literal, field_name, format_spec, conversion in fields
            if field_name is not None
        )
