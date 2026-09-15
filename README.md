# Pochtalion

PyQt6 desktop app for Telegram bulk messaging and parsing.

## Running from source

Requires [`uv`](https://docs.astral.sh/uv/). Everything else (the exact Python
version, all dependencies) is provisioned automatically.

```bash
./run.sh          # Linux / macOS
run.bat           # Windows
```

The launcher creates `.venv` on the pinned Python (`build/PYTHON_VERSION`) and
installs the hash-verified lock (`requirements-<os>.txt`). The dev environment is
identical to the build environment on purpose.

## Dependencies

- Edit **`requirements.in`** (runtime) or **`requirements-build.in`** (build tools) —
  top-level packages only.
- Regenerate the locks: `./build/lock.sh`
- Commit the `.in` change together with every regenerated `requirements*-*.txt`.

Installs use `pip install --require-hashes`, so a compromised index cannot
substitute a package.

## Building a standalone binary

See [`build/README.md`](build/README.md) — build it yourself from source,
locally, on Linux (Docker) or Windows.
