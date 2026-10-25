# 微信工具箱

本地微信工具箱，支持两类功能：

- 导出和分析本机微信聊天记录
- 安装、打开和修复 macOS 微信多开

所有聊天数据默认保存在你的电脑本地，不会自动上传到任何外部服务。

## 一键安装

在 macOS 终端运行：

```bash
curl -fsSL https://raw.githubusercontent.com/risingjerry/wechat-toolkit/main/install.sh | bash
```

安装完成后，重启 Codex，然后输入：

```text
$wechat-toolkit 初始化微信工具箱
```

安装器会自动：

- 安装微信工具箱 plugin
- 配置 Codex 本地 marketplace
- 启用 `$wechat-toolkit`
- 安装每日凌晨 4 点自动更新任务
- 安装 `wechat-toolkit-update` 更新命令

## 更新

默认安装后会创建一个 macOS LaunchAgent：

```text
~/Library/LaunchAgents/com.dontbesilent.wechat-toolkit-updater.plist
```

它会在每天本地时间凌晨 4 点运行一次 `wechat-toolkit-update --quiet`：

- 有新版本：自动拉取 GitHub 最新版本并同步到 Codex 本地 marketplace。
- 没有新版本：安静退出，不影响使用。
- 更新日志：写入 `~/.codex/marketplaces/wechat-local-toolkit/update.log`。

手动更新：

```bash
wechat-toolkit-update
```

查看安装状态：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py status
```

重新安装或修复自动更新任务：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py install-launchagent
```

关闭自动更新：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py uninstall-launchagent
```

## Release 和更新记录

每次功能更新都会按项目 release 的方式记录：

- `CHANGELOG.md`：维护每个版本的改动摘要。
- GitHub Releases：发布带版本号的 release，方便查看本次更新改了什么。
- `.codex-plugin/plugin.json`：同步提升插件版本号。

查看更新内容：

- [CHANGELOG.md](CHANGELOG.md)
- [GitHub Releases](https://github.com/risingjerry/wechat-toolkit/releases)

发布规则：

1. 功能或行为变化时提升版本号，例如 `0.2.2`。
2. 在 `CHANGELOG.md` 顶部新增本次更新摘要。
3. 推送到 GitHub `main` 后，创建对应 tag 和 GitHub Release。
4. 已安装用户的每日 04:00 自动更新任务会在下一次检查时拉取新版本。

## 功能 1：微信聊天导出与分析

这个功能会在本地创建一个 `wechat-chat-analysis/` 工作区，用来保存解密后的数据库副本、账号隔离导出的 Markdown/JSONL、统计文件、AI 分析输入文件、商机雷达和同步健康摘要。

### 第一次使用

```text
$wechat-toolkit 初始化微信工具箱
```

第一次连接某个微信账号时，需要重新登录一次微信，让工具保存后续免登录更新需要的本地 key：

```text
$wechat-toolkit 第一次连接 WeChat 2，保存免登录 key
```

如果 WeChat 2 已经登录，工具会先退出 WeChat 2，然后重新打开它。你只需要按正常流程重新登录一次。

### 更新本地备份数据库

```text
$wechat-toolkit 更新一下 WeChat 2 的备份数据库
```

之后再次导出聊天时，默认会使用最新同步的本地数据库副本。

工具会保留 WeChat 4.x 的多数据库结构，自动读取每个账号的 `message_*.db` 分片，并把不同账号导出到不同目录，避免 `文件传输助手`、`微信团队` 等同名会话互相覆盖。

### 导出联系人聊天

```text
$wechat-toolkit 导出张三的全部聊天记录
```

增量导出新增消息：

```text
$wechat-toolkit 增量导出张三
```

### 导出群聊

```text
$wechat-toolkit 导出群聊「开心一家人」
```

### 导出文件传输助手

```text
$wechat-toolkit 导出文件传输助手
```

### 生成 AI 分析文件

```text
$wechat-toolkit 重新生成「开心一家人」的 AI 分析文件
```

导出结果通常在：

```text
wechat-chat-analysis/output/_accounts/<container>__<account_id>/
```

每个聊天目录里会包含：

- `messages.jsonl`
- `analysis_input.md`
- `stats.json`
- `manifest.json`
- `markdown/`
- `ai/`

### 查询和健康摘要

```text
$wechat-toolkit 生成今天的微信商机雷达
```

```text
$wechat-toolkit 生成微信同步健康摘要
```

健康摘要默认只包含账号安全标签、同步状态、消息分片数、WAL 状态、导出会话数、导出消息数和失败原因，不包含 key、decrypted 数据库路径、私密账号 ID 或完整聊天记录。

## 功能 2：微信一键多开

这个功能可以创建 `WeChat2.app`、修复微信更新后导致的多开失效，并快速打开多个微信。

### 检查多开状态

```text
$wechat-toolkit 检查微信多开状态
```

### 安装微信双开

```text
$wechat-toolkit 安装微信双开
```

安装时可以选择图标配色：

- 黑色
- 青色
- 紫色
- 橙色
- 深蓝
- 深灰

例如：

```text
$wechat-toolkit 安装微信双开，使用紫色图标
```

### 打开两个微信

```text
$wechat-toolkit 一键打开两个微信
```

只打开 WeChat 2：

```text
$wechat-toolkit 打开 WeChat 2
```

### 修复微信多开

微信自动更新后，`WeChat2.app` 可能打不开。这通常是 Bundle ID 被微信更新覆盖导致的，聊天记录不会因此丢失。

修复：

```text
$wechat-toolkit 修复微信多开
```

修复会重建 `WeChat2.app`，但不会删除：

```text
~/Library/Containers/com.tencent.xinWeChat2/
```

## 隐私说明

聊天导出功能会读取并解密你本机的微信数据库副本。导出的 Markdown、JSONL、媒体文件和 AI 分析文件可能包含你和他人的隐私信息。

请只导出你有权访问的聊天记录。默认情况下，所有数据都保存在本地项目目录中。

## 常见问题

### 安装后没有 `$wechat-toolkit`

重启 Codex 后再试一次。

也可以检查安装状态：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py status
```

### WeChat 2 已经登录，但第一次连接抓不到 key

重新运行：

```text
$wechat-toolkit 第一次连接 WeChat 2，保存免登录 key
```

工具会先退出 WeChat 2，然后重新打开。你重新登录一次即可。

### 微信更新后 WeChat 2 打不开

运行：

```text
$wechat-toolkit 修复微信多开
```

### 不想自动更新

运行：

```bash
python3 ~/.codex/marketplaces/wechat-local-toolkit/plugins/wechat-toolkit/scripts/self_update.py uninstall-launchagent
```
