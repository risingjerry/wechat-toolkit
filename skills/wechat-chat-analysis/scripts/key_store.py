import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict


def load_key_store(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "keys" in data:
        return data.get("keys", {})
    return data if isinstance(data, dict) else {}


def save_key_store(path: Path, keys: Dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(),
        "warning": "Sensitive WeChat SQLCipher derived keys. Keep local and do not share.",
        "keys": keys,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def import_keys_log(keys_log: Path, key_store_path: Path) -> Dict[str, dict]:
    keys = load_key_store(key_store_path)
    if not keys_log.exists():
        return keys

    text = keys_log.read_text(encoding="utf-8")
    now = datetime.now().isoformat()
    for block in text.split("\n\n"):
        if "rounds=256000" not in block:
            continue
        salt_match = re.search(r"salt=([a-f0-9]+)", block)
        dk_match = re.search(r"dk=([a-f0-9]+)", block)
        if not salt_match or not dk_match:
            continue
        salt = salt_match.group(1)
        keys[salt] = {
            "rounds": 256000,
            "dk": dk_match.group(1),
            "first_seen_at": keys.get(salt, {}).get("first_seen_at", now),
            "last_seen_at": now,
            "source": "wechat_keys.log",
        }
    save_key_store(key_store_path, keys)
    return keys


def key_for_salt(key_store_path: Path, salt_hex: str) -> str:
    item = load_key_store(key_store_path).get(salt_hex, {})
    return item.get("dk", "")
