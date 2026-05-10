---
name: wechat-chat-analysis
description: "This skill should be used when the user wants a local macOS WeChat chat export workflow: initialize a self-contained project, check dependencies, capture WeChat SQLCipher keys with Frida in spawn mode only for first connection, sync multi-account/multi-shard databases from the local key store, export account-scoped Markdown/JSONL/media locally, query chats/favorites/local Moments, and generate AI-ready analysis, radar, and health reports."
license: Proprietary
metadata:
  version: 0.6.0
  compatibility: "macOS with WeChat Desktop app, Python 3.9+, Frida, pycryptodome, zstandard, and a local project workspace initialized from this skill."
  created: 2026-04-21
  tags: [wechat, export, markdown, obsidian, ai, local, shortlist, shared]
---

# WeChat Chat Analysis

Run a local WeChat export workflow. This skill is designed to be copied into a learner's own project workspace before exporting; do not run exports from the installed skill folder.

Read `references/privacy-and-consent.md` before helping a user export chats.

## 学员安装后怎么用

学员不需要记 Python 命令。安装好 skill 和本地项目后，只需要在 Agent 里用很短的自然语言说目标，Agent 负责在后台执行检查、同步、解密、导出和验证。

这个 skill 可以做：

- 初始化本地微信聊天导出项目
- 检查 macOS 微信、依赖和本地数据库是否可用
- 第一次登录微信后保存免登录 key
- 以后免登录更新/备份本地解密数据库
- 导出联系人、群聊、文件传输助手的聊天记录
- 增量导出新增聊天
- 查询会话、历史、搜索、新消息、收藏、本地朋友圈缓存和账号级 enrichment 摘要
- 生成中文 AI 分析输入和 `ai/` 分析文件
- 生成账号隔离的商机雷达和每日同步健康摘要

学员可以直接这样说：

```text
$wechat-chat-analysis 初始化一个微信聊天导出项目
```

```text
$wechat-chat-analysis 检查一下我的微信导出环境
```

```text
$wechat-chat-analysis 第一次连接 WeChat 2，保存免登录 key
```

```text
$wechat-chat-analysis 更新一下 WeChat 2 的备份数据库
```

```text
$wechat-chat-analysis 导出张三的全部聊天记录
```

```text
$wechat-chat-analysis 增量导出李四
```

```text
$wechat-chat-analysis 导出群聊「开心一家人」
```

```text
$wechat-chat-analysis 重新生成「开心一家人」的 AI 分析文件
```

```text
$wechat-chat-analysis 列出 WeChat 2 里可以导出的联系人和群聊
```

典型例子：

```text
用户：$wechat-chat-analysis 更新一下 WeChat 2 的备份数据库
Agent：自动使用已保存的 key_store.json 免登录同步数据库，生成新的时间戳快照，更新 decrypted/current/，最后告诉用户同步是否成功和最新快照路径。
```

第一次使用时，Agent 可能会让学员登录一次微信。登录后只需要等待，不需要点击联系人、群聊或文件传输助手。只要 `decrypted/key_store.json` 保存成功，后续更新数据库和增量导出默认走免登录模式。

## Standard folders

- Decrypted DBs: `wechat-chat-analysis/decrypted/`
- Current decrypted DBs: `wechat-chat-analysis/decrypted/current/`
- Timestamped DB snapshots: `wechat-chat-analysis/decrypted/snapshots/<YYYY-MM-DD_HHMMSS>/`
- Exported chats: `wechat-chat-analysis/output/_accounts/<container>__<account_id>/`
- Reports: `wechat-chat-analysis/output/_reports/`
- Scripts: `wechat-chat-analysis/scripts/`
- Temporary key log: `wechat-chat-analysis/decrypted/wechat_keys.log`
- Persistent key store: `wechat-chat-analysis/decrypted/key_store.json`

## Recommended learner workflow

The agent should run these setup and maintenance commands for the learner. Do not make the learner memorize or manually execute Python commands unless they explicitly ask for command-line instructions.

### 1. Initialize a local workspace

From the parent folder where the learner wants to keep their local export project:

Run:

```bash
python3 ~/.agents/skills/wechat-chat-analysis/scripts/init_project.py --workspace . --install-deps
```

Or use the shell installer:

```bash
~/.agents/skills/wechat-chat-analysis/scripts/install.sh .
```

This creates:

- `wechat-chat-analysis/scripts/`
- `wechat-chat-analysis/decrypted/`
- `wechat-chat-analysis/output/`
- `wechat-chat-analysis/.gitignore`

If the skill is installed under another agent root, use that path instead, for example `~/.codex/skills/wechat-chat-analysis/scripts/init_project.py`.

### 2. Run the doctor

```bash
cd wechat-chat-analysis
python3 scripts/doctor.py
```

If dependencies are missing:

```bash
python3 scripts/doctor.py --install-deps
```

### 3. Run the guided export wizard

```bash
python3 scripts/guided_export.py
```

The wizard will:

