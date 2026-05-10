import argparse
import json
import re
from pathlib import Path
from typing import List


MESSAGE_SHARD_RE = re.compile(r"^message/message_\d+\.db$")
MEDIA_SHARD_RE = re.compile(r"^message/media_\d+\.db$")
BIZ_MESSAGE_SHARD_RE = re.compile(r"^message/biz_message_\d+\.db$")

CORE_DATABASES = {
    "contact/contact.db": "contact",
    "session/session.db": "session",
    "favorite/favorite.db": "favorite",
    "sns/sns.db": "sns",
    "message/message_resource.db": "message_resource",
}


def normalize_rel(path: Path) -> str:
    return path.as_posix()


def classify_database(relative_path: str) -> str:
    if MESSAGE_SHARD_RE.match(relative_path):
        return "message_shard"
    if MEDIA_SHARD_RE.match(relative_path):
        return "media_shard"
    if BIZ_MESSAGE_SHARD_RE.match(relative_path):
        return "biz_message_shard"
    if relative_path in CORE_DATABASES:
        return CORE_DATABASES[relative_path]
    if relative_path.endswith("_fts.db"):
        return "fts"
    return "other"


def sync_default(relative_path: str, category: str) -> bool:
    return category in {
        "message_shard",
        "contact",
        "session",
        "favorite",
        "sns",
        "message_resource",
    }


def discover_databases(db_root: Path) -> List[dict]:
    databases: List[dict] = []
    if not db_root.exists():
        return databases

    for path in sorted(db_root.rglob("*.db")):
        if not path.is_file():
            continue
        relative_path = normalize_rel(path.relative_to(db_root))
        category = classify_database(relative_path)
        wal_path = Path(str(path) + "-wal")
        databases.append(
            {
                "relative_path": relative_path,
                "category": category,
                "sync_default": sync_default(relative_path, category),
                "source": str(path),
                "wal_source": str(wal_path) if wal_path.exists() else None,
                "size": path.stat().st_size,
            }
        )
    return databases


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
            databases = discover_databases(db_root)
            message_dbs = [
                db for db in databases
                if db["category"] == "message_shard"
            ]
            message_db = db_root / "message/message_0.db"
            if not message_db.exists() and message_dbs:
                message_db = Path(message_dbs[0]["source"])
            contact_db = db_root / "contact/contact.db"
            if not databases and not message_db.exists() and not contact_db.exists():
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
                    "db_root": str(db_root),
                    "databases": databases,
                    "message_dbs": [db["source"] for db in message_dbs],
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
        print(f"  message_dbs: {len(account.get('message_dbs', []))}")
        print(f"  message_db: {account['message_db'] or '-'}")
        print(f"  contact_db: {account['contact_db'] or '-'}")
        print(f"  databases: {len(account.get('databases', []))}")


if __name__ == "__main__":
    main()
