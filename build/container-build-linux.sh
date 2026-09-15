#!/usr/bin/env bash
#
# Host entry point for the Linux build.
#
#   ./build/container-build-linux.sh
#
# Builds the image from build/Dockerfile.build, then runs build/build-linux.sh
# inside it against the current checkout. Output lands in ./dist/, owned by
# you (not root) - see the comment below for why.
#
# Uses podman by default (rootless, no daemon, nothing to pre-authorize) -
# a plain `docker` install normally means either a root daemon or membership
# in the `docker` group, which owns the daemon socket and is therefore
# equivalent to passwordless root. Override with CONTAINER_ENGINE=docker if
# that's what you have installed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
IMAGE_TAG="pochtalion-build:linux"

if [ -n "${CONTAINER_ENGINE:-}" ]; then
    ENGINE="$CONTAINER_ENGINE"
elif command -v podman >/dev/null 2>&1; then
    ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
    ENGINE=docker
else
    echo "no container engine found. Install podman (recommended):" >&2
    echo "  https://podman.io/docs/installation" >&2
    exit 1
fi

# build/Dockerfile.build runs as a non-root 'builder' user. Under podman's
# default rootless mapping, only container UID 0 maps back to the invoking
# host user for a bind mount, so a non-root UID gets a plain "Permission
# denied" writing to /work. --userns=keep-id fixes this by mapping the
# invoking host UID to the same UID inside the container. Not needed (and
# not offered) for plain docker, which doesn't remap UIDs by default.
ENGINE_RUN_EXTRA=()
if [ "$ENGINE" = podman ]; then
    ENGINE_RUN_EXTRA=(--userns=keep-id)
fi

"$ENGINE" build --file "$REPO_ROOT/build/Dockerfile.build" --tag "$IMAGE_TAG" "$REPO_ROOT/build"

# Network is needed to fetch the pinned Python and the wheels, but every one of
# those is hash-verified (uv checks python-build-standalone; pip --require-hashes
# checks the wheels), so a MITM cannot substitute anything. A persistent uv
# cache volume makes repeat builds fast.
#
# --user "$(id -u):$(id -g)" overrides the image's baked-in uid rather than
# trusting it to match - the effective UID always matches whoever is
# actually running the build, on any host, podman or docker. That UID won't
# have an /etc/passwd entry, so HOME is pointed at the (world-writable)
# builder home explicitly.
"$ENGINE" run --rm \
    "${ENGINE_RUN_EXTRA[@]}" \
    --user "$(id -u):$(id -g)" \
    -e HOME=/home/builder \
    -v "$REPO_ROOT:/work:rw" \
    -v "pochtalion-uv-cache:/home/builder/.cache/uv" \
    "$IMAGE_TAG" \
    bash build/build-linux.sh
