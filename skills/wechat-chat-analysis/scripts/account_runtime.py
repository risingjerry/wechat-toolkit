import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def load_sync_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def account_to_runtime(account: dict) -> dict:
    account_root = Path(account["account_root"])
    return {
        "account_key": account.get("account_key", account["account_id"]),
        "account_id": account["account_id"],
        "container_name": account.get("container_name") or (account.get("account_key", "").split(":", 1)[0] if ":" in account.get("account_key", "") else ""),
        "message_db": account.get("message", {}).get("current_output") or account.get("message", {}).get("output"),
        "contact_db": account.get("contact", {}).get("current_output") or account.get("contact", {}).get("output"),
        "wechat_root": str(account_root),
    }


def select_account(manifest: dict, account_id: Optional[str] = None, first_ok: bool = False) -> dict:
    accounts = manifest.get("accounts", [])
    ok_accounts = [
        account for account in accounts
        if account.get("message", {}).get("status") == "ok"
    ]

    if account_id:
        for account in ok_accounts:
            if account.get("account_key") == account_id or account["account_id"] == account_id:
                return account
    elif first_ok and ok_accounts:
        return ok_accounts[0]

    raise ValueError("No matching decrypted account found")


def resolve_runtime(manifest_path: Path, account_id: Optional[str] = None, first_ok: bool = False) -> dict:
    manifest = load_sync_manifest(manifest_path)
    return account_to_runtime(select_account(manifest, account_id=account_id, first_ok=first_ok))


def main():
    parser = argparse.ArgumentParser(description="Resolve a decrypted account runtime config from sync_manifest.json")
    parser.add_argument("--manifest", default="wechat-chat-analysis/decrypted/sync_manifest.json")
    parser.add_argument("--account-id")
    parser.add_argument("--first-ok", action="store_true")
    args = parser.parse_args()

    try:
        runtime = resolve_runtime(Path(args.manifest).expanduser(), account_id=args.account_id, first_ok=args.first_ok)
    except ValueError as exc:
        sys.exit(f"[!] {exc}")

    print(json.dumps(runtime, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
