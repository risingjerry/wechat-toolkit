import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence


def decode_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def load_contacts(contact_db: Optional[Path]) -> Dict[str, dict]:
    contacts = {}
    if not contact_db or not contact_db.exists():
        return contacts

    conn = sqlite3.connect(str(contact_db))
    conn.row_factory = sqlite3.Row
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    candidate_queries = [
        "SELECT username AS user_name, nick_name AS nickname, remark, alias FROM contact",
        "SELECT user_name, nickname, remark, alias FROM contact",
        "SELECT user_name, nick_name AS nickname, remark, alias FROM contact",
        "SELECT username AS user_name, nickname, remark, alias FROM contact",
        "SELECT username AS user_name, nick_name AS nickname, remark_name AS remark, alias FROM contact",
        "SELECT user_name, nick_name AS nickname, remark_name AS remark, alias FROM contact",
    ]

    if "contact" in tables:
        for query in candidate_queries:
            try:
                for row in conn.execute(query):
                    user_name = decode_text(row["user_name"])
                    contacts[user_name] = {
                        "user_name": user_name,
                        "nickname": decode_text(row["nickname"]),
                        "remark": decode_text(row["remark"]),
                        "alias": decode_text(row["alias"]),
                    }
                if contacts:
                    break
            except sqlite3.OperationalError:
                continue

    conn.close()
    return contacts


def display_name(user_name: str, contacts: Dict[str, dict]) -> str:
    user_name = decode_text(user_name)
    if user_name == "filehelper":
        return "文件传输助手"
    info = contacts.get(user_name, {})
    for key in ("remark", "nickname", "alias"):
        value = decode_text(info.get(key, "")).strip()
        if value:
            return value
    return user_name


def classify_target(user_name: str) -> str:
    if user_name == "filehelper":
        return "filehelper"
    if user_name.endswith("@chatroom"):
        return "group"
    return "contact"


def list_targets(message_db: Path, contact_db: Optional[Path], message_dbs: Optional[Sequence[Path]] = None) -> List[dict]:
    db_paths = [Path(path) for path in (message_dbs or [message_db])]
    contacts = load_contacts(contact_db) if contact_db else {}

    sessions = {}
    for db_path in db_paths:
        if not db_path.exists():
            continue
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT rowid, user_name, is_session FROM Name2Id ORDER BY user_name"):
            user_name = decode_text(row["user_name"])
            target_hash = hashlib.md5(user_name.encode()).hexdigest()
            table_name = f"Msg_{target_hash}"
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                continue
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            last_ts = conn.execute(f"SELECT MAX(create_time) FROM {table_name}").fetchone()[0]
            existing = sessions.setdefault(
                user_name,
                {
                    "target_id": user_name,
                    "target_name": display_name(user_name, contacts),
                    "target_type": classify_target(user_name),
                    "is_session": row["is_session"],
                    "message_count": 0,
                    "last_timestamp": None,
                    "source_shards": [],
                },
            )
            existing["message_count"] += count
            if last_ts and (not existing["last_timestamp"] or last_ts > existing["last_timestamp"]):
                existing["last_timestamp"] = last_ts
            existing["is_session"] = max(existing.get("is_session") or 0, row["is_session"] or 0)
            existing["source_shards"].append(str(db_path))
        conn.close()

    if "filehelper" not in sessions:
        sessions["filehelper"] = {
            "target_id": "filehelper",
            "target_name": "文件传输助手",
            "target_type": "filehelper",
            "is_session": 1,
            "message_count": 0,
            "last_timestamp": None,
        }

    results = list(sessions.values())
    results.sort(key=lambda item: (item["target_type"], (item["target_name"] or "").lower(), item["target_id"]))
    return results


def main():
    parser = argparse.ArgumentParser(description="List WeChat chat targets by readable name")
    parser.add_argument("--message-db", required=True)
    parser.add_argument("--message-db-extra", action="append", dest="message_db_extra", help="Additional decrypted message shard")
    parser.add_argument("--contact-db")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--target-type", choices=["contact", "group", "filehelper"])
    args = parser.parse_args()

    message_db = Path(args.message_db).expanduser()
    if not message_db.exists():
        sys.exit(f"[!] message db not found: {message_db}")

    contact_db = Path(args.contact_db).expanduser() if args.contact_db else None
    message_dbs = [message_db] + [Path(path).expanduser() for path in (args.message_db_extra or [])]
    targets = list_targets(message_db, contact_db, message_dbs=message_dbs)
    if args.target_type:
        targets = [target for target in targets if target["target_type"] == args.target_type]

    if args.json:
        print(json.dumps(targets, ensure_ascii=False, indent=2))
        return

    for index, target in enumerate(targets, start=1):
        print(
            f"{index:03d}. [{target['target_type']}] {target['target_name']} | id={target['target_id']} | "
            f"messages={target['message_count']} | last_ts={target['last_timestamp']}"
        )


if __name__ == "__main__":
    main()
