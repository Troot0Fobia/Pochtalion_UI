#!/bin/bash
#
# Dev launcher (Linux). Creates a .venv on the exact pinned Python and
# installs the hash-locked dependencies, then runs the app.
#
# The dev environment is deliberately identical to the build environment:
# same Python (build/PYTHON_VERSION), same locked deps (requirements-linux.txt).

set -e
cd "$(dirname "$(readlink -f "$0")")"

PYTHON_VERSION="$(cat build/PYTHON_VERSION)"
LOCK="requirements-linux.txt"
# Never silently substitute a Python already on this machine for the
# python-build-standalone build uv itself manages.
export UV_PYTHON_PREFERENCE=only-managed

if ! command -v uv >/dev/null 2>&1; then
    echo "[Pochtalion] 'uv' is required. Install it with:"
    echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  then re-run this script."
    exit 1
fi

# Recreate the venv if it is missing or on the wrong Python version.
current=""
[ -x .venv/bin/python ] && current="$(.venv/bin/python -c 'import platform; print(platform.python_version())' 2>/dev/null || true)"
if [ "$current" != "$PYTHON_VERSION" ]; then
    echo "[Pochtalion] Creating .venv on Python $PYTHON_VERSION ..."
    rm -rf .venv
    uv venv --python "$PYTHON_VERSION" .venv
fi

# Make the venv match the lock exactly (fast no-op when already in sync).
uv pip sync --python .venv --require-hashes "$LOCK"

exec .venv/bin/python main.py
