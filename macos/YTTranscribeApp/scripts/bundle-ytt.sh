#!/bin/sh
# [AI-GENERATED] Chatbox agent (claude-opus-5-5); pending human review.
# Packages the ytt CLI (src/ytt) as a single zipapp (ytt.pyz) and copies it
# into the app bundle's Resources so the app works without a separate install.
# Requires python3 on the build machine; yt-dlp is still resolved at runtime.
set -eu

REPO_ROOT="$(cd "$SRCROOT/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$REPO_ROOT/src/ytt" "$STAGE/ytt"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +

DEST="$TARGET_BUILD_DIR/$UNLOCALIZED_RESOURCES_FOLDER_PATH"
mkdir -p "$DEST"
python3 -m zipapp "$STAGE" -o "$DEST/ytt.pyz" -p "/usr/bin/env python3" -m "ytt.cli:main"
chmod +x "$DEST/ytt.pyz"