1. show a privacy/consent notice
2. capture keys in spawn mode if no decrypted account is ready; the learner only needs to log in and wait
3. import captured keys into `decrypted/key_store.json`
4. sync/decrypt local message and contact DB copies into timestamped snapshots and `decrypted/current/`
5. delete temporary `decrypted/wechat_keys.log` after sync
6. let the user choose account, target class, shortlist keywords, and target names
7. export Markdown/JSONL locally under `output/_accounts/<container>__<account_id>/<target-name>/`
8. build `analysis_input.md` and `stats.json`

Use raw preservation only when needed:

```bash
python3 scripts/guided_export.py --preserve-raw
```

For multi-open WeChat installs, first list apps and containers:

```bash
python3 scripts/wechat_apps.py
python3 scripts/discover_databases.py
```

Then target one bundle/container explicitly:

```bash
python3 scripts/guided_export.py --bundle-id com.tencent.xinWeChat2
```

If the app bundle id and data container name differ, pass both:

```bash
python3 scripts/guided_export.py \
  --wechat-app "/Applications/WeChat 2.app" \
  --container-name com.tencent.xinWeChat2
```

Use the same Python executable for initialization, doctor, capture, sync, and export. On macOS with multiple Python installs, prefer the executable reported by `init_project.py` or `doctor.py`.

## Agent workflow

Prefer the guided workflow for learners. Use the lower-level scripts only when the user asks for a specific target, batch export, or debugging.

### 1. Try the interactive driver first

Inside a project workspace:

```bash
python3 scripts/interactive_skill_driver.py
```

If it returns `status: ready`, use its `runtime` block.

If it returns `status: blocked`, move to key capture.

### 2. Capture keys in spawn mode only

Always use spawn mode:

```bash
python3 scripts/extract_key.py --mode spawn
```

If the user wants a clean key log:

```bash
python3 scripts/extract_key.py --mode spawn --reset
```

For multi-open installs, target the intended app explicitly:

```bash
python3 scripts/extract_key.py \
  --mode spawn \
  --reset \
  --bundle-id com.tencent.xinWeChat2 \
  --wechat-app /Applications/WeChat2.app
```

If enough keys have been captured before the wait timer ends, Ctrl-C is safe; the script keeps captured keys and detaches. If Frida attach times out, retry after quitting the target WeChat app. The script retries attach automatically.

Then ask the user to log into WeChat and keep it open. Do not ask them to click a contact, group, or 文件传输助手 by default. The capture script stops early after it sees enough usable SQLCipher keys. Only if the later sync step cannot decrypt the intended account should you ask the learner to rerun capture and keep that account open longer.

Captured keys are imported into `decrypted/key_store.json`. This is the default long-term mode. Future syncs should first try the key store and should not ask the learner to log in again unless the target database salt/key is missing or changed.

### 3. Sync databases

Run:

```bash
python3 scripts/sync_databases.py --keys-log decrypted/wechat_keys.log
```

For later refreshes, reuse the persistent key store without logging in:

```bash
python3 scripts/sync_databases.py
```

For a specific multi-open container:

```bash
python3 scripts/sync_databases.py \
  --keys-log decrypted/wechat_keys.log \
  --container-name com.tencent.xinWeChat2
```

Read `decrypted/sync_manifest.json`.
The manifest points to the latest timestamped snapshot and to `decrypted/current/`. Use `current_output` / `decrypted/current/` for normal exports. Use `decrypted/snapshots/<timestamp>/` when you need to inspect a specific sync time.
Modern WeChat can spread messages across `message/message_0.db`, `message/message_1.db`, and future shards. Always use all `message_shard` entries from the manifest, and keep favorites, local cached Moments, contacts, sessions, and message resources account-scoped.

If some accounts still fail, report which salts/accounts are blocked and stop there.
It is normal for one multi-open container to contain multiple account folders where only the opened/logged-in account decrypts.

### 4. Select account

If multiple decrypted accounts exist, ask the user which one to use.

Resolve the runtime with:

```bash
python3 scripts/account_runtime.py --manifest decrypted/sync_manifest.json --account-id <account_key>
```

### 5. Export with account isolation

Do not export two accounts into the same flat `output/` folder. Use `export_targets.py` with the sync manifest and an account-scoped output root:

```bash
python3 scripts/export_targets.py \
  --sync-manifest decrypted/sync_manifest.json \
  --account-id <account_key> \
  --output-dir output/_accounts/<container>__<account_id> \
  --name "张三" \
  --incremental \
  --no-attachments
```

For natural-language `$wechat-toolkit chat export`, the wrapper resolves the selected account and writes to `_accounts/<container>__<account_id>/` automatically.

### 6. Query, radar, and health summaries

Use concise account-scoped queries by default:

```bash
python3 scripts/query_account.py --all-accounts --json sessions
python3 scripts/query_account.py --all-accounts --json search "关键词"
python3 scripts/query_account.py --all-accounts --json favorites -n 10
python3 scripts/query_account.py --all-accounts --json sns-feed -n 10
python3 scripts/query_account.py --all-accounts --json enrichment-summary
```

Generate opportunity reports directly from account-scoped exports:

