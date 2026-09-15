# Build system

Builds a standalone binary from source, for both maintainers cutting a
release and anyone who'd rather build from source than trust a prebuilt
download. Everything runs on your own machine; the only network access is
downloading Python/dependencies/build tools, all hash- or checksum-verified
so a compromised mirror can't substitute anything.

## Files

| File | Purpose |
|---|---|
| `PYTHON_VERSION` | the one exact Python version, read by everything |
| `lock.sh` | regenerate all dependency locks from the `.in` files |
| `pochtalion.spec` | PyInstaller recipe (onedir) |
| `Dockerfile.build` | Linux build image (Debian + system libs + uv) |
| `build-linux.sh` | the Linux build itself (in the container, or on a matching host) |
| `container-build-linux.sh` | host entry point: build the image, run the build in it |
| `build-windows.ps1` | Windows build (run on a Windows machine/VM) |
| `appimage.sh` | package the Linux onedir as an AppImage; called by build-linux.sh |
| `installer.iss` | Inno Setup script (Windows installer, per-user install) |

## Building on Linux

Install [podman](https://podman.io/docs/installation) (rootless by default —
see "Container engine" below for why this matters over plain Docker).

```bash
./build/container-build-linux.sh
```

Output in `dist/`:

- `Pochtalion/` — the onedir tree
- `Pochtalion-<version>-linux-x86_64.tar.gz`
- `Pochtalion-<version>-x86_64.AppImage`
- `SHA256SUMS`

`build-linux.sh` also runs `Pochtalion --selfcheck` — a display-free import +
offscreen-Qt smoke test that fails the build if the bundle is missing a
module.

## Building on Windows

Prerequisites on the Windows machine:
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) on PATH.
- Optionally, [Inno Setup](https://jrsoftware.org/isinfo.php) for the
  installer — see "Installing Inno Setup" below. Without it the script still
  produces the zip, just skips the installer.

```powershell
.\build\build-windows.ps1
```

Output in `dist\`:
- `Pochtalion\` — the onedir tree
- `Pochtalion-<version>-windows-x86_64.zip`
- `Pochtalion-<version>-windows-setup.exe` — installer, if Inno Setup is present
- `SHA256SUMS`

### Installing Inno Setup

```powershell
$url  = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
$sha  = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
Invoke-WebRequest $url -OutFile innosetup.exe
$actual = (Get-FileHash innosetup.exe -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $sha) { throw "checksum mismatch: got $actual" }
.\innosetup.exe /VERYSILENT   # unattended install; adds iscc.exe to PATH
```

(Pinned to a specific version + checksum rather than whatever
`jrsoftware.org` currently links to — check
https://jrsoftware.org/isdl.php for newer releases and re-pin
deliberately if you want one.) One-time setup, not something
`build-windows.ps1` does on every run.

## Where builds get their inputs from

Every third-party thing a build downloads is verified before use, so a
compromised mirror or CDN can't substitute something else in:

- **Python + every dependency**: `uv` fetches the exact pinned interpreter
  and installs from `requirements/*.txt` with `--require-hashes` — a wheel
  whose hash doesn't match the lock file is rejected outright. Regenerate
  locks with `build/lock.sh` after editing `requirements.in` /
  `requirements-build.in`.
- **uv itself** (`Dockerfile.build`): downloaded from its GitHub release and
  checked against the checksum file it publishes alongside it.
- **appimagetool + its runtime stub** (`appimage.sh`): pinned to a specific
  release and a sha256 captured from that exact asset — appimagetool's own
  "continuous" build is a moving target and, left to its defaults, silently
  downloads its runtime stub unpinned.
- **Inno Setup**: pinned by sha256 (see above).

Binaries are **not code-signed** (cost) — verify the published `SHA256SUMS`
after downloading, or just build it yourself from source.

## Container engine: podman over docker

`container-build-linux.sh` prefers **podman**: it's rootless by default (no
background daemon, nothing to pre-authorize), whereas a plain `docker`
install normally means either a root daemon or membership in the `docker`
group — which owns the daemon socket and is therefore equivalent to
passwordless root. `docker` still works
(`CONTAINER_ENGINE=docker ./build/container-build-linux.sh`) if that's what
you have installed.

## Notes / open optimisations

- The onedir tree is ~617 MB uncompressed (QtWebEngine bundles a full Chromium).
  A later size pass can drop unused Qt modules (QtQuick3D, QtPdf, QtDesigner…)
  and trim `qtwebengine_locales` to the languages we ship. Not done yet — keep
  the build working first.
- `hiddenimports` in the spec is empty; the bundled PyQt6 hooks + hooks-contrib
  (`puremagic`, `tzdata`) cover the dep graph. Revisit only if a build reports a
  missing module.
- On Linux the icon is ignored (comes from the `.desktop` / AppImage). The
  Windows `.exe` gets `pochtalion.ico`; a PE version resource from the
  `VERSION` file is a future nice-to-have.
