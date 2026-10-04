# Endstone CPS Detector

A conservative, server-side CPS monitor for Minecraft Bedrock Dedicated Server running **Endstone 0.11.9 or newer**. The project targets Endstone API `0.11` and is developed against the current `0.11.x` API. It measures only attack evidence exposed by Endstone; it does not treat generic animations or arbitrary damage as clicks.

## Detection sources and scope

The detector listens to two official Endstone events:

1. **Air/missed attacks:** `PlayerInteractEvent` with `Action.LEFT_CLICK_AIR`. Endstone maps Bedrock's `MissedSwing` input bit to this explicit left-click-air action (available starting with Endstone 0.11.9). This counts an attack attempt that hits no block or actor.
2. **Entity hits:** `ActorDamageEvent` only when the `DamageSource` is direct, non-indirect, player-caused melee damage (`entity_attack` or the Bedrock `mace_smash` cause). This counts player hits on other players and mobs/entities when Endstone reports the hit through its damage event.

The plugin intentionally does **not** count:

- `PlayerArmSwingEvent` by itself: it is a generic arm animation and cannot prove an attack.
- Left-clicking/breaking a block (`LEFT_CLICK_BLOCK`), block placing, right-click interactions, item use, eating, inventory actions, movement, or emotes.
- Projectile, environmental, fire, fall, explosion, indirect, or non-player damage.

No raw packet decoder or undocumented server hook is used. The high-level Endstone air-click event already exposes the Bedrock missed-swing action; entity hits are filtered using the public `ActorDamageEvent.damage_source` fields.

### Accuracy limits (important)

Endstone does not currently expose a separate, universal `PlayerAttackEvent` carrying the player's attack intent and target for every case. Consequently, an entity attack is counted when a direct player melee `ActorDamageEvent` is emitted. A click against an invulnerable/immune target, or a case where the server produces no damage event, may not be counted. Conversely, a third-party plugin that deliberately creates damage with the same direct-player melee cause is indistinguishable from a real melee hit at this API layer. The plugin prefers under-counting these ambiguous cases over counting generic swings or kicking for them.

The Bedrock missed-swing signal is a per-input packet bit rather than an arbitrary-length click list. If a client/platform coalesces multiple air attacks into one input update, Endstone cannot recover a higher count from that event. CPS is therefore the attack rate the server/API actually exposes, not client-side telemetry.

