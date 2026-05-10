import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from decrypt_db import apply_wal, decrypt_file, is_plain_sqlite, read_salt_hex, resolve_key_for_db
from discover_databases import discover_accounts
from key_store import import_keys_log


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_KEYS_LOG = PROJECT_ROOT / "decrypted" / "wechat_keys.log"
DEFAULT_KEY_STORE = PROJECT_ROOT / "decrypted" / "key_store.json"
DEFAULT_DECRYPTED_ROOT = PROJECT_ROOT / "decrypted"


def timestamp_slug(value: datetime) -> str:
    return value.strftime("%Y-%m-%d_%H%M%S")


def tighten_permissions(*paths: Path) -> None:
    for path in paths:
        try:
            if path.exists():
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
        except OSError:
            continue


def safe_account_dir_name(account: dict) -> str:
    account_id = account["account_id"]
    account_key = account.get("account_key", account_id)
    return account_key.replace(":", "__")


def db_output_path(account_dir: Path, relative_path: str) -> Path:
    return account_dir / relative_path


def copy_plain_database(source_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, out_path)


def legacy_database_result(result: dict, relative_path: str) -> dict:
    for database in result.get("databases", []):
        if database.get("relative_path") == relative_path:
            return {
                "status": database.get("status"),
                "source": database.get("source"),
                "output": database.get("output"),
                "current_output": database.get("current_output"),
                "salt": database.get("salt"),
                "size": database.get("size"),
                "snapshot_at": database.get("snapshot_at"),
                "wal": database.get("wal"),
            }
    return {"status": "missing_source"}


def summarize_databases(databases: List[dict]) -> dict:
    by_status: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    for database in databases:
        by_status[database.get("status", "unknown")] = by_status.get(database.get("status", "unknown"), 0) + 1
        by_category[database.get("category", "unknown")] = by_category.get(database.get("category", "unknown"), 0) + 1
    return {
        "total": len(databases),
        "by_status": by_status,
        "by_category": by_category,
        "message_shards_ok": sum(
            1
            for database in databases
            if database.get("category") == "message_shard" and database.get("status") in {"ok", "plain"}
        ),
    }


def sync_database_entry(
    db_entry: dict,
    account_dir: Path,
    current_account_dir: Path,
    keys_log: str,
    key_store: Path,
    sync_time: datetime,
) -> dict:
    source_path = Path(db_entry["source"])
    relative_path = db_entry["relative_path"]
    out_path = db_output_path(account_dir, relative_path)
    current_path = db_output_path(current_account_dir, relative_path)
    base_result = {
        "relative_path": relative_path,
        "category": db_entry.get("category"),
        "sync_default": bool(db_entry.get("sync_default")),
        "source": str(source_path),
        "output": str(out_path),
        "current_output": str(current_path),
        "snapshot_at": sync_time.isoformat(),
        "source_size": source_path.stat().st_size if source_path.exists() else None,
        "source_mtime": source_path.stat().st_mtime if source_path.exists() else None,
    }

    if not source_path.exists():
        return {**base_result, "status": "missing_source"}

    try:
        if is_plain_sqlite(str(source_path)):
            copy_plain_database(source_path, out_path)
            copy_plain_database(out_path, current_path)
            return {
                **base_result,
                "status": "plain",
                "size": out_path.stat().st_size,
                "wal": {"status": "skipped_plaintext"},
            }

        salt_hex = read_salt_hex(str(source_path))
        key_hex = resolve_key_for_db(str(source_path), keys_log=keys_log, key_store=str(key_store))
        decrypt_file(
            str(source_path),
            str(out_path),
            keys_log=keys_log,
            key=key_hex,
            key_store=str(key_store),
            apply_wal_frames=False,
        )
        wal_result = apply_wal(str(source_path), str(out_path), key_hex)
        copy_plain_database(out_path, current_path)
        return {
            **base_result,
            "status": "ok",
            "salt": salt_hex,
            "size": out_path.stat().st_size,
            "current_size": current_path.stat().st_size,
            "wal": wal_result,
        }
    except Exception as exc:
        return {
            **base_result,
            "status": "error",
            "salt": read_salt_hex(str(source_path)) if source_path.exists() and not is_plain_sqlite(str(source_path)) else None,
            "error": str(exc),
        }


