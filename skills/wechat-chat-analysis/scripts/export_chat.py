import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import zstandard as zstd
except ImportError:
    sys.exit("[!] zstandard not installed. Run: pip install zstandard")

TYPE_MAP = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    48: "location",
    49: "share",
    10000: "system",
    65537: "system_notice",
}


def decode_text_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def decode_content(raw: bytes) -> bytes:
    if not raw:
        return b""
    if raw[:4] == b"\x28\xB5\x2F\xFD":
        try:
            return zstd.ZstdDecompressor().decompress(raw, max_output_size=100 * 1024 * 1024)
        except Exception:
            return raw
    return raw


def xml_field(s: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.DOTALL)
    return html.unescape(match.group(1).strip()) if match else ""


def xml_attr(s: str, tag: str, attr: str) -> str:
    match = re.search(rf'<{tag}[^>]*\\b{attr}="([^"]+)"', s, re.DOTALL)
    return html.unescape(match.group(1)) if match else ""


def render_text(plain: str) -> str:
    match = re.search(
        r"([\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef][^\x00-\x08\x0b-\x1f]{2,}.*)",
        plain,
        re.DOTALL,
    )
    return match.group(1).strip() if match else plain.strip()


def format_msg(local_type: int, raw: bytes) -> Tuple[str, str]:
    decoded = decode_content(raw)
    text = decoded.decode("utf-8", errors="replace") if decoded else ""

    if local_type == 1:
        rendered = render_text(text)
        return rendered, rendered
    if local_type == 3:
        md5_value = xml_attr(text, "img", "md5") or xml_attr(text, "img", "aeskey")
        summary = f"[图片] md5={md5_value[:12]}..." if md5_value else "[图片]"
        return text, summary
    if local_type == 34:
        voice_length = xml_attr(text, "voicemsg", "voicelength")
        summary = f"[语音 {voice_length}ms]" if voice_length else "[语音]"
        return text, summary
    if local_type == 43:
        play_length = xml_attr(text, "videomsg", "playlength")
        summary = f"[视频 {play_length}s]" if play_length else "[视频]"
        return text, summary
    if local_type == 48:
        location = xml_attr(text, "location", "poiname") or xml_attr(text, "location", "label")
        return text, f"[位置] {location}".strip()
    if local_type == 49 or local_type > 100:
        title = xml_field(text, "title")
        desc = xml_field(text, "des") or xml_field(text, "desc")
        url = xml_field(text, "url")
        source = xml_field(text, "sourcedisplayname")
        if url and title:
            summary = f"**[{title}]({url})**"
            if source:
                summary += f" — _{source}_"
            if desc:
                summary += f"\n> {desc}"
            return text, summary
        if title:
            return text, f"**{title}**" + (f"\n> {desc}" if desc else "")
        match = re.search(r"https?://[^\s\"'<>]+", text)
        if match:
            return text, match.group(0)
        return text, f"[类型{local_type}]"
    match = re.search(r"https?://[^\s\"'<>]+", text)
    if match:
        return text, match.group(0)
    return text, f"[类型{local_type}]"


def image_candidates_from_xml(text: str) -> Dict[str, int]:
    return {
        "thumb": int(xml_attr(text, "img", "cdnthumblength") or 0),
        "mid": int(xml_attr(text, "img", "length") or 0),
        "hd": int(xml_attr(text, "img", "hdlength") or 0),
    }


def decode_wechat_attachment(dat_path: Path) -> Optional[Path]:
    data = dat_path.read_bytes()
    candidates = {
        ".jpg": bytes.fromhex("ffd8ff"),
        ".png": bytes.fromhex("89504e470d0a1a0a"),
        ".gif": b"GIF8",
        ".webp": b"RIFF",
        ".bmp": b"BM",
    }
    for offset in range(0, 64):
        body = data[offset:]
        for key in range(256):
            probe = bytes(b ^ key for b in body[:16])
            ext = None
            for candidate_ext, signature in candidates.items():
                if probe.startswith(signature):
                    ext = candidate_ext
                    break
                if candidate_ext == ".webp" and len(probe) >= 12 and probe[:4] == b"RIFF" and bytes(b ^ key for b in body[8:12]) == b"WEBP":
                    ext = candidate_ext
                    break
            if not ext:
                continue
            decoded = bytes(b ^ key for b in body)
            out_path = dat_path.with_suffix(ext)
            out_path.write_bytes(decoded)
            return out_path
    return None


