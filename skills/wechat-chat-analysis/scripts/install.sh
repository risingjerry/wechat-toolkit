#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="${1:-$PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$SCRIPT_DIR/init_project.py" --workspace "$WORKSPACE" --install-deps

PROJECT_ROOT="$WORKSPACE"
if [[ "$(basename "$PROJECT_ROOT")" != "wechat-chat-analysis" ]]; then
  PROJECT_ROOT="$WORKSPACE/wechat-chat-analysis"
fi

cd "$PROJECT_ROOT"
python3 scripts/doctor.py

echo
echo "Ready."
echo
echo "You can now ask your agent in natural language, for example:"
echo '  $wechat-chat-analysis 第一次连接 WeChat 2，保存免登录 key'
echo '  $wechat-chat-analysis 更新一下 WeChat 2 的备份数据库'
echo '  $wechat-chat-analysis 导出张三的全部聊天记录'
echo '  $wechat-chat-analysis 增量导出李四'
echo '  $wechat-chat-analysis 导出群聊「开心一家人」'
echo
echo "The agent should run the needed scripts for you. You do not need to memorize Python commands."