def decrypt_account(account: dict, snapshot_root: Path, current_root: Path, keys_log: str, key_store: Path, sync_time: datetime) -> dict:
    account_id = account["account_id"]
    safe_account_key = safe_account_dir_name(account)
    account_dir = snapshot_root / safe_account_key
    current_account_dir = current_root / safe_account_key
    account_dir.mkdir(parents=True, exist_ok=True)
    current_account_dir.mkdir(parents=True, exist_ok=True)
    tighten_permissions(account_dir, current_account_dir)

    result = {
        "account_key": account.get("account_key", account_id),
        "account_id": account_id,
        "container": account["container"],
        "container_name": account.get("container_name"),
        "account_root": account["account_root"],
        "synced_at": sync_time.isoformat(),
        "snapshot_dir": str(account_dir),
        "current_dir": str(current_account_dir),
        "databases": [],
        "message": None,
        "contact": None,
    }

    database_entries = [
        entry for entry in account.get("databases", [])
        if entry.get("sync_default")
    ]
    if not database_entries:
        database_entries = []
        for field_name in ("message_db", "contact_db"):
            source = account.get(field_name)
            if source:
                source_path = Path(source)
                database_entries.append(
                    {
                        "relative_path": source_path.name,
                        "category": "message_shard" if field_name == "message_db" else "contact",
                        "sync_default": True,
                        "source": str(source_path),
                    }
                )

    for db_entry in database_entries:
        result["databases"].append(
            sync_database_entry(
                db_entry,
                account_dir=account_dir,
                current_account_dir=current_account_dir,
                keys_log=keys_log,
                key_store=key_store,
                sync_time=sync_time,
            )
        )

    result["database_summary"] = summarize_databases(result["databases"])
    result["message"] = legacy_database_result(result, "message/message_0.db")
    result["contact"] = legacy_database_result(result, "contact/contact.db")
    return result


def main():
    parser = argparse.ArgumentParser(description="Decrypt all discovered WeChat DBs into a persistent project folder")
    parser.add_argument("--keys-log", default=str(DEFAULT_KEYS_LOG))
    parser.add_argument("--key-store", default=str(DEFAULT_KEY_STORE), help="Persistent local key store used for future syncs without logging in again")
    parser.add_argument("--output-dir", default=str(DEFAULT_DECRYPTED_ROOT))
    parser.add_argument("--account-id", action="append", dest="account_ids")
    parser.add_argument("--container-name", action="append", dest="container_names")
    parser.add_argument("--bundle-id", action="append", dest="container_names", help="Alias for --container-name when bundle id equals the WeChat container name")
    args = parser.parse_args()

    decrypted_root = Path(args.output_dir).expanduser()
    decrypted_root.mkdir(parents=True, exist_ok=True)
    tighten_permissions(decrypted_root)
    sync_time = datetime.now()
    snapshot_id = timestamp_slug(sync_time)
    snapshot_root = decrypted_root / "snapshots" / snapshot_id
    current_root = decrypted_root / "current"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    current_root.mkdir(parents=True, exist_ok=True)
    tighten_permissions(snapshot_root, current_root)

    key_store_path = Path(args.key_store).expanduser()
    import_keys_log(Path(args.keys_log).expanduser(), key_store_path)
    tighten_permissions(key_store_path.parent, key_store_path)
    keys_log_path = Path(args.keys_log).expanduser()
    if keys_log_path.exists():
        tighten_permissions(keys_log_path)

    accounts = discover_accounts()
    if args.container_names:
        allow_containers = set(args.container_names)
        accounts = [account for account in accounts if account.get("container_name") in allow_containers]
    if args.account_ids:
        allow = set(args.account_ids)
        accounts = [account for account in accounts if account["account_id"] in allow or account.get("account_key") in allow]

    results: List[dict] = []
    for account in accounts:
        results.append(decrypt_account(
            account,
            snapshot_root=snapshot_root,
            current_root=current_root,
            keys_log=args.keys_log,
            key_store=key_store_path,
            sync_time=sync_time,
        ))

    manifest = {
        "synced_at": sync_time.isoformat(),
        "keys_log": args.keys_log,
        "key_store": str(key_store_path),
        "output_dir": str(decrypted_root),
        "snapshot_id": snapshot_id,
        "snapshot_dir": str(snapshot_root),
        "current_dir": str(current_root),
        "accounts": results,
    }
    manifest_path = decrypted_root / "sync_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tighten_permissions(manifest_path)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
