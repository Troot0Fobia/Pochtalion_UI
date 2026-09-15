# Build system

## Files

| File | Purpose |
|---|---|
| `PYTHON_VERSION` | the one exact Python version, read by everything |
| `lock.sh` | regenerate all dependency locks from the `.in` files |
| `pochtalion.spec` | PyInstaller recipe (onedir) |
| `Dockerfile.build` | Linux build image (OS + uv only) |
| `build-linux.sh` | Linux build (in the image or on a matching host) |
| `container-build-linux.sh` | host entry point: build the image, run the build in it |
| `build-windows.ps1` | Windows build (run on a Windows machine/VM) |
| `appimage.sh` | package the Linux onedir as an AppImage; called by build-linux.sh |
| `installer.iss` | Inno Setup script (Windows installer) |

## Building on Linux

Install [podman](https://podman.io/docs/installation) (rootless by default —
see "Container engine" below for why this matters over plain Docker).

```bash
./build/container-build-linux.sh    # build the image, run the build in it
```

Output in `dist/`:

- `Pochtalion/` — the onedir tree
- `Pochtalion-<version>-linux-x86_64.tar.gz` — release archive (deterministic:
  fixed member order, owner 0, mtime = last commit)
- `SHA256SUMS`

`build-linux.sh` also runs `Pochtalion --selfcheck` — a display-free import +
offscreen-Qt smoke test that fails the build if the bundle is missing a module.

## Building on Windows

Prerequisites on the Windows build VM:
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) on PATH.
- Optionally, [Inno Setup](https://jrsoftware.org/isinfo.php) for the
  installer — see "Installing Inno Setup" below. Without it the script still
  produces the zip, just skips the installer.

```powershell
.\build\build-windows.ps1
```

Output in `dist\`:
- `Pochtalion\` — the onedir tree
- `Pochtalion-<version>-windows-x86_64.zip` — release archive
- `Pochtalion-<version>-windows-setup.exe` — installer, if Inno Setup is present
- `SHA256SUMS`

### Installing Inno Setup

Releases moved to GitHub (`jrsoftware/issrc`) a while back, so — like uv and
appimagetool — we can pin a specific asset by a real sha256 rather than just
trusting whatever `jrsoftware.org` currently links to. Verified by hand:

```powershell
$url  = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
$sha  = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"
Invoke-WebRequest $url -OutFile innosetup.exe
$actual = (Get-FileHash innosetup.exe -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $sha) { throw "checksum mismatch: got $actual" }
.\innosetup.exe /VERYSILENT   # unattended install; adds iscc.exe to PATH
```

The installer is also Authenticode-signed by the author, Jordan Russell, as
a second check: `(Get-AuthenticodeSignature .\innosetup.exe).Status` should
read `Valid`.

This is a one-time setup step on the build VM, not something
`build-windows.ps1` does on every run. Check https://jrsoftware.org/isdl.php
for newer releases and re-pin (new version → new sha256) deliberately, the
same way `build/appimage.sh`'s pins get updated.

The exact interpreter (`PYTHON_VERSION`) and every wheel (`requirements-*.txt`,
`--require-hashes`) are fetched over the network but hash-verified, so the build
cannot pick up a substituted artifact.

## Trust model

The release artifact is the one **you build locally** (Docker for Linux, a VM for
Windows) - nothing downloads or executes anything you didn't choose to run
yourself.

Binaries are **not code-signed** (cost). Users verify the published SHA256 before
running.

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
  Windows `.exe` gets `pochtalion.ico`; a PE version resource from
  `config.__version__` is a future nice-to-have.
