# Changelog

All notable changes to WeChat Toolkit are recorded here. Releases are also published on GitHub so installed users can see what changed before or after updating.

## 0.2.2 - 2026-05-10

- Documented the release workflow and where to read update notes.
- Changed the installed auto-updater from a rolling 24-hour interval to a fixed daily 04:00 local-time LaunchAgent schedule.
- Added the updater schedule to `self_update.py status`.
- Clarified that no-op update checks are expected when the plugin is already current.

## 0.2.1 - 2026-05-10

- Added multi-account and multi-message-shard WeChat export support.
- Preserved account isolation under `output/_accounts/<container>__<account_id>/`.
- Added account-scoped query support for chats, favorites, local cached Moments, and enrichment summaries.
- Added opportunity radar and privacy-safe daily sync health reports.
- Updated the `$wechat-toolkit` wrapper to export into account-scoped folders and redact private account ids in command output.

## 0.2.0 - 2026-05-09

- Added the productized WeChat Toolkit plugin packaging.
- Added local installer, Codex marketplace registration, and manual update command.
- Added chat export/analysis workflows and WeChat multi-open workflows.
