# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Replaced the template example with a production-oriented Endstone CPS detector.
- Added attack normalization from explicit `LEFT_CLICK_AIR` and direct player melee `ActorDamageEvent` sources.
- Added bounded timestamp-based CPS measurement, continuous violation timing, lag recovery, staff warnings, kick-only enforcement, and safe name-tag suffix handling.
- Added validated TOML configuration, administrative commands/permissions, unit tests, and a VS Code task-driven build/export workflow.

### Changed
- Targeted Endstone API 0.11.9+ to use the explicit Bedrock left-click-air event; current development dependency resolves the latest compatible 0.11.x API.
- Replaced starter-template documentation and command/config examples with CPS Detector deployment documentation.

## [0.5.0] - 2026-03-23

### Changed
- Overhauled plugin examples to focus on essential patterns: lifecycle, config, commands, events
- Two commands (`/hello`, `/broadcast`) demonstrating `isinstance` sender checks, config usage, and arguments
- Simplified listener to player join/quit with event priority example
- Modernized build system with hatch-vcs for automatic git-tag versioning
- Switched from pip to uv for dependency management and builds
- Updated minimum Python version to 3.10
- Bumped api_version from 0.6 to 0.11
- Simplified source file names (plugin.py, listener.py)
- CI now runs linting (ruff)
- Replaced publish workflow with full release automation (changelog, tagging, PyPI, GitHub release)
- README rewritten as a practical template quickstart with renaming guide, dependency instructions, and release docs
- Fixed deprecated ServerListPingEvent API (remote_host/remote_port to address)

### Added
- AGENTS.md to guide AI coding agents building Endstone plugins
- Default config.toml with multiple value types (string, bool)
- Comments and docstrings throughout example code explaining what and why
- CONTRIBUTING.md, bug report and feature request issue templates
- Ruff linting and Dependabot configuration

### Removed
- Separate CommandExecutor class (command.py); on_command approach is simpler for examples
- Scheduler, permission attachment examples (too advanced for a starter template)