def resolve_image_attachment_paths(decoded_text: str, attachment_info: Dict[str, object]) -> Dict[str, Optional[str]]:
    files = [Path(path) for path in attachment_info.get("files", [])]
    if not files:
        return {"thumb": None, "mid": None, "hd": None, "decoded": None}

    sizes = image_candidates_from_xml(decoded_text)
    matched = {"thumb": None, "mid": None, "hd": None}
    for kind, expected_size in sizes.items():
        if not expected_size:
            continue
        for candidate in files:
            actual_size = candidate.stat().st_size
            if actual_size == expected_size or actual_size == expected_size + 31:
                matched[kind] = str(candidate)
                break

    decoded_preview = None
    for key in ("thumb", "mid", "hd"):
        path = matched[key]
        if not path:
            continue
        decoded = decode_wechat_attachment(Path(path))
        if decoded:
            decoded_preview = str(decoded)
            break

    return {
        "thumb": matched["thumb"],
        "mid": matched["mid"],
        "hd": matched["hd"],
        "decoded": decoded_preview,
    }


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
                    user_name = decode_text_value(row["user_name"])
                    contacts[user_name] = {
                        "user_name": user_name,
                        "nickname": decode_text_value(row["nickname"]),
                        "remark": decode_text_value(row["remark"]),
                        "alias": decode_text_value(row["alias"]),
                    }
                if contacts:
                    break
            except sqlite3.OperationalError:
                continue
    conn.close()
    return contacts


def display_name(user_name: str, contacts: Dict[str, dict]) -> str:
    user_name = decode_text_value(user_name)
    if user_name == "filehelper":
        return "文件传输助手"
    info = contacts.get(user_name, {})
    for key in ("remark", "nickname", "alias"):
        value = decode_text_value(info.get(key, "")).strip()
        if value:
            return value
    return user_name


def resolve_target(message_conn: sqlite3.Connection, contacts: Dict[str, dict], target: Optional[str], target_name: Optional[str]):
    rows = list(message_conn.execute("SELECT user_name FROM Name2Id ORDER BY user_name"))
    user_names = [decode_text_value(row[0]) for row in rows]
    if target:
        if target in user_names or target == "filehelper":
            return target, display_name(target, contacts)
        sys.exit(f"[!] Target not found: {target}")

    if not target_name:
        sys.exit("[!] Provide either --target or --target-name")

    normalized = target_name.strip().lower()
    exact_matches = []
    partial_matches = []
    for user_name in user_names:
        shown = display_name(user_name, contacts)
        user_name_lower = user_name.lower()
        shown_lower = shown.lower()
        if shown_lower == normalized or user_name_lower == normalized:
            exact_matches.append((user_name, shown))
        elif normalized in shown_lower or normalized in user_name_lower:
            partial_matches.append((user_name, shown))

    matches = exact_matches or partial_matches
    if not matches:
        sys.exit(f"[!] No chat target matched name: {target_name}")
    if len(matches) > 1:
        joined = ", ".join(f"{shown} ({user_name})" for user_name, shown in matches)
        sys.exit(f"[!] Multiple matches for '{target_name}': {joined}. Use --target.")
    return matches[0]


def copy_attachments(wx_root: Path, target_hash: str, month: str, dst: Path) -> List[str]:
    src = wx_root / "msg" / "attach" / target_hash / month
    if not src.exists():
        return []
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for root, _, files in os.walk(src):
        for name in files:
            if name.startswith("."):
                continue
            source_path = Path(root) / name
            if source_path.stat().st_size > 200 * 1024 * 1024:
                continue
            target_path = dst / name
            if not target_path.exists():
                try:
                    shutil.copy2(source_path, target_path)
                except Exception:
                    continue
            copied.append(str(target_path))
    return copied


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip()).strip("-")
    return cleaned or "chat"


def unique_export_root(output_root: Path, target_slug: str, target_id: str, force_slug_id: bool = False) -> Path:
    base = output_root / (slugify(target_id) if force_slug_id else slugify(target_slug))
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        return base
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        manifest = {}
    if manifest.get("target_id") in {None, target_id}:
        return base
    suffix = hashlib.md5(target_id.encode()).hexdigest()[:8]
    return output_root / f"{slugify(target_slug)}-{suffix}"


