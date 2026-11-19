#!/bin/sh
# [AI-GENERATED] Claude Code agent; pending human review.
# Regenerates the hash-pinned package locks that the app installs into its
# private AI runtime. Run from anywhere after editing AIRuntime/*.in:
#
#   macos/YTTranscribeApp/scripts/lock-ai-runtime.sh
#
# The locks target Apple silicon, CPython 3.12 and macOS 14 (the app's minimum),
# and list the hashes of every wheel for each pinned version, so the same lock
# installs the macOS 15 and 26 builds of MLX on newer systems.
set -eu

DIR="$(cd "$(dirname "$0")/../AIRuntime" && pwd)"
for name in enhance speech; do
    MACOSX_DEPLOYMENT_TARGET=14.0 uv pip compile "$DIR/requirements-$name.in" \
        --python-platform aarch64-apple-darwin \
        --python-version 3.12 \
        --generate-hashes \
        --only-binary :all: \
        --no-header \
        --quiet \
        -o "$DIR/requirements-$name.txt"
    echo "wrote $DIR/requirements-$name.txt"
done
