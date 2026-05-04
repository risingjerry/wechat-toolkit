import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from decrypt_db import decrypt_file, read_salt_hex
from discover_databases import discover_accounts
from key_store import import_keys_log


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_KEYS_LOG = PROJECT_ROOT / "decrypted" / "wechat_keys.log"
DEFAULT_KEY_STORE = PROJECT_ROOT / "decrypted" / "key_store.json"
DEFAULT_DECRYPTED_ROOT = PROJECT_ROOT / "decrypted"


def timestamp_slug(value: datetime) -> str:
    return value.strftime("%Y-%m-%d_%H%M%S")


def decrypt_account(account: dict, snapshot_root: Path, current_root: Path, keys_log: str, key_store: Path, sync_time: datetime) -> dict:
    account_id = account["account_id"]
    account_key = account.get("account_key", account_id)
    safe_account_key = account_key.replace(":", "__")
    account_dir = snapshot_root / safe_account_key
    current_account_dir = current_root / safe_account_key
    account_dir.mkdir(parents=True, exist_ok=True)
    current_account_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "account_key": account.get("account_key", account_id),
        "account_id": account_id,
        "container": account["container"],
        "container_name": account.get("container_name"),
        "account_root": account["account_root"],
        "synced_at": sync_time.isoformat(),
        "snapshot_dir": str(account_dir),
        "current_dir": str(current_account_dir),
        "message": None,
        "contact": None,
    }

    for kind, field_name in (("message", "message_db"), ("contact", "contact_db")):
        source = account.get(field_name)
        if not source:
            result[kind] = {"status": "missing_source"}
            continue

        source_path = Path(source)
        out_path = account_dir / source_path.name
        current_path = current_account_dir / source_path.name
        try:
            salt_hex = read_salt_hex(str(source_path))
            key_hex = decrypt_file(str(source_path), str(out_path), keys_log=keys_log, key_store=str(key_store))
            shutil.copy2(out_path, current_path)
            result[kind] = {
                "status": "ok",
                "source": str(source_path),
                "output": str(out_path),
                "current_output": str(current_path),
                "salt": salt_hex,
                "key_prefix": key_hex[:16],
                "size": out_path.stat().st_size,
                "snapshot_at": sync_time.isoformat(),
            }
        except Exception as exc:
            result[kind] = {
                "status": "error",
                "source": str(source_path),
                "salt": read_salt_hex(str(source_path)) if source_path.exists() else None,
                "error": str(exc),
            }
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
    sync_time = datetime.now()
    snapshot_id = timestamp_slug(sync_time)
    snapshot_root = decrypted_root / "snapshots" / snapshot_id
    current_root = decrypted_root / "current"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    current_root.mkdir(parents=True, exist_ok=True)

    key_store_path = Path(args.key_store).expanduser()
    import_keys_log(Path(args.keys_log).expanduser(), key_store_path)

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
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
