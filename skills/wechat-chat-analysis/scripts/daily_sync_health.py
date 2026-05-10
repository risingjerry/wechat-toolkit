#!/usr/bin/env python3
"""Write a privacy-safe daily health summary for WeChat sync/export automation."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
VAULT_ROOT = PROJECT_ROOT.parent
DEFAULT_SYNC_MANIFEST = PROJECT_ROOT / "decrypted" / "sync_manifest.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
DEFAULT_REPORT_DIR = DEFAULT_OUTPUT_ROOT / "_reports"
OK_STATUSES = {"ok", "plain"}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(VAULT_ROOT.resolve()))
    except ValueError:
        return path.name


def redact_reason(value: str, limit: int = 180) -> str:
    text = (value or "").splitlines()[0]
    text = re.sub(r"wxid_[A-Za-z0-9_\\-]+", "[WXID_REDACTED]", text)
    text = re.sub(r"/Users/[^\\s'\"]+", "[PATH_REDACTED]", text)
    text = re.sub(r"\b[A-Fa-f0-9]{32,}\b", "[TOKEN_REDACTED]", text)
    return text[:limit]


def account_label(account: dict[str, Any], index: int) -> str:
    return f"{account.get('container_name') or 'account'}#{index + 1}"


def account_export_dir(account: dict[str, Any], output_root: Path) -> Path:
    account_key = account.get("account_key") or account.get("account_id") or ""
    if ":" in account_key:
        dirname = account_key.replace(":", "__")
    else:
        dirname = f"{account.get('container_name') or 'account'}__{account.get('account_id') or account_key}"
    return output_root / "_accounts" / dirname


def summarize_sync(account: dict[str, Any]) -> dict[str, Any]:
    databases = account.get("databases", [])
    status_counts = Counter(database.get("status", "unknown") for database in databases)
    category_counts = Counter(database.get("category", "unknown") for database in databases)
    message_shards = [
        database
        for database in databases
        if database.get("category") == "message_shard" and database.get("status") in OK_STATUSES
    ]
    wal_counts = Counter()
    for database in databases:
        if database.get("category") == "message_shard":
            wal_counts[(database.get("wal") or {}).get("status", "not_recorded")] += 1

    failures = []
    for database in databases:
        status = database.get("status", "unknown")
        if status in OK_STATUSES:
            continue
        failures.append(
            {
                "category": database.get("category", "unknown"),
                "relative_path": database.get("relative_path", ""),
                "status": status,
                "reason": redact_reason(database.get("error") or status),
            }
        )

    if failures:
        sync_status = "partial"
    elif message_shards:
        sync_status = "ok"
    else:
        sync_status = "failed"

    return {
        "status": sync_status,
        "synced_at": account.get("synced_at", ""),
        "database_total": len(databases),
        "database_status_counts": dict(status_counts),
        "database_category_counts": dict(category_counts),
        "message_shards_ok": len(message_shards),
        "wal_status_counts": dict(wal_counts),
        "failures": failures,
    }


def summarize_exports(account: dict[str, Any], output_root: Path) -> dict[str, Any]:
    account_dir = account_export_dir(account, output_root)
    manifests = sorted(account_dir.glob("*/manifest.json")) if account_dir.is_dir() else []
    chat_type_counts: Counter[str] = Counter()
    message_total = 0
    multi_shard_conversations = 0
    last_exported = ""
    unreadable = 0

    for manifest_path in manifests:
        manifest = load_json(manifest_path, {})
        if not manifest:
            unreadable += 1
            continue
        chat_type_counts[manifest.get("target_type", "unknown")] += 1
        message_total += int(manifest.get("message_count") or 0)
        if len(manifest.get("source_shards") or []) > 1:
            multi_shard_conversations += 1
        exported_at = str(manifest.get("exported_at") or "")
        if exported_at > last_exported:
            last_exported = exported_at

    return {
        "status": "ok" if manifests else "missing",
        "conversation_count": len(manifests),
        "message_count": message_total,
        "chat_type_counts": dict(chat_type_counts),
        "multi_shard_conversation_count": multi_shard_conversations,
        "last_exported_at": last_exported,
        "unreadable_manifest_count": unreadable,
    }


def report_paths(report_dir: Path, report_date: datetime) -> dict[str, str]:
    date_slug = report_date.strftime("%Y-%m-%d")
    year, week, _ = report_date.isocalendar()
    week_slug = f"{year}-W{week:02d}"
    candidates = {
        "daily_markdown": report_dir / f"opportunity_radar_{date_slug}.md",
        "daily_json": report_dir / f"opportunity_radar_{date_slug}.json",
        "weekly_markdown": report_dir / f"opportunity_radar_weekly_{week_slug}.md",
        "weekly_json": report_dir / f"opportunity_radar_weekly_{week_slug}.json",
    }
    return {key: safe_rel(path) for key, path in candidates.items() if path.exists()}


def build_health(sync_manifest: Path, output_root: Path, report_dir: Path, report_date: datetime) -> dict[str, Any]:
    manifest = load_json(sync_manifest, {})
    included = []
    for account in manifest.get("accounts", []):
        sync = summarize_sync(account)
        exports = summarize_exports(account, output_root)
        if sync.get("message_shards_ok", 0) == 0 and exports.get("status") != "ok":
            continue
        included.append((account, sync, exports))

    accounts = []
    for index, (account, sync, exports) in enumerate(included):
        failures = [*sync.get("failures", [])]
        if exports.get("status") != "ok":
            failures.append({"category": "export", "relative_path": "", "status": exports.get("status"), "reason": "no account-scoped exports found"})
        accounts.append(
            {
                "account_scope": account_label(account, index),
                "sync": sync,
                "exports": exports,
                "failure_count": len(failures),
                "failures": failures,
            }
        )

    overall_status = "ok"
    if not accounts:
        overall_status = "failed"
    elif any(account["sync"]["status"] == "failed" or account["exports"]["status"] != "ok" for account in accounts):
        overall_status = "failed"
    elif any(account["failure_count"] for account in accounts):
        overall_status = "partial"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_date": report_date.strftime("%Y-%m-%d"),
        "status": overall_status,
        "account_count": len(accounts),
        "accounts": accounts,
        "radar_reports": report_paths(report_dir, report_date),
        "privacy": {
            "account_ids": "redacted",
            "database_paths": "redacted",
            "message_content": "not_included",
        },
    }


def markdown_table(rows: list[list[str]], headers: list[str]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(health: dict[str, Any]) -> str:
    rows = []
    for account in health.get("accounts", []):
        sync = account.get("sync", {})
        exports = account.get("exports", {})
        wal = ", ".join(f"{key}:{value}" for key, value in sync.get("wal_status_counts", {}).items()) or "none"
        failures = "; ".join(f"{item.get('category')}:{item.get('status')}" for item in account.get("failures", [])[:4])
        rows.append(
            [
                account.get("account_scope", ""),
                sync.get("status", ""),
                sync.get("message_shards_ok", 0),
                wal,
                exports.get("conversation_count", 0),
                exports.get("message_count", 0),
                failures or "none",
            ]
        )

    lines = [
        f"# WeChat Daily Sync Health - {health.get('report_date')}",
        "",
        f"- Overall status: {health.get('status')}",
        f"- Accounts: {health.get('account_count')}",
        "",
        markdown_table(rows, ["Account", "Sync", "Message shards", "WAL status", "Conversations", "Messages", "Failures"]),
        "",
        "## Radar Reports",
        "",
    ]
    reports = health.get("radar_reports", {})
    if reports:
        for key, path in reports.items():
            lines.append(f"- {key}: `{path}`")
    else:
        lines.append("- none")
    lines.extend(["", "> Privacy: account ids, database paths, keys, and message content are not included in this health report.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate privacy-safe WeChat daily sync health summaries")
    parser.add_argument("--sync-manifest", default=str(DEFAULT_SYNC_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--date", default="")
    args = parser.parse_args()

    report_date = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.now()
    report_dir = Path(args.report_dir).expanduser()
    report_dir.mkdir(parents=True, exist_ok=True)
    health = build_health(
        sync_manifest=Path(args.sync_manifest).expanduser(),
        output_root=Path(args.output_root).expanduser(),
        report_dir=report_dir,
        report_date=report_date,
    )

    date_slug = report_date.strftime("%Y-%m-%d")
    json_path = report_dir / f"daily_sync_health_{date_slug}.json"
    md_path = report_dir / f"daily_sync_health_{date_slug}.md"
    json_path.write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(health), encoding="utf-8")
    print(json.dumps({"status": health["status"], "json": safe_rel(json_path), "markdown": safe_rel(md_path)}, ensure_ascii=False))
    return 0 if health["status"] in {"ok", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
