#!/bin/bash
# Installs Pochtalion as a desktop application on Linux.
# Run once: bash install_desktop.sh

set -e
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"

chmod +x "$SCRIPT_DIR/run.sh"

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

sed \
    -e "s|/ABSOLUTE/PATH/TO/run.sh|$SCRIPT_DIR/run.sh|g" \
    -e "s|/ABSOLUTE/PATH/TO/icon.ico|$SCRIPT_DIR/icon.ico|g" \
    "$SCRIPT_DIR/Pochtalion.desktop" > "$DESKTOP_DIR/Pochtalion.desktop"

chmod +x "$DESKTOP_DIR/Pochtalion.desktop"

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo "[Pochtalion] Installed to $DESKTOP_DIR/Pochtalion.desktop"
echo "[Pochtalion] The app should now appear in your application menu."
