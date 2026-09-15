#!/usr/bin/env bash
#
# Regenerate every dependency lock file from the *.in sources.
#
# Run this after editing requirements.in or requirements-build.in, then
# commit the *.in change together with all four regenerated lock files
# under requirements/.
#
# The locks are pinned to one exact Python version (build/PYTHON_VERSION)
# and one platform each. `uv` resolves the same inputs to the same output
# deterministically, so re-running this on any machine with the same uv
# version produces byte-identical files.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

PYTHON_VERSION="$(cat build/PYTHON_VERSION)"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

mkdir -p requirements

compile() {
    local in_file="$1" platform="$2" out_file="$3"
    echo ">> $out_file"
    uv pip compile "$in_file" \
        --quiet \
        --generate-hashes \
        --python-version "$PYTHON_VERSION" \
        --python-platform "$platform" \
        -o "$out_file"
}

compile requirements.in       linux   requirements/linux.txt
compile requirements.in       windows requirements/windows.txt
compile requirements-build.in linux   requirements/build-linux.txt
compile requirements-build.in windows requirements/build-windows.txt

echo "done — review the diff and commit the *.in and *.txt together."