References: [Endstone event API](https://endstone.dev/latest/reference/python/event/), [Endstone damage-source API](https://endstone.dev/latest/reference/python/damage/), and the Bedrock [Player Action packet](https://mojang.github.io/bedrock-protocol-docs/latest/packets/player-action-packet/) and [action types](https://mojang.github.io/bedrock-protocol-docs/latest/types/player-action-type/).

## Behavior

- Default measurement window: **1 second**. Use `0.5` for a more responsive, noisier half-second sample. Active samples are reevaluated on a configurable **0.10-second** cadence (bounded by the server's 20 Hz scheduler).
- Click timestamps use a monotonic clock and a bounded per-player deque. CPS is estimated from actual timestamps: `(sample_count - 1) / (last_timestamp - first_timestamp)` after at least three samples over a minimum observation span. One click is never extrapolated into a high CPS value.
- The default limit is **16 CPS**. Crossing it starts a continuous-time violation timer; it does **not** kick immediately. CPS must remain above the limit for **1.25 seconds** before enforcement is eligible.
- If the rate drops to or below the limit, the violation timer resets. A short idle pause clears the active burst. A long server sampling gap restarts the timer rather than crediting time that was not observed.
- Operator warnings are rate-limited per player (default: every 2 seconds) and sent only to operators or users with `cps.notify`. Console warning logging is independently configurable.
- Enforcement is **kick only**; this plugin never bans. Kicks are evaluated on Endstone's synchronous scheduler and re-check that the player is still online.
- Peak CPS is session-scoped and is cleared on disconnect, config reload, or an authorized admin reset.

## Name-tag display

CPS is shown as a suffix on the player's existing Bedrock name tag, by default:

```text
Steve [12 CPS]
```

The plugin stores the original/base tag and appends only its own suffix. If another plugin changes the tag while the CPS suffix is visible, that new value is adopted as the base on the next display refresh. On a zero value (by default) or plugin disable, only the CPS suffix is removed and the latest base tag is restored. `/cps toggle` disables/enables the caller's suffix; since Endstone changes the server-side actor name tag, that suffix is visible to everyone, not only to the caller. Name-tag formatting is inherently shared state: plugins that continuously rewrite the same name tag can still conflict, so keep `display.update_interval_seconds` conservative.

## Installation

1. Install an Endstone build using API `0.11.9+` on the server.
2. Build the wheel using the workflow below.
3. Copy `dist/endstone_cps_detector-*.whl` into the server's `plugins/` directory (or use **INSTALL/EXPORT** and select that directory).
4. Restart the server. Endstone loads Python plugins from wheel files in `plugins/`.
5. Edit the generated `plugins/CPS/config.toml` (the exact data-folder name is determined by Endstone) and restart or run `/cps reload`.

The plugin has no third-party runtime dependency; Endstone provides its own Python API in the server environment.

## Configuration

Endstone plugins use TOML (`config.toml`), not YAML. The packaged defaults are in `src/endstone_cps_detector/config.toml` and are copied to the plugin data folder on first enable.

```toml
enabled = true

[cps]
limit = 16.0
warning_threshold = 16.0
window_seconds = 1.0
processing_interval_seconds = 0.10
violation_seconds = 1.25
warning_interval_seconds = 2.0
idle_timeout_seconds = 0.30
lag_reset_gap_seconds = 1.0
max_measurement_cps = 80.0

[display]
enabled = true
update_interval_seconds = 0.15
format = " §7[§f{cps} CPS§7]"
precision = 0
show_zero = false

[warnings]
enabled = true
operators_only = true
console_logging = false

[punishment]
enabled = true
kick = true
kick_reason = "Unusually high CPS detected. Please avoid excessive clicking and reconnect if this was a mistake."
console_logging = true

[permissions]
bypass_visible_to_staff = true
```

Invalid types, non-finite numbers, out-of-range values, and unsupported format placeholders fall back to safe defaults with a useful warning. Operator warnings are always staff-only; setting `warnings.operators_only = false` is rejected and kept `true`.

`max_measurement_cps` is a sanity ceiling for reported rates, not a way to evade the configured limit: values at the ceiling are still over a normal 16 CPS threshold. The timestamp deque is bounded by this ceiling and the rolling window.

## Commands

| Command | Behavior | Permission |
|---|---|---|
| `/cps` | Shows the caller's current and peak CPS. | `cps.command` (everyone) |
| `/cps <player>` | Shows an online player's current and peak CPS. | `cps.view` (operators by default; self-view remains available via `/cps`) |
| `/cps info <player>` | Shows current CPS, session peak, time above the limit, and violation state. | `cps.admin` (operators by default) |
| `/cps reload` | Reloads TOML settings and clears current histories/peaks. | `cps.reload` (operators by default) |
| `/cps toggle` | Toggles the caller's CPS suffix on their server-side name tag. | `cps.toggle` (everyone by default) |
| `/cps reset <player>` | Clears current history, violation, and peak for an online player. | `cps.admin` (operators by default) |

Players with `cps.bypass` are never automatically kicked. Their measurements remain available to staff by default; set `permissions.bypass_visible_to_staff = false` to hide them from staff warnings and administrative query output. Name-tag display is a separate public display setting.

## Permissions

- `cps.command` — use `/cps` (default: everyone).
- `cps.view` — query another player's CPS (default: operators).
- `cps.admin` — view detailed violation state and reset a player's session (default: operators).
- `cps.reload` — reload server-side configuration (default: operators).
- `cps.toggle` — toggle the caller's CPS suffix (default: everyone).
- `cps.notify` — receive staff warnings (default: operators).
- `cps.bypass` — exempt a player from automatic kicks (default: nobody).

Thresholds and punishment settings cannot be changed by ordinary players. The bypass permission affects automatic kicks only; it does not erase recorded history.

## Development, validation, and packaging

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run python tools/build.py validate
uv run python tools/build.py build
```

The build validates the project layout and packaged config, imports the actual Endstone API (including `PlayerInteractEvent.Action.LEFT_CLICK_AIR`), checks the plugin entry point, compiles Python sources, runs Ruff and the tests, then builds and inspects the wheel. Endstone expects a wheel (`.whl`) in its `plugins/` directory; the artifact is written to `dist/`.

### Action Wheel / VS Code Tasks

The repository includes real VS Code tasks in `.vscode/tasks.json`. Open **Terminal → Run Task** and select one of:

- **BUILD PLUGIN** — validate, lint, test, build, and inspect the wheel.
- **REBUILD** — clean generated files, then run the full build.
- **VALIDATE** — check imports, syntax, metadata, lint, and tests.
- **PACKAGE** — validate and build/inspect the wheel.
- **CLEAN** — remove generated build/test files.
- **INSTALL/EXPORT** — run validation/build and copy the wheel to the plugins directory you enter in the prompt.

These tasks invoke `tools/build.py` through `uv run --extra dev`, so the development tools are synchronized automatically; they are not display-only buttons. The CLI equivalents are:

```bash
python tools/build.py validate
python tools/build.py build
python tools/build.py rebuild
python tools/build.py package
python tools/build.py clean
python tools/build.py export --to /path/to/endstone/plugins
```

Set `ENDSTONE_PLUGIN_DIR` instead of `--to` for automation. Export copies the `.whl`; it does not restart the server.

## Tests and performance

Run tests with `uv run pytest`. They cover timestamp-based 5, 10, 16, 16.1, 17, and 20 CPS, short/sustained violations, recovery, lag gaps, duplicate samples, bypass, config validation, name-tag restoration, and operator-only warning cooldowns.

Scheduled work is one lightweight callback at the configurable processing cadence; the detector evaluates only players with a recent attack burst. Click history is bounded, no per-click log is emitted, and player state is removed immediately on quit. The display does not rebuild or set a name tag when its formatted CPS value has not changed.

## License

MIT; see [LICENSE](LICENSE).
