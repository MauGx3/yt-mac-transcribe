#!/bin/sh
# [AI-GENERATED] Claude Code agent; pending human review.
# Puts everything the app needs to set up on-device AI into the app bundle:
#
#   Contents/Helpers/uv                         pinned uv binary, checksum-verified
#   Contents/Resources/AIRuntime/requirements-*.txt   hash-pinned package locks
#   Contents/Resources/AIRuntime/rewrite_with_local_model.py   MLX-LM runner
#   Contents/Resources/AIRuntime/fetch_mlx_model.py            model pre-download
#
# Python, MLX and the models are not bundled: the app installs Python and the
# locked packages into ~/Library/Application Support when the user agrees, and
# models download on first use. See docs/ai-features.md.
#
# Called from bundle-ytt.sh (an Xcode build phase). Environment overrides:
#   YTT_UV_BINARY=/path/to/uv   copy this uv instead of downloading one
#   YTT_SKIP_UV_BUNDLE=1        build without uv (on-device AI setup is then
#                               unavailable in the app; Settings says so)
set -eu

UV_VERSION="0.13.9"
UV_WHEEL="uv-$UV_VERSION-py3-none-macosx_11_0_arm64.whl"
UV_URL="https://files.pythonhosted.org/packages/f3/a7/a8d7b074798c7fb3b26b37584b8fe2e29df2ccdc24ce7902caab2a53edbf/$UV_WHEEL"
UV_SHA256="66c512266d633bef48384a1f53003f41f2a8e7b36fe6e7fbfd3e0fd52d96fa63"

APP_ROOT="$(cd "$SRCROOT" && pwd)"
REPO_ROOT="$(cd "$SRCROOT/../.." && pwd)"
CONTENTS="$TARGET_BUILD_DIR/$CONTENTS_FOLDER_PATH"
RESOURCES="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH/AIRuntime"
HELPERS="$CONTENTS/Helpers"

mkdir -p "$RESOURCES"
cp "$APP_ROOT/AIRuntime/requirements-enhance.txt" "$APP_ROOT/AIRuntime/requirements-speech.txt" "$RESOURCES/"
cp "$REPO_ROOT/tools/rewrite_with_local_model.py" "$REPO_ROOT/tools/fetch_mlx_model.py" "$RESOURCES/"

if [ "${YTT_SKIP_UV_BUNDLE:-0}" = "1" ]; then
    echo "warning: YTT_SKIP_UV_BUNDLE=1, building without uv; on-device AI setup is unavailable."
    rm -f "$HELPERS/uv"
    exit 0
fi

mkdir -p "$HELPERS"
if [ -n "${YTT_UV_BINARY:-}" ]; then
    cp "$YTT_UV_BINARY" "$HELPERS/uv"
else
    CACHE="${HOME}/Library/Caches/yt-transcribe-build"
    mkdir -p "$CACHE"
    WHEEL="$CACHE/$UV_WHEEL"
    if [ ! -f "$WHEEL" ] || [ "$(shasum -a 256 "$WHEEL" | cut -d' ' -f1)" != "$UV_SHA256" ]; then
        rm -f "$WHEEL"
        if ! curl -fsSL --retry 3 -o "$WHEEL.part" "$UV_URL"; then
            rm -f "$WHEEL.part"
            echo "error: could not download uv $UV_VERSION from PyPI. Build offline with YTT_SKIP_UV_BUNDLE=1, or set YTT_UV_BINARY." >&2
            exit 1
        fi
        mv "$WHEEL.part" "$WHEEL"
    fi
    ACTUAL="$(shasum -a 256 "$WHEEL" | cut -d' ' -f1)"
    if [ "$ACTUAL" != "$UV_SHA256" ]; then
        rm -f "$WHEEL"
        echo "error: uv wheel checksum mismatch (got $ACTUAL, expected $UV_SHA256)." >&2
        exit 1
    fi
    unzip -p "$WHEEL" "uv-$UV_VERSION.data/scripts/uv" > "$HELPERS/uv"
fi
chmod 755 "$HELPERS/uv"

# Nested code must be signed before Xcode signs the app around it. Unsigned
# builds (CODE_SIGNING_ALLOWED=NO, as in CI) keep uv's own ad-hoc signature.
if [ "${CODE_SIGNING_ALLOWED:-YES}" = "YES" ] && [ -n "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]; then
    TIMESTAMP="--timestamp=none"
    # Notarization needs a secure timestamp; ad-hoc signatures cannot have one.
    if [ "${CONFIGURATION:-}" = "Release" ] && [ "$EXPANDED_CODE_SIGN_IDENTITY" != "-" ]; then
        TIMESTAMP="--timestamp"
    fi
    codesign --force --options runtime "$TIMESTAMP" \
        --sign "$EXPANDED_CODE_SIGN_IDENTITY" "$HELPERS/uv"
fi
