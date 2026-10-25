#!/usr/bin/env bash
set -euo pipefail

MARKETPLACE_NAME="${WECHAT_TOOLKIT_MARKETPLACE_NAME:-wechat-local-toolkit}"
PLUGIN_NAME="${WECHAT_TOOLKIT_PLUGIN_NAME:-wechat-toolkit}"
REPO_URL="${WECHAT_TOOLKIT_REPO_URL:-https://github.com/risingjerry/wechat-toolkit.git}"
BRANCH="${WECHAT_TOOLKIT_BRANCH:-main}"
PLUGIN_SUBDIR="${WECHAT_TOOLKIT_PLUGIN_SUBDIR:-.}"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
MARKETPLACE_ROOT="${WECHAT_TOOLKIT_MARKETPLACE_ROOT:-$CODEX_HOME/marketplaces/$MARKETPLACE_NAME}"
SOURCE_DIR="$MARKETPLACE_ROOT/.source"
PLUGIN_DIR="$MARKETPLACE_ROOT/plugins/$PLUGIN_NAME"
AUTO_UPDATE="${WECHAT_TOOLKIT_AUTO_UPDATE:-1}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required to install $PLUGIN_NAME" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to install $PLUGIN_NAME" >&2
  exit 1
fi

mkdir -p "$MARKETPLACE_ROOT/plugins"

if [ -d "$SOURCE_DIR/.git" ]; then
  git -C "$SOURCE_DIR" remote set-url origin "$REPO_URL"
  git -C "$SOURCE_DIR" fetch --prune origin "$BRANCH"
  git -C "$SOURCE_DIR" checkout "$BRANCH"
  git -C "$SOURCE_DIR" reset --hard "origin/$BRANCH"
else
  rm -rf "$SOURCE_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SOURCE_DIR"
fi

SOURCE_PLUGIN_DIR="$SOURCE_DIR"
if [ "$PLUGIN_SUBDIR" != "." ]; then
  SOURCE_PLUGIN_DIR="$SOURCE_DIR/$PLUGIN_SUBDIR"
fi

if [ ! -f "$SOURCE_PLUGIN_DIR/.codex-plugin/plugin.json" ]; then
  echo "Plugin manifest not found at $SOURCE_PLUGIN_DIR/.codex-plugin/plugin.json" >&2
  echo "Set WECHAT_TOOLKIT_PLUGIN_SUBDIR if the plugin is inside a monorepo." >&2
  exit 1
fi

mkdir -p "$PLUGIN_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  "$SOURCE_PLUGIN_DIR/" "$PLUGIN_DIR/"

python3 "$PLUGIN_DIR/scripts/self_update.py" configure \
  --repo-url "$REPO_URL" \
  --branch "$BRANCH" \
  --plugin-subdir "$PLUGIN_SUBDIR" \
  --marketplace-name "$MARKETPLACE_NAME" \
  --marketplace-root "$MARKETPLACE_ROOT" \
  --plugin-name "$PLUGIN_NAME" \
  --auto-update "$AUTO_UPDATE"

echo
echo "$PLUGIN_NAME installed."
echo "Marketplace: $MARKETPLACE_ROOT"
echo "Plugin:      $PLUGIN_DIR"
echo
echo 'Restart Codex, then use: $wechat-toolkit 初始化微信工具箱'
echo "Manual update command: wechat-toolkit-update"
