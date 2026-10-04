from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from pathlib import Path

from endstone_cps_detector.config import (
    DEFAULT_DISPLAY_FORMAT,
    DEFAULT_KICK_REASON,
    ConfigurationManager,
)


def test_packaged_toml_defaults_validate_without_warnings() -> None:
    warnings: list[str] = []
    config_path = Path(__file__).parents[1] / "src" / "endstone_cps_detector" / "config.toml"
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    settings = ConfigurationManager(warnings.append).load(raw)
    assert warnings == []
    assert settings.enabled
    assert settings.cps.limit == 16.0
    assert settings.cps.window_seconds == 1.0
    assert settings.cps.processing_interval_seconds == 0.10
    assert settings.cps.violation_seconds == 1.25
    assert settings.display.format == DEFAULT_DISPLAY_FORMAT
    assert settings.warnings.operators_only
    assert settings.punishment.kick_reason == DEFAULT_KICK_REASON


def test_invalid_values_fall_back_to_safe_defaults_and_warn() -> None:
    warnings: list[str] = []
    settings = ConfigurationManager(warnings.append).load(
        {
            "enabled": "yes",
            "cps": {
                "limit": 500,
                "window_seconds": 0,
                "processing_interval_seconds": "fast",
                "warning_interval_seconds": float("nan"),
                "max_measurement_cps": 1,
            },
            "display": {
                "format": "{player} {cps}",
                "precision": 3,
                "show_zero": "false",
            },
            "warnings": {"operators_only": False},
            "punishment": {"kick_reason": ""},
        }
    )
    assert settings.enabled is True
    assert settings.cps.limit == 16.0
    assert settings.cps.window_seconds == 1.0
    assert settings.cps.processing_interval_seconds == 0.10
    assert settings.cps.warning_interval_seconds == 2.0
    assert settings.cps.max_measurement_cps > settings.cps.limit
    assert settings.display.format == DEFAULT_DISPLAY_FORMAT
    assert settings.display.precision == 0
    assert settings.display.show_zero is False
    assert settings.warnings.operators_only is True
    assert settings.punishment.kick_reason == DEFAULT_KICK_REASON
    assert len(warnings) >= 8


def test_measurement_ceiling_is_always_above_the_kick_limit() -> None:
    warnings: list[str] = []
    settings = ConfigurationManager(warnings.append).load(
        {"cps": {"limit": 16.0, "max_measurement_cps": 16.0}}
    )
    assert settings.cps.limit == 16.0
    assert settings.cps.max_measurement_cps == 17.0
    assert warnings

    settings = ConfigurationManager().load(
        {"cps": {"limit": 16.0, "warning_threshold": 100.0, "max_measurement_cps": 80.0}}
    )
    assert settings.cps.max_measurement_cps == 101.0


def test_huge_numeric_config_values_fall_back_instead_of_overflowing() -> None:
    warnings: list[str] = []
    settings = ConfigurationManager(warnings.append).load({"cps": {"limit": 10**400}})
    assert settings.cps.limit == 16.0
    assert warnings


def test_invalid_sections_use_defaults_instead_of_crashing() -> None:
    warnings: list[str] = []
    settings = ConfigurationManager(warnings.append).load({"cps": ["bad"], "display": None})
    assert settings.cps.limit == 16.0
    assert settings.display.enabled
    assert any("section [cps]" in warning for warning in warnings)
    assert any("section [display]" in warning for warning in warnings)
