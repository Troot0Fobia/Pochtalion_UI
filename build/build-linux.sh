#!/usr/bin/env bash
#
# Linux build. Runs inside build/Dockerfile.build (via
# build/container-build-linux.sh) or directly on a host that matches it.
#
# Produces, under dist/:
#   Pochtalion/                                      the onedir tree
#   Pochtalion-<version>-linux-x86_64.tar.gz         the release archive
#   Pochtalion-<version>-linux-x86_64.tar.gz.sha256  its sha256 (sha256sum -c compatible)
#
# Also builds the AppImage (build/appimage.sh).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON_VERSION="$(cat build/PYTHON_VERSION)"
VERSION="$(cat VERSION)"
[ -n "$VERSION" ] || { echo "VERSION file is empty" >&2; exit 1; }

export UV_LINK_MODE=copy
# Never fall back to a discovered system Python for uv's own pinned,
# checksum-verified download.
export UV_PYTHON_PREFERENCE=only-managed

VENV="${POCHTALION_BUILD_VENV:-/tmp/pochtalion-build-venv}"
WORK="${POCHTALION_BUILD_WORK:-/tmp/pochtalion-pyi-work}"
DIST="$REPO_ROOT/dist"
ARCHIVE="Pochtalion-${VERSION}-linux-x86_64.tar.gz"

echo ">> version=$VERSION  python=$PYTHON_VERSION"

rm -rf "$VENV" "$WORK" "$DIST"

# --- provision the exact, hash-verified toolchain --------------------------
uv venv --python "$PYTHON_VERSION" "$VENV"
uv pip install --python "$VENV" --require-hashes \
    -r requirements/linux.txt \
    -r requirements/build-linux.txt

# --- build ---------------------------------------------------------------
"$VENV/bin/pyinstaller" build/pochtalion.spec \
    --distpath "$DIST" --workpath "$WORK" \
    --noconfirm --clean --log-level WARN

# --- smoke test (no display needed) -----------------------------------
# Runs the freshly built exe from inside dist/Pochtalion/ - with no override,
# core.paths sees a "directory"-form frozen install rooted right there and
# creates data/ next to the exe (portable mode's default), which would then
# ship inside the packaged tar.gz/AppImage. Point it at a throwaway dir instead.
echo ">> selfcheck"
SELFCHECK_DATA_DIR="$(mktemp -d)"
POCHTALION_DATA_DIR="$SELFCHECK_DATA_DIR" "$DIST/Pochtalion/Pochtalion" --selfcheck
rm -rf "$SELFCHECK_DATA_DIR"

# --- package ---------------------------------------------------------
echo ">> packaging"
tar -C "$DIST" -czf "$DIST/$ARCHIVE" Pochtalion

( cd "$DIST" && sha256sum "$ARCHIVE" > "$ARCHIVE.sha256" )
echo ">> done: dist/$ARCHIVE"

# --- AppImage ----------------------------------------------------------
POCHTALION_BUILD_PYTHON="$VENV/bin/python3" "$REPO_ROOT/build/appimage.sh"
