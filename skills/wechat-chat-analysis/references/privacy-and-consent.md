# Privacy And Consent

Use this skill only for chats the local macOS user is authorized to access.

## Before Export

- Explain that the workflow decrypts local WeChat database copies.
- Confirm the user understands exported Markdown, JSONL, media files, and AI notes may contain private or third-party personal information.
- Keep all data local unless the user explicitly chooses another destination.
- Do not upload exported chats to external services by default.

## Defaults

- `extract_key.py` stores only `rounds`, `salt`, and derived key (`dk`) by default. Use `--include-pw` only for debugging.
- `export_chat.py` and `export_targets.py` omit raw base64 blobs by default. Use `--preserve-raw` only when exact raw-message preservation is required.
- `guided_export.py` asks before copying media attachments and deletes `decrypted/wechat_keys.log` after database sync by default.
- `init_project.py` writes a `.gitignore` that excludes `decrypted/`, `output/`, and logs.

## Distribution Guidance

- Ship the skill folder and scripts, not any `decrypted/` or `output/` folder.
- Tell learners to export only their own account data or chats where they have permission.
- For class demos, use a disposable WeChat account or synthetic data.
- If learners want AI summaries, have the agent read only the selected export folder and avoid sending full chat history to cloud tools without consent.
