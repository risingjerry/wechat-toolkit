import argparse
import json
import sys
from pathlib import Path


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict) -> dict:
    issues = []
    accounts = manifest.get("accounts", [])
    if not accounts:
        issues.append("manifest has no accounts")

    summaries = []
    for index, account in enumerate(accounts):
        account_label = account.get("container_name") or f"account[{index}]"
        display_label = f"{account_label}#{index + 1}"
        databases = account.get("databases", [])
        if not databases:
            issues.append(f"{display_label}: missing per-database entries")
            continue

        message_shards = [
            database for database in databases
            if database.get("category") == "message_shard"
        ]
        ok_message_shards = [
            database for database in message_shards
            if database.get("status") in {"ok", "plain"}
        ]
        if not ok_message_shards:
            issues.append(f"{display_label}: no synced message shards")

        for database in databases:
            if "key_prefix" in database:
                issues.append(f"{display_label}: database manifest exposes key_prefix")
            if database.get("status") == "ok" and "wal" not in database:
                issues.append(f"{display_label}: {database.get('relative_path')} missing WAL status")

        summaries.append(
            {
                "account": display_label,
                "databases": len(databases),
                "message_shards": len(message_shards),
                "ok_message_shards": len(ok_message_shards),
                "errors": sum(1 for database in databases if database.get("status") == "error"),
            }
        )

    return {
        "ok": not issues,
        "issues": issues,
        "summaries": summaries,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate the multi-database WeChat sync manifest")
    parser.add_argument("--manifest", default="wechat-chat-analysis/decrypted/sync_manifest.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = validate_manifest(load_manifest(Path(args.manifest).expanduser()))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("sync manifest verification:", "OK" if report["ok"] else "FAILED")
        for summary in report["summaries"]:
            print(
                f"- {summary['account']}: databases={summary['databases']} "
                f"message_shards={summary['ok_message_shards']}/{summary['message_shards']} "
                f"errors={summary['errors']}"
            )
        for issue in report["issues"]:
            print(f"  issue: {issue}")

    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
