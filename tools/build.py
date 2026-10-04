#!/usr/bin/env python3
"""Validate, build, clean, or export the installable Endstone plugin wheel."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DIST = ROOT / "dist"
PACKAGE_NAME = "endstone_cps_detector"
ENTRY_POINT = "endstone_cps_detector:CPSTrackerPlugin"

sys.path.insert(0, str(SRC))


class BuildError(RuntimeError):
    """Raised when validation or packaging fails."""


def _run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise BuildError(f"Command failed with exit code {result.returncode}: {' '.join(args)}")


def _read_pyproject() -> dict[str, Any]:
    path = ROOT / "pyproject.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildError(f"Could not parse pyproject.toml: {exc}") from exc


def validate_structure_and_metadata() -> None:
    required = (
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "src" / PACKAGE_NAME / "__init__.py",
        ROOT / "src" / PACKAGE_NAME / "plugin.py",
        ROOT / "src" / PACKAGE_NAME / "detector.py",
        ROOT / "src" / PACKAGE_NAME / "cps_manager.py",
        ROOT / "src" / PACKAGE_NAME / "config.toml",
        ROOT / "tests" / "test_cps.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise BuildError("Missing required project files: " + ", ".join(missing))

    pyproject = _read_pyproject()
    project = pyproject.get("project", {})
    endstone_entries = project.get("entry-points", {}).get("endstone", {})
    if endstone_entries.get("cps-detector") != ENTRY_POINT:
        raise BuildError(f"Expected Endstone entry point cps-detector = {ENTRY_POINT!r}.")
    if project.get("requires-python") != ">=3.10":
        raise BuildError("Project Python support metadata must match the declared Endstone-compatible floor (>=3.10).")

    raw_config = tomllib.loads((ROOT / "src" / PACKAGE_NAME / "config.toml").read_text(encoding="utf-8"))
    from endstone_cps_detector.config import ConfigurationManager

    config_warnings: list[str] = []
    ConfigurationManager(config_warnings.append).load(raw_config)
    if config_warnings:
        raise BuildError("Packaged default config has validation warnings: " + "; ".join(config_warnings))
    print("Project structure, plugin metadata, and packaged TOML config: OK")


def validate_endstone_api() -> None:
    """Import the real current Endstone API and plugin class, not local stubs."""
    try:
        from endstone import Player
        from endstone.damage import DamageSource
        from endstone.event import ActorDamageEvent, Event, PlayerInteractEvent, PlayerQuitEvent
        from endstone.plugin import Plugin

        if PlayerInteractEvent.Action.LEFT_CLICK_AIR.name != "LEFT_CLICK_AIR":
            raise BuildError("Endstone PlayerInteractEvent.Action.LEFT_CLICK_AIR is unavailable or renamed.")
        for event_type in (ActorDamageEvent, PlayerQuitEvent):
            if not issubclass(event_type, Event):
                raise BuildError(f"Unexpected Endstone event binding: {event_type!r}")
        required_api_members = {
            Player: ("kick", "has_permission", "name_tag", "is_valid", "unique_id"),
            PlayerInteractEvent: ("player", "action"),
            ActorDamageEvent: ("damage_source",),
            PlayerQuitEvent: ("player",),
            DamageSource: ("type", "is_indirect", "damaging_actor"),
        }
        for api_type, members in required_api_members.items():
            for member in members:
                if not hasattr(api_type, member):
                    raise BuildError(f"Endstone {api_type.__name__} API is missing required member {member!r}.")
        module_name, class_name = ENTRY_POINT.split(":", 1)
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)
        if not issubclass(plugin_class, Plugin):
            raise BuildError(f"{ENTRY_POINT} does not resolve to an Endstone Plugin subclass.")
        if getattr(plugin_class, "api_version", None) != "0.11":
            raise BuildError("Plugin api_version must target Endstone 0.11.")
        if not hasattr(Player, "__name__"):
            raise BuildError("Could not import Endstone Player API.")
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(
            "Could not import the required Endstone API. Install the development extra "
            "(endstone>=0.11.9,<0.12) before validating."
        ) from exc
    print("Endstone API imports and plugin entry point: OK")


def validate() -> None:
    validate_structure_and_metadata()
    validate_endstone_api()
    _run([sys.executable, "-m", "compileall", "-q", "src", "tests", "tools"])
    _run([sys.executable, "-m", "ruff", "check", "src", "tests", "tools"])
    _run([sys.executable, "-m", "pytest", "-q"])
    print("Validation passed.")


def inspect_wheel(wheel_path: Path) -> None:
    try:
        with zipfile.ZipFile(wheel_path) as wheel:
            names = set(wheel.namelist())
            config_path = f"{PACKAGE_NAME}/config.toml"
            if config_path not in names:
                raise BuildError(f"Built wheel is missing packaged default config: {config_path}")
            if f"{PACKAGE_NAME}/plugin.py" not in names:
                raise BuildError("Built wheel is missing the plugin source module.")
            ep_files = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
            if len(ep_files) != 1:
                raise BuildError("Built wheel must contain one entry_points.txt metadata file.")
            entry_text = wheel.read(ep_files[0]).decode("utf-8")
            expected = f"cps-detector = {ENTRY_POINT}"
            if expected not in entry_text:
                raise BuildError(f"Built wheel is missing Endstone entry point: {expected}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BuildError(f"Could not inspect wheel {wheel_path}: {exc}") from exc
    print(f"Wheel contents and Endstone metadata verified: {wheel_path.relative_to(ROOT)}")


def build_wheel() -> Path:
    DIST.mkdir(exist_ok=True)
    _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(DIST)])
    wheels = sorted(DIST.glob("*.whl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not wheels:
        raise BuildError("Build completed without producing a wheel in dist/.")
    inspect_wheel(wheels[0])
    return wheels[0]


def clean() -> None:
    generated_version = SRC / PACKAGE_NAME / "_version.py"
    for path in (ROOT / "build", DIST, ROOT / ".pytest_cache", ROOT / ".ruff_cache", generated_version):
        if path.exists():
            shutil.rmtree(path)
    for source_root in (SRC, ROOT / "tests", ROOT / "tools"):
        if not source_root.exists():
            continue
        for path in source_root.rglob("__pycache__"):
            if path.is_dir():
                shutil.rmtree(path)
    for path in ROOT.glob("*.egg-info"):
        if path.is_dir():
            shutil.rmtree(path)
    print("Generated build, distribution, and test cache files removed.")


def export_wheel(destination: str | None) -> None:
    target_value = destination or os.environ.get("ENDSTONE_PLUGIN_DIR")
    if not target_value:
        raise BuildError("Pass --to <Endstone plugins directory> or set ENDSTONE_PLUGIN_DIR.")
    validate()
    wheel = build_wheel()
    target = Path(target_value).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    exported = target / wheel.name
    shutil.copy2(wheel, exported)
    print(f"Exported Endstone plugin wheel: {exported}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("build", "Validate, test, and build the installable wheel."),
        ("rebuild", "Clean generated files, then validate, test, and rebuild the wheel."),
        ("validate", "Check Endstone API imports, metadata, syntax, lint, and tests."),
        ("package", "Validate and package the installable wheel."),
        ("clean", "Remove generated build and test files."),
    ):
        subparsers.add_parser(action, help=help_text)
    export_parser = subparsers.add_parser("export", help="Build and copy the wheel into a server plugins directory.")
    export_parser.add_argument("--to", dest="destination", help="Destination Endstone plugins directory.")
    args = parser.parse_args()

    try:
        if args.action == "clean":
            clean()
        elif args.action == "validate":
            validate()
        elif args.action in {"build", "package"}:
            validate()
            build_wheel()
        elif args.action == "rebuild":
            clean()
            validate()
            build_wheel()
        elif args.action == "export":
            export_wheel(args.destination)
        else:
            parser.error(f"Unknown action: {args.action}")
    except BuildError as exc:
        print(f"BUILD ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