def ensure_json_serializable(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def autodetect_wechat_root(db_path: Optional[Path] = None) -> Path:
    candidates = []
    if db_path:
        for parent in db_path.parents:
            if parent.name == "db_storage" and parent.parent.name.startswith("wxid_"):
                candidates.append(parent.parent)
    base = Path.home() / "Library/Containers"
    for container in sorted(base.glob("com.tencent.xinWeChat*")):
        docs_root = container / "Data/Documents/xwechat_files"
        if docs_root.exists():
            for account_root in docs_root.iterdir():
                if account_root.is_dir():
                    candidates.append(account_root)
    for candidate in candidates:
        if (candidate / "msg/attach").exists():
            return candidate
    raise FileNotFoundError("Unable to auto-detect WeChat data root; pass --wechat-root")


def normalize_attachment_index(attachment_index: Dict[str, dict], project_root: Path) -> Dict[str, dict]:
    normalized = {}
    for month, info in attachment_index.items():
        files = []
        for path in info.get("files", []):
            path_obj = Path(path)
            if not path_obj.is_absolute():
                path_obj = (project_root / path_obj).resolve()
            files.append(str(path_obj))
        dir_value = info.get("dir")
        dir_path = Path(dir_value) if dir_value else None
        if dir_path and not dir_path.is_absolute():
            dir_path = (project_root / dir_path).resolve()
        normalized[month] = {
            "dir": str(dir_path) if dir_path else None,
            "files": files,
        }
    return normalized


def load_state(export_root: Path) -> dict:
    state_path = export_root / "state.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_state(export_root: Path, state: dict) -> None:
    (export_root / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def rewrite_day_markdown(month_dir: Path, day_key: str, target_name: str, records: List[dict]) -> None:
    month_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"# {day_key} · {target_name}", ""]
    for record in sorted(records, key=lambda r: (r.get("timestamp") or "", r.get("local_id") or 0)):
        time_part = record["timestamp"][11:19] if record.get("timestamp") else "unknown"
        lines.append(f"## {time_part} · {record['sender_name']} · {record['type_name']}")
        lines.append("")
        lines.append(record.get("formatted_markdown") or "_(空)_")
        lines.append("")
    (month_dir / f"{day_key}.md").write_text("\n".join(lines), encoding="utf-8")


def normalize_message_dbs(db_path: Path, message_dbs: Optional[Sequence[Path]] = None) -> List[Path]:
    paths = [Path(path).expanduser() for path in (message_dbs or [db_path])]
    if db_path not in paths:
        paths.insert(0, db_path.expanduser())
    unique = []
    seen = set()
    for path in paths:
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def source_db_key(db_path: Path) -> str:
    parts = db_path.parts
    if "message" in parts:
        index = len(parts) - 1 - list(reversed(parts)).index("message")
        return "/".join(parts[index:])
    return db_path.name


def open_message_connections(db_paths: Sequence[Path]) -> List[Tuple[str, Path, sqlite3.Connection]]:
    connections = []
    for path in db_paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.text_factory = bytes
        connections.append((source_db_key(path), path, conn))
    return connections


def collect_user_names(connections: Sequence[Tuple[str, Path, sqlite3.Connection]]) -> List[str]:
    names = set()
    for _, _, conn in connections:
        try:
            for row in conn.execute("SELECT user_name FROM Name2Id ORDER BY user_name"):
                user_name = decode_text_value(row["user_name"])
                if user_name:
                    names.add(user_name)
        except sqlite3.Error:
            continue
    return sorted(names)


def resolve_target_across(
    connections: Sequence[Tuple[str, Path, sqlite3.Connection]],
    contacts: Dict[str, dict],
    target: Optional[str],
    target_name: Optional[str],
):
    user_names = collect_user_names(connections)
    if target:
        if target in user_names or target == "filehelper":
            return target, display_name(target, contacts)
        sys.exit(f"[!] Target not found: {target}")

    if not target_name:
        sys.exit("[!] Provide either --target or --target-name")

    normalized = target_name.strip().lower()
    exact_matches = []
    partial_matches = []
    for user_name in user_names:
        shown = display_name(user_name, contacts)
        user_name_lower = user_name.lower()
        shown_lower = shown.lower()
        if shown_lower == normalized or user_name_lower == normalized:
            exact_matches.append((user_name, shown))
        elif normalized in shown_lower or normalized in user_name_lower:
            partial_matches.append((user_name, shown))

    matches = exact_matches or partial_matches
    if not matches:
        sys.exit(f"[!] No chat target matched name: {target_name}")
    if len(matches) > 1:
        joined = ", ".join(f"{shown} ({user_name})" for user_name, shown in matches)
        sys.exit(f"[!] Multiple matches for '{target_name}': {joined}. Use --target.")
    return matches[0]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    )


