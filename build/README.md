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
  Windows `.exe` gets `icon.ico`; a PE version resource from `config.__version__`
  is a future nice-to-have.
