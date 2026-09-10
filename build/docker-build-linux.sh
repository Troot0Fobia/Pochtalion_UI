#!/usr/bin/env bash
#
# Host entry point for the Linux build.
#
#   ./build/docker-build-linux.sh
#
# Builds the image from build/Dockerfile.build, then runs build/build-linux.sh
# inside it against the current checkout. Output lands in ./dist/ (owned by
# you, uid 1000 in the container).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
IMAGE_TAG="pochtalion-build:linux"

docker build --file "$REPO_ROOT/build/Dockerfile.build" --tag "$IMAGE_TAG" "$REPO_ROOT/build"

# Network is needed to fetch the pinned Python and the wheels, but every one of
# those is hash-verified (uv checks python-build-standalone; pip --require-hashes
# checks the wheels), so a MITM cannot substitute anything. A persistent uv
# cache volume makes repeat builds fast.
docker run --rm \
    -v "$REPO_ROOT:/work:rw" \
    -v "pochtalion-uv-cache:/home/builder/.cache/uv" \
    "$IMAGE_TAG" \
    bash build/build-linux.sh