def load_sender_lookup(conn: sqlite3.Connection) -> Dict[int, str]:
    sender_lookup = {}
    for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
        sender_lookup[row["rowid"]] = decode_text_value(row["user_name"])
    return sender_lookup


def query_message_rows(conn: sqlite3.Connection, table_name: str, last_local_id: Optional[int]) -> List[sqlite3.Row]:
    query = (
        f"SELECT local_id, server_id, local_type, create_time, real_sender_id, status, source, "
        f"CAST(message_content AS BLOB) AS message_content FROM {table_name} "
    )
    params = []
    if last_local_id is not None:
        query += "WHERE local_id > ? "
        params.append(last_local_id)
    query += "ORDER BY create_time ASC, local_id ASC"
    return conn.execute(query, params).fetchall()


def record_identity(record: dict) -> tuple:
    server_id = record.get("server_id")
    if server_id not in (None, "", 0, "0"):
        return ("server", server_id)
    return (
        "fallback",
        record.get("target_id"),
        record.get("local_id"),
        record.get("create_time"),
        record.get("local_type"),
        record.get("sender_id"),
        record.get("decoded_text"),
    )


def dedupe_records(records: List[dict]) -> List[dict]:
    deduped = {}
    for record in records:
        deduped[record_identity(record)] = record
    return list(deduped.values())


def build_shard_state(records: List[dict]) -> dict:
    shards: Dict[str, dict] = {}
    for record in records:
        source_db = record.get("source_db")
        source_table = record.get("source_table")
        if not source_db or not source_table:
            continue
        shard_state = shards.setdefault(source_db, {}).setdefault(source_table, {})
        local_id = record.get("local_id") or 0
        create_time = record.get("create_time") or 0
        if local_id > shard_state.get("last_local_id", 0):
            shard_state["last_local_id"] = local_id
        if create_time > shard_state.get("last_create_time", 0):
            shard_state["last_create_time"] = create_time
    return shards


