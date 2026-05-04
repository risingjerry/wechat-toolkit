# 微信工具箱 Plugin

`wechat-toolkit` 是面向产品化的本地微信工具箱。它把底层复杂流程收进 plugin 内部，对用户只暴露两个一级功能。

## 一行安装

推荐把本目录发布成独立 GitHub 仓库：`https://github.com/JNHFlow21/wechat-toolkit`。

发布后，用户只需要运行：

```bash
curl -fsSL https://raw.githubusercontent.com/JNHFlow21/wechat-toolkit/main/install.sh | bash
```

安装器会自动完成：

- 克隆或更新插件源码到 `~/.codex/marketplaces/wechat-local-toolkit/.source`
- 同步插件到 `~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit`
- 写入本地 marketplace：`~/.codex/marketplaces/wechat-local-toolkit/.agents/plugins/marketplace.json`
- 更新 `~/.codex/config.toml`，启用 `wechat-toolkit@wechat-local-toolkit`
- 安装每日自动更新任务
- 安装命令：`wechat-toolkit-update`

如果暂时仍从 `Knowledge_OS` 仓库分发，可以这样安装：

```bash
curl -fsSL https://raw.githubusercontent.com/JNHFlow21/Knowledge_OS/main/wechat/plugins/wechat-toolkit/install.sh | \
  WECHAT_TOOLKIT_REPO_URL=https://github.com/JNHFlow21/Knowledge_OS.git \
  WECHAT_TOOLKIT_PLUGIN_SUBDIR=wechat/plugins/wechat-toolkit \
  bash
```

安装后重启 Codex，然后使用：

```text
$wechat-toolkit 初始化微信工具箱
```

## 更新机制

默认会安装一个 macOS LaunchAgent，每天运行一次：

```bash
wechat-toolkit-update --quiet
```

手动更新：

```bash
wechat-toolkit-update
```

查看安装状态：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py status
```

关闭自动更新：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py uninstall-launchagent
```

安装时不启用自动更新：

```bash
curl -fsSL https://raw.githubusercontent.com/JNHFlow21/wechat-toolkit/main/install.sh | WECHAT_TOOLKIT_AUTO_UPDATE=0 bash
```

## 发布建议

短期用 GitHub 作为分发渠道最稳：你能控制版本、安装命令和自动更新。Marketplace 适合后续做官方入口，但不应该阻塞第一次公开分发。

建议发布流程：

1. 创建独立仓库 `JNHFlow21/wechat-toolkit`
2. 仓库根目录直接放本 plugin 的内容：`.codex-plugin/`、`skills/`、`scripts/`、`assets/`、`install.sh`
3. 每次更新后提升 `.codex-plugin/plugin.json` 的 `version`
4. 推送到 `main`
5. 用户的每日自动更新会 fast-forward 到最新 `main`

## 功能划分

### 1. 微信聊天导出与分析

这一功能复用内置的 `wechat-chat-analysis` skill。用户第一次下载 plugin 后，可以先初始化本地工作区：

```text
$wechat-toolkit 初始化微信工具箱
```

用户可以用短 prompt 让 Agent 完成：

```text
$wechat-toolkit 初始化微信工具箱
$wechat-toolkit 更新一下 WeChat 2 的备份数据库
$wechat-toolkit 导出张三的全部聊天记录
$wechat-toolkit 增量导出李四
$wechat-toolkit 导出群聊「开心一家人」
$wechat-toolkit 重新生成「开心一家人」的 AI 分析文件
```

Agent 内部负责从 plugin 内置模板创建 `wechat-chat-analysis/` 工作区，检查环境、读取已保存的免登录 key、同步解密数据库、导出 Markdown/JSONL、生成中文分析输入和 `ai/` 文件。

### 2. 微信一键多开

这一功能复用内置的 `wechat-multifix` skill，来源：

```text
https://github.com/JNHFlow21/wechat-multifix.git
```

用户可以用短 prompt 让 Agent 完成：

```text
$wechat-toolkit 检查微信多开状态
$wechat-toolkit 安装微信双开
$wechat-toolkit 修复微信多开
$wechat-toolkit 一键打开两个微信
$wechat-toolkit 打开 WeChat 2
```

Agent 内部负责调用 `wechat-multifix` 的流程：复制微信、修改 Bundle ID、重新签名、替换配色图标、检测微信更新后的 Bundle ID 冲突，并报告修复结果。用户不需要理解这些内部步骤。

## 产品原则

- 用户只看到能完成什么，不需要理解 key、Frida、数据库、salt、container 等内部概念。
- 所有微信数据默认保存在本地项目目录。
- 第一次连接需要用户登录微信；之后默认走免登录刷新。
- 多开功能只做用户授权范围内的本机自动化。
- 微信多开安装/修复会写入 `/Applications/WeChat2.app` 等应用路径，执行前需要用户确认。
