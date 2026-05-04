import argparse
import json
from pathlib import Path
from typing import List


def discover_accounts() -> List[dict]:
    container_root = Path.home() / "Library/Containers"
    accounts: List[dict] = []

    for container in sorted(container_root.glob("com.tencent.xinWeChat*")):
        docs_root = container / "Data/Documents/xwechat_files"
        if not docs_root.exists():
            continue
        for account_root in sorted(docs_root.iterdir()):
            if not account_root.is_dir():
                continue
            db_root = account_root / "db_storage"
            message_db = db_root / "message/message_0.db"
            contact_db = db_root / "contact/contact.db"
            if not message_db.exists() and not contact_db.exists():
                continue
            account_id = account_root.name
            container_name = container.name
            account_key = f"{container_name}:{account_id}"
            accounts.append(
                {
                    "account_key": account_key,
                    "account_id": account_id,
                    "container": str(container),
                    "container_name": container_name,
                    "account_root": str(account_root),
                    "message_db": str(message_db) if message_db.exists() else None,
                    "contact_db": str(contact_db) if contact_db.exists() else None,
                }
            )

    return sorted(accounts, key=lambda item: (item["account_id"], item["container_name"]))


def main():
    parser = argparse.ArgumentParser(description="Discover WeChat database locations by account")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    accounts = discover_accounts()
    if args.json:
        print(json.dumps(accounts, ensure_ascii=False, indent=2))
        return

    for account in accounts:
        print(f"account_key={account['account_key']}")
        print(f"  account_id: {account['account_id']}")
        print(f"  container: {account['container']}")
        print(f"  message_db: {account['message_db'] or '-'}")
        print(f"  contact_db: {account['contact_db'] or '-'}")


if __name__ == "__main__":
    main()