def export_chat(
    db_path: Path,
    contact_db: Optional[Path],
    target: Optional[str],
    target_name: Optional[str],
    output_root: Path,
    vault: Optional[Path] = None,
    folder: str = "WeChat",
    wechat_root: Optional[Path] = None,
    no_attachments: bool = False,
    incremental: bool = False,
    preserve_raw: bool = False,
    include_id_in_slug: bool = False,
    message_dbs: Optional[Sequence[Path]] = None,
) -> dict:
    db_paths = normalize_message_dbs(db_path, message_dbs=message_dbs)
    wx_root = wechat_root.expanduser() if wechat_root else autodetect_wechat_root(db_paths[0])
    connections = open_message_connections(db_paths)
    if not connections:
        raise FileNotFoundError("No readable message databases found")

    contacts = load_contacts(contact_db)
    resolved_target_id, resolved_target_name = resolve_target_across(connections, contacts, target, target_name)
    target_hash = hashlib.md5(resolved_target_id.encode()).hexdigest()
    table_name = f"Msg_{target_hash}"

    target_slug = slugify(f"{resolved_target_name}-{resolved_target_id}" if include_id_in_slug else resolved_target_name)
    export_root = unique_export_root(output_root, target_slug, resolved_target_id, force_slug_id=False)
    markdown_root = export_root / "markdown"
    markdown_root.mkdir(parents=True, exist_ok=True)
    export_root.mkdir(parents=True, exist_ok=True)

    state = load_state(export_root)
    shard_state = state.get("shards", {}) if incremental else {}
    migrate_to_shard_state = bool(incremental and state and not shard_state)
    if incremental:
        state["attachment_months"] = normalize_attachment_index(state.get("attachment_months", {}), Path(__file__).resolve().parent.parent.parent)

    rows_with_context = []
    source_tables = []
    for source_key, _, conn in connections:
        if not table_exists(conn, table_name):
            continue
        source_tables.append(source_key)
        last_local_id = None
        if incremental and not migrate_to_shard_state:
            last_local_id = shard_state.get(source_key, {}).get(table_name, {}).get("last_local_id")
        sender_lookup = load_sender_lookup(conn)
        for row in query_message_rows(conn, table_name, last_local_id):
            rows_with_context.append((source_key, sender_lookup, row))
    rows_with_context.sort(key=lambda item: (item[2]["create_time"] or 0, item[2]["local_id"] or 0, item[0]))

    vault_root = None
    if vault:
        vault_root = vault.expanduser() / folder / target_slug
        vault_root.mkdir(parents=True, exist_ok=True)

    messages_path = export_root / "messages.jsonl"
    manifest_path = export_root / "manifest.json"
    existing_records = []
    if incremental and messages_path.exists():
        with messages_path.open("r", encoding="utf-8") as handle:
            existing_records = [json.loads(line) for line in handle if line.strip()]

    attachment_index = state.get("attachment_months", {}) if incremental else {}
    all_records = existing_records[:]
    touched_days = set()

    for source_key, sender_lookup, row in rows_with_context:
        timestamp = dt.datetime.fromtimestamp(row["create_time"]) if row["create_time"] else None
        sender_id = sender_lookup.get(row["real_sender_id"], "")
        sender_name_value = display_name(sender_id, contacts) if sender_id else resolved_target_name
        decoded_text, formatted = format_msg(row["local_type"], row["message_content"] or b"")
        month = timestamp.strftime("%Y-%m") if timestamp else "unknown"
        month_dir = markdown_root / month
        if month not in attachment_index and not no_attachments and timestamp:
            attachment_dir = month_dir / "attachments"
            copied_files = copy_attachments(wx_root, target_hash, month, attachment_dir)
            attachment_index[month] = {
                "dir": str(attachment_dir),
                "files": [str(Path(path).resolve()) for path in copied_files],
            }
        attachment_info = attachment_index.get(month, {"dir": None, "files": []}) if timestamp else {"dir": None, "files": []}

        image_attachments = {"thumb": None, "mid": None, "hd": None, "decoded": None}
        if row["local_type"] == 3:
            image_attachments = resolve_image_attachment_paths(decoded_text, attachment_info)
            if image_attachments["decoded"]:
                preview_rel = Path(image_attachments["decoded"]).relative_to(month_dir)
                formatted = f"![图片]({preview_rel.as_posix()})"
            else:
                links = []
                for label, key in (("缩略图", "thumb"), ("中图", "mid"), ("原图", "hd")):
                    if image_attachments[key]:
                        rel = Path(image_attachments[key]).relative_to(month_dir)
                        links.append(f"[{label}]({rel.as_posix()})")
                if links:
                    formatted = "[图片]\n\n" + " | ".join(links)

        record = {
            "target_id": resolved_target_id,
            "target_name": resolved_target_name,
            "sender_id": sender_id,
            "sender_name": sender_name_value,
            "local_id": row["local_id"],
            "server_id": row["server_id"],
            "real_sender_id": row["real_sender_id"],
            "create_time": row["create_time"],
            "timestamp": timestamp.isoformat() if timestamp else None,
            "local_type": row["local_type"],
            "type_name": TYPE_MAP.get(row["local_type"], f"type{row['local_type']}"),
            "status": row["status"],
            "decoded_source": ensure_json_serializable(row["source"]),
            "decoded_text": decoded_text,
            "formatted_markdown": formatted,
            "attachment_dir": attachment_info["dir"],
            "image_attachments": image_attachments,
            "source_db": source_key,
            "source_table": table_name,
        }
        if preserve_raw:
            record["raw_source_b64"] = base64.b64encode(row["source"] or b"").decode("ascii")
            record["raw_message_b64"] = base64.b64encode(row["message_content"] or b"").decode("ascii")
        all_records.append(record)
        if timestamp:
            touched_days.add(timestamp.strftime("%Y-%m-%d"))

    for _, _, conn in connections:
        conn.close()

    all_records = dedupe_records(all_records)
    all_records.sort(key=lambda record: (record.get("create_time") or 0, record.get("local_id") or 0, record.get("source_db") or ""))

    with messages_path.open("w", encoding="utf-8") as handle:
        for record in all_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    by_day: Dict[str, List[dict]] = {}
    for record in all_records:
        ts = record.get("timestamp")
        if not ts:
            continue
        day_key = ts[:10]
        by_day.setdefault(day_key, []).append(record)

    days_to_write = touched_days if incremental and touched_days else set(by_day.keys())
    if not incremental:
        days_to_write = set(by_day.keys())

    for day_key in sorted(days_to_write):
        month = day_key[:7]
        month_dir = markdown_root / month
        rewrite_day_markdown(month_dir, day_key, resolved_target_name, by_day.get(day_key, []))
        if vault_root:
            vault_month_dir = vault_root / month
            rewrite_day_markdown(vault_month_dir, day_key, resolved_target_name, by_day.get(day_key, []))
            src_attachments = month_dir / "attachments"
            if src_attachments.exists():
                shutil.copytree(src_attachments, vault_month_dir / "attachments", dirs_exist_ok=True)

    latest_local_id = max((record.get("local_id") or 0) for record in all_records) if all_records else state.get("last_local_id")
    latest_create_time = max((record.get("create_time") or 0) for record in all_records) if all_records else state.get("last_create_time")
    target_type = "filehelper" if resolved_target_id == "filehelper" else ("group" if resolved_target_id.endswith("@chatroom") else "contact")
    new_shard_state = build_shard_state(all_records)

    manifest = {
        "target_id": resolved_target_id,
        "target_name": resolved_target_name,
        "target_slug": target_slug,
        "target_type": target_type,
        "message_count": len(all_records),
        "output_root": str(export_root),
        "messages_jsonl": str(messages_path),
        "markdown_root": str(markdown_root),
        "attachment_months": attachment_index,
        "vault_root": str(vault_root) if vault_root else None,
        "preserve_raw": preserve_raw,
        "source_table": table_name,
        "source_table_found": bool(source_tables),
        "source_tables": source_tables,
        "source_db_count": len(db_paths),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    state.update(
        {
            "target_id": resolved_target_id,
            "target_name": resolved_target_name,
            "target_type": target_type,
            "last_local_id": latest_local_id,
            "last_create_time": latest_create_time,
            "last_export_time": dt.datetime.now().isoformat(),
            "last_export_mode": "incremental" if incremental else "full",
            "attachment_months": attachment_index,
            "preserve_raw": preserve_raw,
            "shards": new_shard_state,
        }
    )
    save_state(export_root, state)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Export a WeChat chat with raw preservation")
    parser.add_argument("--db", required=True, help="Decrypted message_0.db path")
    parser.add_argument("--db-extra", action="append", dest="db_extra", help="Additional decrypted message shard")
    parser.add_argument("--contact-db", help="Decrypted contact.db path")
    parser.add_argument("--target", help="Conversation target: filehelper or raw wxid/chatroom id")
    parser.add_argument("--target-name", help="Readable target name to resolve via contact.db")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent.parent / "output"), help="Output root path")
    parser.add_argument("--vault", help="Optional Obsidian vault root path")
    parser.add_argument("--folder", default="WeChat", help="Folder inside vault")
    parser.add_argument("--wechat-root", help="Override WeChat data root")
    parser.add_argument("--no-attachments", action="store_true")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--preserve-raw", action="store_true", help="Keep raw base64 message/source blobs in JSONL")
    parser.add_argument("--include-id-in-slug", action="store_true", help="Include target id in output folder name")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        sys.exit(f"[!] DB not found: {db_path}")
    message_dbs = [db_path] + [Path(path).expanduser() for path in (args.db_extra or [])]

    contact_db = Path(args.contact_db).expanduser() if args.contact_db else None
    output_root = Path(args.output_dir).expanduser()
    wechat_root = Path(args.wechat_root).expanduser() if args.wechat_root else None
    vault = Path(args.vault).expanduser() if args.vault else None

    try:
        manifest = export_chat(
            db_path=db_path,
            contact_db=contact_db,
            target=args.target,
            target_name=args.target_name,
            output_root=output_root,
            vault=vault,
            folder=args.folder,
            wechat_root=wechat_root,
            no_attachments=args.no_attachments,
            incremental=args.incremental,
            preserve_raw=args.preserve_raw,
            include_id_in_slug=args.include_id_in_slug,
            message_dbs=message_dbs,
        )
    except Exception as exc:
        sys.exit(f"[!] {exc}")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
