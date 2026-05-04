import argparse
import json
from pathlib import Path
from typing import List

from account_runtime import load_sync_manifest
from list_targets import list_targets

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DECRYPTED_ROOT = PROJECT_ROOT / "decrypted"
OUTPUT_ROOT = PROJECT_ROOT / "output"
SYNC_MANIFEST = DECRYPTED_ROOT / "sync_manifest.json"


def choose_account(accounts: List[dict], preferred: str = "") -> dict:
    ok_accounts = [account for account in accounts if account.get("message", {}).get("status") == "ok"]
    if preferred:
        for account in ok_accounts:
            if account.get("account_key") == preferred or account.get("account_id") == preferred:
                return account
    return ok_accounts[0] if ok_accounts else {}


def summarize_targets(message_db: Path, contact_db: Path) -> dict:
    targets = list_targets(message_db, contact_db)
    summary = {"contact": 0, "group": 0, "filehelper": 0}
    for target in targets:
        summary[target["target_type"]] += 1
    return {
        "counts": summary,
        "examples": {
            kind: [target["target_name"] for target in targets if target["target_type"] == kind][:10]
            for kind in summary
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Interactive driver for the WeChat export skill")
    parser.add_argument("--sync-manifest", default=str(SYNC_MANIFEST))
    parser.add_argument("--account-id")
    args = parser.parse_args()

    manifest_path = Path(args.sync_manifest).expanduser()
    if not manifest_path.exists():
        print(json.dumps({
            "status": "blocked",
            "reason": f"Sync manifest not found: {manifest_path}",
            "next_step": "先运行 extract_key.py --mode spawn，登录微信并等待；完成后运行 sync_databases.py。之后有 key_store.json 时可直接运行 sync_databases.py 免登录刷新。",
        }, ensure_ascii=False, indent=2))
        return

    try:
        manifest = load_sync_manifest(manifest_path)
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "blocked",
            "reason": f"Sync manifest is not valid JSON: {exc}",
            "next_step": "Rerun sync_databases.py to rebuild decrypted/sync_manifest.json",
        }, ensure_ascii=False, indent=2))
        return
    except OSError as exc:
        print(json.dumps({
            "status": "blocked",
            "reason": f"Unable to read sync manifest: {exc}",
            "next_step": "Check file permissions or rerun sync_databases.py",
        }, ensure_ascii=False, indent=2))
        return

    account = choose_account(manifest.get("accounts", []), preferred=args.account_id or "")
    if not account:
        print(json.dumps({
            "status": "blocked",
            "reason": "No decrypted accounts available",
            "next_step": "先运行 extract_key.py --mode spawn，登录微信并等待；完成后运行 sync_databases.py。之后有 key_store.json 时可直接运行 sync_databases.py 免登录刷新。",
        }, ensure_ascii=False, indent=2))
        return

    runtime = {
        "account_key": account.get("account_key"),
        "account_id": account.get("account_id"),
        "message_db": account.get("message", {}).get("current_output") or account.get("message", {}).get("output"),
        "contact_db": account.get("contact", {}).get("current_output") or account.get("contact", {}).get("output"),
        "wechat_root": account.get("account_root"),
        "output_root": str(OUTPUT_ROOT),
    }
    summary = summarize_targets(Path(runtime["message_db"]), Path(runtime["contact_db"]))
    print(json.dumps({
        "status": "ready",
        "runtime": runtime,
        "target_summary": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
