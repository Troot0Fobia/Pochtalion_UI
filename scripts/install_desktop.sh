#!/bin/bash
# Installs Pochtalion as a desktop application on Linux.
# Run once: bash scripts/install_desktop.sh

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

chmod +x "$REPO_ROOT/run.sh"

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

sed \
    -e "s|/ABSOLUTE/PATH/TO/run.sh|$REPO_ROOT/run.sh|g" \
    -e "s|/ABSOLUTE/PATH/TO/pochtalion.ico|$REPO_ROOT/pochtalion.ico|g" \
    "$SCRIPT_DIR/Pochtalion.desktop" > "$DESKTOP_DIR/Pochtalion.desktop"

chmod +x "$DESKTOP_DIR/Pochtalion.desktop"

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo "[Pochtalion] Installed to $DESKTOP_DIR/Pochtalion.desktop"
echo "[Pochtalion] The app should now appear in your application menu."
