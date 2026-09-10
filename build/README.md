# Build system

## Files

| File | Purpose |
|---|---|
| `PYTHON_VERSION` | the one exact Python version, read by everything |
| `lock.sh` | regenerate all dependency locks from the `.in` files |

## Trust model

The release artifact is the one **you build locally** (Docker for Linux, a VM for
Windows) - nothing downloads or executes anything you didn't choose to run
yourself.

Binaries are **not code-signed** (cost). Users verify the published SHA256 before
running.