```bash
python3 scripts/opportunity_radar.py --output-root output
```

Generate a privacy-safe daily sync/export health summary:

```bash
python3 scripts/daily_sync_health.py \
  --sync-manifest decrypted/sync_manifest.json \
  --output-root output
```

Health summaries include safe account labels, sync status, message shard counts, WAL status counts, exported conversation/message counts, and failure reasons. They must not include keys, decrypted database paths, private account identifiers, raw XML, or full chat logs.

### 5. Ask export choices with shortlist + refine

Ask the user for the first choices:

Question A — target classes:
- Contacts (Recommended)
- Groups
- Filehelper
- Everything

Question B — export mode:
- Shortlist by names (Recommended)
- Export all selected classes
- Incremental only
- Full refresh

If the user chooses shortlist flow, do this:

1. Ask for one or more search keywords.
2. Run:

```bash
python3 scripts/shortlist_targets.py \
  --sync-manifest decrypted/sync_manifest.json \
  --account-id <account_key> \
  --target-type <contact/group/filehelper> \
  --query <keyword>
```

3. Show the returned shortlist back to the user.
4. Let the user refine again if the shortlist is too broad.
5. When the shortlist is narrow enough, ask which names to export.

Do not dump hundreds of targets at once.

### 6. Export

Use `export_targets.py` with sync manifest, account key, and the chosen flags.

Examples:

```bash
python3 scripts/export_targets.py \
  --sync-manifest decrypted/sync_manifest.json \
  --account-id "com.tencent.xinWeChat:wxid_xxx" \
  --contacts --name "FRED"
```

```bash
python3 scripts/export_targets.py \
  --sync-manifest decrypted/sync_manifest.json \
  --account-id "com.tencent.xinWeChat:wxid_xxx" \
  --everything --incremental
```

By default exports omit raw base64 message/source blobs. Add `--preserve-raw` only for exact forensic preservation.
Empty conversations or targets with no `Msg_<hash>` table should still export a valid empty bundle.
By default each target exports directly under `output/<target-name>/`. If there is a naming collision, the script appends a short id hash. Use `--include-id-in-slug` only when you explicitly want legacy id-in-folder names.

### 7. Generate AI files

There are two phases:

#### Phase A — write/update support files
Run:

```bash
python3 scripts/run_ai_analysis.py --export-dir <dir>
```

This keeps the `ai/` folder structure in place.

#### Phase B — write real summary content at runtime
For each exported target:

1. Run:

```bash
python3 scripts/select_ai_inputs.py --export-dir <dir>
```

2. Read the returned `analysis_input`, `stats`, `state`, and selected `day_files`.
3. Based on `target_type`, write real AI outputs directly:

- group:
  - `ai/daily_digest/<day>.md`
  - `ai/weekly_topics.md`
  - `ai/action_items.md`
  - `ai/high_signal_digest.md`
- contact:
  - `ai/relationship_brief.md`
  - `ai/recent_changes.md`
  - `ai/followups.md`
  - `ai/high_value_notes.md`
- filehelper:
  - `ai/inbox_digest.md`

AI files should be written in Chinese by default, because learner-facing summaries are expected to be readable by Chinese learners. Keep filenames stable for scripts, but use Chinese headings and Chinese summary content inside the files unless the user explicitly asks for another language.
Do not leave placeholder text in those files after runtime generation.
Use the exported data to write real content.
For keyword/stat summaries, prefer readable Markdown content and filter XML/CDATA/key/id noise before using the statistics as AI context.

### 8. Repair legacy metadata if needed

If old export manifests/state files contain stale attachment paths, run:

```bash
python3 scripts/repair_export_metadata.py
```

## Distribution checklist

- Ship this skill folder with `SKILL.md`, `requirements.txt`, `scripts/`, `references/`, and `agents/`.
- Do not ship any `decrypted/`, `output/`, `wechat_keys.log`, or learner chat data.
- Do not ship `key_store.json`; it contains sensitive derived keys.
- Tell learners to run `init_project.py` first; the installed skill folder is the template, not the export workspace.
- Ask learners to use macOS WeChat Desktop and quit any running WeChat before spawn-mode key capture.
- For multi-open WeChat installs, have learners select by `container_name` / bundle id, not by contact name alone.
- For demonstrations, use synthetic chats or a disposable account.

## Output expectations

Report briefly:
- which account was decrypted
- which WeChat container/bundle was used when multiple WeChat installs exist
- which targets were shortlisted
- which targets were exported
- where the export folders are
- whether this was full or incremental
- whether real AI summaries were written

## Important rules

- Always prefer spawn mode for key capture.
- Never promise that every account can be decrypted without user interaction.
- Keep all generated data inside the user's local `wechat-chat-analysis/` project.
- Prefer file-link-first media handling over unreliable inline decoding.
- Use shortlist + refine instead of dumping huge target lists.
- When generating AI outputs, write real summary content, not placeholders.
- Never read or summarize exported chats unless the user explicitly asks for analysis of selected export folders.
- Do not upload exported chats or key logs to external services by default.
