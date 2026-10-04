# Contributing

Thanks for helping improve Endstone CPS Detector.

## Development setup

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), and an internet connection for development dependencies.

```bash
uv sync --extra dev
```

The development extra installs the current Endstone `0.11.x` Python API, pytest, Ruff, and the wheel build frontend. The server runtime itself supplies Endstone when the wheel is installed.

## Validation

Run the same validation and packaging steps as the VS Code build tasks before opening a pull request:

```bash
uv run python tools/build.py validate
uv run python tools/build.py build
```

`validate` checks the plugin metadata and packaged TOML config, imports the real Endstone event/API used by detection, compiles the Python source, runs Ruff, and executes unit tests. `build` then creates and inspects the installable wheel in `dist/`.

## Design constraints

- Use supported Endstone APIs; do not add generic arm animations, Java APIs, or undocumented packet assumptions as attack evidence.
- Keep attack classification conservative and document any API limitation that could under-count attacks.
- Never auto-ban. A kick must require the configured continuous violation duration and an online-player check on the server thread.
- Keep click histories bounded and clear per-player services on disconnect.
- Update tests and `README.md` when detection behavior, configuration, commands, or permissions change.
