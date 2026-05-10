---
name: wechat-toolkit
description: "Use when the user wants the productized local WeChat toolkit: export/analyze WeChat chats or manage one-click WeChat multi-open on macOS."
---

# 微信工具箱

这个 plugin 对用户只暴露两个功能：

1. 微信聊天导出与分析
2. 微信一键多开

用户是小白时，不要向用户解释 key、salt、数据库同步、Frida hook、container 等内部步骤。用户只需要说目标，Agent 负责调用 plugin 脚本完成。

## 用户可以这样说

```text
$wechat-toolkit 初始化微信工具箱
$wechat-toolkit 更新一下 WeChat 2 的备份数据库
$wechat-toolkit 导出张三的全部聊天记录
$wechat-toolkit 增量导出李四
$wechat-toolkit 导出群聊「开心一家人」
$wechat-toolkit 重新生成「开心一家人」的 AI 分析文件
$wechat-toolkit 检查微信多开状态
$wechat-toolkit 安装微信双开
$wechat-toolkit 修复微信多开
$wechat-toolkit 一键打开两个微信
```

## Agent 执行原则

- 先判断用户要的是“聊天导出与分析”还是“微信多开”。
- 聊天导出与分析复用内置 `skills/wechat-chat-analysis/` 模板；如果本地还没有 `wechat-chat-analysis/` 工作区，先初始化。
- 微信多开复用内置 `skills/wechat-multifix/SKILL.md` 的流程和图标资源；安装/修复时按它的规则复制微信、修改 Bundle ID、重新签名和替换图标。
- 微信多开安装/修复会写入 `/Applications/WeChat2.app` 等应用路径，执行前要让用户确认。
- 对用户报告结果时，只说功能结果、导出目录、快照目录、成功/失败原因。
- 不把 Python 命令作为用户需要执行的步骤，除非用户明确要求命令。

## 内部入口

在 plugin 根目录内可用：

```bash
python3 scripts/wechat_toolkit.py chat status
python3 scripts/wechat_toolkit.py chat init
python3 scripts/wechat_toolkit.py chat update-backup --container-name com.tencent.xinWeChat2
python3 scripts/wechat_toolkit.py chat export --target-name 张三 --target-type contact
python3 scripts/wechat_toolkit.py multiopen status
python3 scripts/wechat_toolkit.py multiopen install --number 2 --theme black
python3 scripts/wechat_toolkit.py multiopen repair --number 2 --theme black
python3 scripts/wechat_toolkit.py multiopen launch --app /Applications/WeChat2.app
```

这些命令是给 Agent 和未来 CLI 调用的，不是给学员记忆的。
