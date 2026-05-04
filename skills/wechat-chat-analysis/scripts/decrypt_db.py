import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

from Crypto.Cipher import AES
from key_store import key_for_salt

PAGE_SIZE = 4096
RESERVE = 80
IV_LEN = 16
SQLITE_HEADER = b"SQLite format 3\x00"


def find_key_for_salt(keys_log: str, salt_hex: str) -> str:
    blocks = Path(keys_log).read_text(encoding="utf-8").split("\n\n")
    for block in blocks:
        if "rounds=256000" not in block:
            continue
        match_salt = re.search(r"salt=([a-f0-9]+)", block)
        match_dk = re.search(r"dk=([a-f0-9]+)", block)
        if match_salt and match_dk and match_salt.group(1) == salt_hex:
            return match_dk.group(1)
    return ""


def read_salt_hex(db_path: str) -> str:
    with open(db_path, "rb") as handle:
        return handle.read(16).hex()


def resolve_key_for_db(db_path: str, keys_log: str, key: Optional[str] = None, key_store: Optional[str] = None) -> str:
    if key:
        return key
    salt_hex = read_salt_hex(db_path)
    if key_store:
        matched_key = key_for_salt(Path(key_store), salt_hex)
        if matched_key:
            return matched_key
    if not os.path.exists(keys_log):
        raise FileNotFoundError(f"No --key provided, no matching key in key store, and keys log not found: {keys_log}")
    matched_key = find_key_for_salt(keys_log, salt_hex)
    if not matched_key:
        raise ValueError(f"No matching key found in key store or keys log for salt={salt_hex}")
    return matched_key


def decrypt_bytes(enc_db: str, enc_key_hex: str) -> bytes:
    enc_key = bytes.fromhex(enc_key_hex)
    with open(enc_db, "rb") as handle:
        data = handle.read()
    total_pages = len(data) // PAGE_SIZE

    out = bytearray()
    out += SQLITE_HEADER

    for index in range(total_pages):
        page = data[index * PAGE_SIZE:(index + 1) * PAGE_SIZE]
        offset = 16 if index == 0 else 0
        enc_data = page[offset:PAGE_SIZE - RESERVE]
        iv = page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + IV_LEN]
        cipher = AES.new(enc_key, AES.MODE_CBC, iv)
        plain = cipher.decrypt(enc_data)
        out += plain
        pad = PAGE_SIZE - (len(SQLITE_HEADER) if index == 0 else 0) - len(plain)
        if pad > 0:
            out += b"\x00" * pad
    return bytes(out)


def decrypt(enc_db: str, out_db: str, enc_key_hex: str) -> None:
    salt = read_salt_hex(enc_db)
    print(f"[*] salt={salt}", flush=True)
    decrypted = decrypt_bytes(enc_db, enc_key_hex)
    out_path = Path(out_db)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(decrypted)
    print(f"[*] wrote {out_db} size={out_path.stat().st_size}", flush=True)


def decrypt_file(enc_db: str, out_db: str, keys_log: str = "/tmp/wechat_keys.log", key: Optional[str] = None, key_store: Optional[str] = None) -> str:
    resolved_key = resolve_key_for_db(enc_db, keys_log=keys_log, key=key, key_store=key_store)
    decrypt(enc_db, out_db, resolved_key)
    return resolved_key


def main():
    parser = argparse.ArgumentParser(description="Decrypt a WeChat SQLCipher v4 database")
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--key")
    parser.add_argument("--keys-log", default="/tmp/wechat_keys.log")
    parser.add_argument("--key-store")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"[!] DB not found: {args.db}")

    try:
        salt = read_salt_hex(args.db)
        print(f"[*] Looking up key for salt={salt} in {args.keys_log}", flush=True)
        resolved_key = resolve_key_for_db(args.db, keys_log=args.keys_log, key=args.key, key_store=args.key_store)
        print(f"[*] Matched key={resolved_key[:16]}...", flush=True)
        decrypt(args.db, args.out, resolved_key)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"[!] {exc}")


if __name__ == "__main__":
    main()
