# Build system

## Files

| File | Purpose |
|---|---|
| `PYTHON_VERSION` | the one exact Python version, read by everything |
| `lock.sh` | regenerate all dependency locks from the `.in` files |
| `pochtalion.spec` | PyInstaller recipe (onedir) |

## Trust model

The release artifact is the one **you build locally** (Docker for Linux, a VM for
Windows) - nothing downloads or executes anything you didn't choose to run
yourself.

Binaries are **not code-signed** (cost). Users verify the published SHA256 before
running.

## Notes / open optimisations

- The onedir tree is ~617 MB uncompressed (QtWebEngine bundles a full Chromium).
  A later size pass can drop unused Qt modules (QtQuick3D, QtPdf, QtDesigner…)
  and trim `qtwebengine_locales` to the languages we ship. Not done yet — keep
  the build working first.
- `hiddenimports` in the spec is empty; the bundled PyQt6 hooks + hooks-contrib
  (`puremagic`, `tzdata`) cover the dep graph. Revisit only if a build reports a
  missing module.
- On Linux the icon is ignored (comes from the `.desktop` / AppImage). The
  Windows `.exe` gets `icon.ico`; a PE version resource from `config.__version__`
  is a future nice-to-have.
