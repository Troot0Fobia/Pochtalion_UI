#!/usr/bin/env bash
#
# Package dist/Pochtalion/ (built by build-linux.sh) as a single-file
# AppImage: dist/Pochtalion-<version>-x86_64.AppImage
#
# The PyInstaller onedir tree is already fully self-contained (Python, Qt,
# QtWebEngine and all), so this just wraps it in the AppDir layout - no
# linuxdeploy library-scanning needed, we already know exactly what's there.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO_ROOT"

VERSION="$(sed -nE 's/^__version__ = "([^"]+)"/\1/p' config.py)"
[ -n "$VERSION" ] || { echo "could not read __version__ from config.py" >&2; exit 1; }

DIST="$REPO_ROOT/dist"
APPDIR="$DIST/Pochtalion.AppDir"
# Needs Pillow for the icon conversion below; build-linux.sh passes its own
# venv's interpreter (which already has it, from requirements/linux.txt).
PYTHON="${POCHTALION_BUILD_PYTHON:-python3}"

if [ ! -x "$DIST/Pochtalion/Pochtalion" ]; then
    echo "dist/Pochtalion not found - run build/build-linux.sh first" >&2
    exit 1
fi

# Pinned, checksum-verified appimagetool. "continuous" is a moving tag on
# upstream's own release pipeline (confirmed: re-downloading it later gives a
# different sha256 despite an identical --version string) - pin the numbered
# release and a hash captured from that exact asset instead.
APPIMAGETOOL_VERSION=1.9.1
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
APPIMAGETOOL="$DIST/.appimagetool-${APPIMAGETOOL_VERSION}"

if [ ! -x "$APPIMAGETOOL" ]; then
    echo ">> fetching appimagetool $APPIMAGETOOL_VERSION"
    curl -LsSf -o "$APPIMAGETOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_VERSION}/appimagetool-x86_64.AppImage"
    echo "$APPIMAGETOOL_SHA256  $APPIMAGETOOL" | sha256sum -c -
    chmod +x "$APPIMAGETOOL"
fi

# appimagetool prepends an AppImage "runtime" stub to the squashfs to make the
# final file self-executing, and by DEFAULT DOWNLOADS IT FROM THE "continuous"
# (moving) TAG WITH NO CHECKSUM CHECK at build time. Pin a dated release and
# verify it ourselves, then pass --runtime-file so appimagetool never touches
# the network for it.
RUNTIME_VERSION=20251108
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
RUNTIME="$DIST/.appimage-runtime-${RUNTIME_VERSION}"

if [ ! -f "$RUNTIME" ]; then
    echo ">> fetching AppImage runtime $RUNTIME_VERSION"
    curl -LsSf -o "$RUNTIME" \
        "https://github.com/AppImage/type2-runtime/releases/download/${RUNTIME_VERSION}/runtime-x86_64"
    echo "$RUNTIME_SHA256  $RUNTIME" | sha256sum -c -
fi

echo ">> building AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a "$DIST/Pochtalion/." "$APPDIR/usr/bin/"

# Resize onto a square canvas for a conventional app icon (Pillow opens the
# largest frame of a multi-res ICO by default).
"$PYTHON" - "$REPO_ROOT/pochtalion.ico" "$APPDIR/pochtalion.png" <<'PYEOF'
import sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
im.thumbnail((256, 256), Image.LANCZOS)
canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
canvas.paste(im, ((256 - im.width) // 2, (256 - im.height) // 2), im)
canvas.save(dst)
PYEOF

cat > "$APPDIR/Pochtalion.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Pochtalion
Comment=Telegram bulk messaging tool
Exec=Pochtalion
Icon=pochtalion
Terminal=false
StartupNotify=true
Categories=Network;InstantMessaging;
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/usr/bin/Pochtalion" "$@"
EOF
chmod +x "$APPDIR/AppRun"

echo ">> running appimagetool"
OUT="$DIST/Pochtalion-${VERSION}-x86_64.AppImage"
rm -f "$OUT"
# --appimage-extract-and-run: works without /dev/fuse (rootless containers
# don't have it). ARCH is required when appimagetool
# can't infer the target architecture from AppRun (ours is a shell script,
# not an ELF binary). --runtime-file: see the pinning note above.
ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run --no-appstream \
    --runtime-file "$RUNTIME" "$APPDIR" "$OUT"
chmod +x "$OUT"

( cd "$DIST" && sha256sum "$(basename "$OUT")" >> SHA256SUMS )
echo ">> done: dist/$(basename "$OUT")"
