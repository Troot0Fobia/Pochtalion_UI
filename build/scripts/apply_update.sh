#!/usr/bin/env bash
#
# Detached self-update helper (Linux). Bundled into _internal/scripts/ by
# pochtalion.spec; modules.update_apply copies it out to a scratch dir
# (independent of anything this script is about to touch) before launching
# it detached, right before the app process exits.
#
# Usage:
#   apply_update.sh directory <pid> <install_dir> <new_build_dir>
#   apply_update.sh appimage  <pid> <current_appimage_path> <new_appimage_path>
#
# "directory" replaces only the app's own files (the exe + _internal/)
# inside install_dir - never the whole directory - so a portable data/
# folder, or a POCHTALION_DATA_DIR that happens to live inside or alongside
# install_dir, survives untouched. This fixed pair must match
# modules.update_apply.APP_OWNED_NAMES; modules.update_apply already
# refused to get here at all if POCHTALION_DATA_DIR collided with either
# name, so this script never has to re-check that itself.

set -euo pipefail

wait_for_exit() {
    while kill -0 "$1" 2>/dev/null; do
        sleep 0.2
    done
}

FORM="$1"
echo "apply_update.sh starting: form=$FORM"

case "$FORM" in
    directory)
        PID="$2"; INSTALL_DIR="$3"; NEW_BUILD_DIR="$4"
        wait_for_exit "$PID"
        rm -rf "$INSTALL_DIR/_internal"
        rm -f "$INSTALL_DIR/Pochtalion"
        mv "$NEW_BUILD_DIR/_internal" "$INSTALL_DIR/_internal"
        mv "$NEW_BUILD_DIR/Pochtalion" "$INSTALL_DIR/Pochtalion"
        rm -rf "$(dirname "$NEW_BUILD_DIR")"
        EXE="$INSTALL_DIR/Pochtalion"
        ;;
    appimage)
        PID="$2"; CURRENT="$3"; NEW="$4"
        wait_for_exit "$PID"
        chmod +x "$NEW"
        mv -f "$NEW" "$CURRENT"
        EXE="$CURRENT"
        ;;
    *)
        echo "apply_update.sh: unknown form '$FORM'" >&2
        exit 1
        ;;
esac

nohup "$EXE" >/dev/null 2>&1 &
disown
echo "apply ($FORM) done, relaunched $EXE"

rm -- "$0"
