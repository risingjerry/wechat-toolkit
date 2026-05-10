import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from account_runtime import account_to_runtime, load_sync_manifest
from list_targets import classify_target, display_name, list_targets, load_contacts


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_MANIFEST = PROJECT_ROOT / "decrypted" / "sync_manifest.json"
DEFAULT_STATE = PROJECT_ROOT / "decrypted" / "query_state" / "new_messages.json"
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
FAVORITE_TYPE_MAP = {
    1: "text",
    2: "image",
    3: "voice",
    4: "video",
    5: "article",
    6: "location",
    7: "music",
    8: "file",
    14: "chat_record",
    16: "card",
    18: "note",
}
FAVORITE_TYPE_ALIASES = {
    "text": 1,
    "image": 2,
    "voice": 3,
    "video": 4,
    "article": 5,
    "link": 5,
    "location": 6,
    "music": 7,
    "file": 8,
    "chat_record": 14,
    "chat-record": 14,
    "card": 16,
    "note": 18,
}
SUMMARY_THEME_PATTERNS = {
    "AI / 自动化": ["ai", "agent", "自动化", "大模型", "知识库", "claude", "codex", "hermes"],
    "课程 / 付费产品": ["课程", "训练营", "报名", "付费", "会员", "教程"],
    "合作 / 推广": ["合作", "推广", "商务", "渠道", "广告", "测评"],
    "内容 / 流量": ["小红书", "抖音", "视频", "公众号", "内容", "流量"],
    "工具 / 配置": ["安装", "配置", "报错", "打不开", "api", "订阅"],
}
_MESSAGE_TOOLS = None


def safe_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def decode_text_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    )


def message_tools() -> dict:
    global _MESSAGE_TOOLS
    if _MESSAGE_TOOLS is None:
        from export_chat import format_msg, load_sender_lookup, open_message_connections, query_message_rows, resolve_target_across

        _MESSAGE_TOOLS = {
            "format_msg": format_msg,
            "load_sender_lookup": load_sender_lookup,
            "open_message_connections": open_message_connections,
            "query_message_rows": query_message_rows,
            "resolve_target_across": resolve_target_across,
        }
    return _MESSAGE_TOOLS


def account_label(runtime: dict, index: int) -> str:
    return f"{runtime.get('container_name') or 'account'}#{index + 1}"


def load_runtimes(manifest_path: Path, account_id: Optional[str], all_accounts: bool) -> List[dict]:
    manifest = load_sync_manifest(manifest_path)
    accounts = [
        account for account in manifest.get("accounts", [])
        if account.get("message", {}).get("status") in {"ok", "plain"}
        or any(
            database.get("category") == "message_shard" and database.get("status") in {"ok", "plain"}
            for database in account.get("databases", [])
        )
    ]
    if account_id:
        accounts = [
            account for account in accounts
            if account.get("account_key") == account_id or account.get("account_id") == account_id
        ]
    elif not all_accounts:
        accounts = accounts[:1]
    runtimes = [account_to_runtime(account) for account in accounts]
    if not runtimes:
        raise ValueError("No matching synced account runtime found")
    return runtimes


def message_paths(runtime: dict) -> List[Path]:
    paths = [Path(path).expanduser() for path in runtime.get("message_dbs", [])]
    if not paths and runtime.get("message_db"):
        paths = [Path(runtime["message_db"]).expanduser()]
    return paths


def contact_path(runtime: dict) -> Optional[Path]:
    value = runtime.get("contact_db")
    return Path(value).expanduser() if value else None


def favorite_path(runtime: dict) -> Optional[Path]:
    value = runtime.get("favorite_db")
    return Path(value).expanduser() if value else None


def sns_path(runtime: dict) -> Optional[Path]:
    value = runtime.get("sns_db")
    return Path(value).expanduser() if value else None


def parse_time(value: Optional[str], end_of_day: bool = False) -> Optional[int]:
    if not value:
        return None
    text = value.strip()
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            return int(parsed.timestamp())
        except ValueError:
            continue
    raise ValueError(f"Unable to parse time: {value}")


def fmt_time(timestamp: Optional[int]) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp).isoformat(timespec="minutes")


def truncate_text(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)] + "…"


def extract_xml_text(value: str, tags: Sequence[str]) -> str:
    text = unescape(value or "")
    for tag in tags:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, flags=re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        inner = match.group(1)
        cdata = re.search(r"<!\[CDATA\[(.*?)\]\]>", inner, flags=re.DOTALL)
        return unescape(cdata.group(1) if cdata else inner).strip()
    return ""


def extract_xml_int(value: str, tags: Sequence[str]) -> Optional[int]:
    text = extract_xml_text(value, tags)
    if not text:
        return None
    match = re.search(r"\d{9,13}", text)
    return normalize_epoch(int(match.group(0))) if match else None


def normalize_epoch(value: Optional[int]) -> Optional[int]:
    if not value:
        return None
    return int(value / 1000) if value > 10_000_000_000 else int(value)


def normalize_preview_text(value: str) -> str:
    text = unescape(value or "")
    preferred = extract_xml_text(
        text,
        (
            "contentDesc",
            "contentdesc",
            "title",
            "desc",
            "des",
            "summary",
            "content",
            "plain",
        ),
    )
    if preferred:
        text = preferred
    else:
        cdata_values = re.findall(r"<!\[CDATA\[(.*?)\]\]>", text, flags=re.DOTALL)
        if cdata_values:
            text = " ".join(item.strip() for item in cdata_values if item.strip())
    text = re.sub(r"https?://[^\s<>\"]+", " [URL_REDACTED] ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def redact_text(value: str, limit: int = 180) -> str:
    text = normalize_preview_text(value)
    text = re.sub(r"https?%3A%2F%2F[^\s<>\"]+", "[URL_REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[API_KEY_REDACTED]", text)
    text = re.sub(r"wxid_[A-Za-z0-9_\\-]+", "[WXID_REDACTED]", text)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[PHONE_REDACTED]", text)
    text = re.sub(r"\b\d{15,}\b", "[NUMBER_REDACTED]", text)
    text = re.sub(r"\b\d{6}(?:19|20)?\d{2}\d{2}\d{2}\d{3}[0-9Xx]\b", "[ID_REDACTED]", text)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL_REDACTED]", text)
    text = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[TOKEN_REDACTED]", text)
    return truncate_text(text, limit)


def safe_display(raw_id: str, contacts: Dict[str, dict], limit: int = 80) -> str:
    if not raw_id:
        return ""
    return redact_text(display_name(raw_id, contacts), limit)


def type_label(value: Optional[int]) -> str:
    if value is None:
        return "unknown"
    return FAVORITE_TYPE_MAP.get(value, f"type{value}")


def favorite_type_filter(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = value.strip().lower()
    if text.isdigit():
        return int(text)
    if text not in FAVORITE_TYPE_ALIASES:
        raise ValueError(f"Unknown favorite type: {value}")
    return FAVORITE_TYPE_ALIASES[text]


def source_status(path: Optional[Path], table_name: str) -> tuple[str, str]:
    if not path:
        return "unavailable", "database not synced"
    if not path.exists():
        return "unavailable", "database path missing"
    try:
        conn = sqlite3.connect(path)
        try:
            if not table_exists(conn, table_name):
                return "unavailable", f"table {table_name} not found"
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return "unavailable", str(exc)
    return "ok", ""


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def table_for_target(target_id: str) -> str:
    return f"Msg_{hashlib.md5(target_id.encode()).hexdigest()}"


def row_to_message(
    row: sqlite3.Row,
    source_db: str,
    table_name: str,
    target_id: str,
    target_name: str,
    contacts: Dict[str, dict],
    sender_lookup: Dict[int, str],
    preview_chars: int,
) -> dict:
    sender_id = sender_lookup.get(row["real_sender_id"], "")
    sender = display_name(sender_id, contacts) if sender_id else target_name
    format_msg = message_tools()["format_msg"]
    decoded_text, formatted = format_msg(row["local_type"], row["message_content"] or b"")
    content = truncate_text(formatted or decoded_text, preview_chars)
    return {
        "chat": target_name,
        "chat_type": classify_target(target_id),
        "time": fmt_time(row["create_time"]),
        "timestamp": row["create_time"],
        "sender": sender,
        "type": TYPE_MAP.get(row["local_type"], f"type{row['local_type']}"),
        "content": content,
        "source_db": source_db,
        "source_table": table_name,
    }


def query_target_rows(
    runtime: dict,
    target_id: str,
    limit: int,
    since: Optional[int],
    until: Optional[int],
    preview_chars: int,
) -> List[dict]:
    contacts = load_contacts(contact_path(runtime))
    tools = message_tools()
    connections = tools["open_message_connections"](message_paths(runtime))
    target_name = display_name(target_id, contacts)
    table_name = table_for_target(target_id)
    messages: List[dict] = []
    try:
        for source_db, _, conn in connections:
            if not table_exists(conn, table_name):
                continue
            sender_lookup = tools["load_sender_lookup"](conn)
            rows = tools["query_message_rows"](conn, table_name, None)
            for row in rows:
                ts = row["create_time"] or 0
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
                messages.append(
                    row_to_message(row, source_db, table_name, target_id, target_name, contacts, sender_lookup, preview_chars)
                )
    finally:
        for _, _, conn in connections:
            conn.close()
    messages.sort(key=lambda item: (item.get("timestamp") or 0, item.get("source_db") or ""))
    if limit:
        messages = messages[-limit:]
    return messages


def cmd_sessions(runtimes: Sequence[dict], limit: int) -> dict:
    out = []
    for index, runtime in enumerate(runtimes):
        paths = message_paths(runtime)
        targets = list_targets(paths[0], contact_path(runtime), message_dbs=paths)
        targets.sort(key=lambda item: item.get("last_timestamp") or 0, reverse=True)
        out.append(
            {
                "account_scope": account_label(runtime, index),
                "count": min(len(targets), limit),
                "sessions": [
                    {
                        "chat": item.get("target_name"),
                        "chat_type": item.get("target_type"),
                        "message_count": item.get("message_count"),
                        "last_time": fmt_time(item.get("last_timestamp")),
                        "source_shard_count": len(item.get("source_shards", [])),
                    }
                    for item in targets[:limit]
                ],
            }
        )
    return {"accounts": out}


def cmd_history(runtimes: Sequence[dict], chat: str, limit: int, since: Optional[int], until: Optional[int], preview_chars: int) -> dict:
    accounts = []
    for index, runtime in enumerate(runtimes):
        contacts = load_contacts(contact_path(runtime))
        tools = message_tools()
        connections = tools["open_message_connections"](message_paths(runtime))
        try:
            try:
                target_id, target_name = tools["resolve_target_across"](connections, contacts, None, chat)
            except SystemExit as exc:
                accounts.append(
                    {
                        "account_scope": account_label(runtime, index),
                        "chat": chat,
                        "count": 0,
                        "messages": [],
                        "error": str(exc),
                    }
                )
                continue
        finally:
            for _, _, conn in connections:
                conn.close()
        messages = query_target_rows(runtime, target_id, limit, since, until, preview_chars)
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "chat": target_name,
                "count": len(messages),
                "messages": messages,
            }
        )
    return {"accounts": accounts}


def iter_search_targets(
    conn: sqlite3.Connection,
    contacts: Dict[str, dict],
    chat_filter: Optional[str],
) -> Iterable[Tuple[str, str, str]]:
    rows = list(conn.execute("SELECT user_name FROM Name2Id ORDER BY user_name"))
    for row in rows:
        target_id = decode_text_value(row["user_name"])
        target_name = display_name(target_id, contacts)
        if chat_filter:
            needle = chat_filter.strip().lower()
            if needle not in target_name.lower() and needle not in target_id.lower():
                continue
        table_name = table_for_target(target_id)
        if table_exists(conn, table_name):
            yield target_id, target_name, table_name


def cmd_search(
    runtimes: Sequence[dict],
    keyword: str,
    chat: Optional[str],
    limit: int,
    since: Optional[int],
    until: Optional[int],
    preview_chars: int,
) -> dict:
    if not keyword.strip():
        raise ValueError("keyword is required")
    like = f"%{escape_like(keyword)}%"
    accounts = []
    for index, runtime in enumerate(runtimes):
        contacts = load_contacts(contact_path(runtime))
        tools = message_tools()
        connections = tools["open_message_connections"](message_paths(runtime))
        results = []
        try:
            for source_db, _, conn in connections:
                sender_lookup = tools["load_sender_lookup"](conn)
                for target_id, target_name, table_name in iter_search_targets(conn, contacts, chat):
                    clauses = ["message_content LIKE ? ESCAPE '\\'"]
                    params: List[object] = [like]
                    if since:
                        clauses.append("create_time >= ?")
                        params.append(since)
                    if until:
                        clauses.append("create_time <= ?")
                        params.append(until)
                    params.append(max(limit * 3, limit))
                    sql = (
                        f"SELECT local_id, server_id, local_type, create_time, real_sender_id, status, source, "
                        f"CAST(message_content AS BLOB) AS message_content FROM {table_name} "
                        f"WHERE {' AND '.join(clauses)} ORDER BY create_time DESC LIMIT ?"
                    )
                    for row in conn.execute(sql, params):
                        results.append(
                            row_to_message(row, source_db, table_name, target_id, target_name, contacts, sender_lookup, preview_chars)
                        )
        finally:
            for _, _, conn in connections:
                conn.close()
        results.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "keyword": keyword,
                "count": min(len(results), limit),
                "results": results[:limit],
            }
        )
    return {"accounts": accounts}


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_chmod(path.parent, 0o700)
    safe_chmod(path, 0o600)


def cmd_new_messages(runtimes: Sequence[dict], limit: int, state_path: Path, preview_chars: int) -> dict:
    state = load_state(state_path)
    fallback = int((datetime.now() - timedelta(days=1)).timestamp())
    accounts = []
    for index, runtime in enumerate(runtimes):
        label = account_label(runtime, index)
        runtime_key = runtime.get("account_key") or label
        account_state = state.setdefault(runtime_key, {})
        paths = message_paths(runtime)
        targets = list_targets(paths[0], contact_path(runtime), message_dbs=paths)
        changed = [
            target for target in targets
            if (target.get("last_timestamp") or 0) > account_state.get(target["target_id"], fallback)
        ]
        pending: List[Tuple[str, dict]] = []
        for target in changed:
            since = account_state.get(target["target_id"], fallback)
            target_messages = query_target_rows(runtime, target["target_id"], max(limit, 1), since, None, preview_chars)
            pending.extend(
                (target["target_id"], message)
                for message in target_messages
                if (message.get("timestamp") or 0) > since
            )
        pending.sort(key=lambda item: item[1].get("timestamp") or 0)
        pending = pending[:limit]
        messages = [message for _, message in pending]
        for target_id, message in pending:
            if message.get("timestamp"):
                account_state[target_id] = max(account_state.get(target_id, 0), message["timestamp"])
        accounts.append({"account_scope": label, "count": len(messages), "messages": messages})
    save_state(state_path, state)
    return {"accounts": accounts, "state_path": str(state_path)}


def favorite_row_to_record(row: sqlite3.Row, contacts: Dict[str, dict], preview_chars: int) -> dict:
    update_time = normalize_epoch(row["update_time"])
    source_id = decode_text_value(row["realchatname"] or row["fromusr"] or "")
    return {
        "time": fmt_time(update_time),
        "timestamp": update_time,
        "type": type_label(row["type"]),
        "source": safe_display(source_id, contacts),
        "preview": redact_text(row["content"] or "", preview_chars),
        "source_table": "fav_db_item",
    }


def cmd_favorites(
    runtimes: Sequence[dict],
    limit: int,
    query: Optional[str],
    favorite_type: Optional[str],
    preview_chars: int,
) -> dict:
    accounts = []
    type_filter = favorite_type_filter(favorite_type)
    for index, runtime in enumerate(runtimes):
        path = favorite_path(runtime)
        status, error = source_status(path, "fav_db_item")
        if status != "ok":
            accounts.append(
                {
                    "account_scope": account_label(runtime, index),
                    "status": status,
                    "count": 0,
                    "favorites": [],
                    "error": error,
                }
            )
            continue

        contacts = load_contacts(contact_path(runtime))
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        clauses = []
        params: List[object] = []
        if type_filter is not None:
            clauses.append("type = ?")
            params.append(type_filter)
        if query:
            clauses.append("content LIKE ? ESCAPE '\\'")
            params.append(f"%{escape_like(query)}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(f"SELECT COUNT(*) AS count FROM fav_db_item {where}", params).fetchone()["count"]
        rows = conn.execute(
            f"SELECT local_id, type, update_time, content, fromusr, realchatname FROM fav_db_item "
            f"{where} ORDER BY update_time DESC, local_id DESC LIMIT ?",
            [*params, max(limit, 0)],
        ).fetchall()
        by_type = conn.execute("SELECT type, COUNT(*) AS count FROM fav_db_item GROUP BY type ORDER BY count DESC").fetchall()
        conn.close()
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "status": "ok",
                "total": total,
                "count": len(rows),
                "by_type": [{"type": type_label(row["type"]), "count": row["count"]} for row in by_type],
                "favorites": [favorite_row_to_record(row, contacts, preview_chars) for row in rows],
            }
        )
    return {"accounts": accounts}


def sns_row_to_record(row: sqlite3.Row, contacts: Dict[str, dict], preview_chars: int) -> dict:
    raw_content = decode_text_value(row["content"] or "")
    user_id = decode_text_value(row["user_name"] or "")
    create_time = extract_xml_int(raw_content, ("createTime", "createtime", "create_time"))
    return {
        "time": fmt_time(create_time),
        "timestamp": create_time,
        "author": safe_display(user_id, contacts),
        "preview": redact_text(raw_content, preview_chars),
        "source_table": "SnsTimeLine",
    }


def include_sns_record(record: dict, user: Optional[str], since: Optional[int], until: Optional[int]) -> bool:
    timestamp = record.get("timestamp")
    if user and user.lower() not in (record.get("author") or "").lower():
        return False
    if since and (not timestamp or timestamp < since):
        return False
    if until and (not timestamp or timestamp > until):
        return False
    return True


def cmd_sns_feed(
    runtimes: Sequence[dict],
    limit: int,
    user: Optional[str],
    since: Optional[int],
    until: Optional[int],
    preview_chars: int,
) -> dict:
    accounts = []
    for index, runtime in enumerate(runtimes):
        path = sns_path(runtime)
        status, error = source_status(path, "SnsTimeLine")
        if status != "ok":
            accounts.append(
                {
                    "account_scope": account_label(runtime, index),
                    "status": status,
                    "count": 0,
                    "posts": [],
                    "error": error,
                }
            )
            continue

        contacts = load_contacts(contact_path(runtime))
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) AS count FROM SnsTimeLine").fetchone()["count"]
        fetch_limit = max(limit * 50, limit, 500)
        rows = conn.execute(
            "SELECT tid, user_name, content FROM SnsTimeLine ORDER BY tid DESC LIMIT ?",
            (fetch_limit,),
        ).fetchall()
        conn.close()
        records = [
            record
            for record in (sns_row_to_record(row, contacts, preview_chars) for row in rows)
            if include_sns_record(record, user, since, until)
        ][:limit]
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "status": "ok",
                "total": total,
                "count": len(records),
                "posts": records,
            }
        )
    return {"accounts": accounts}


def cmd_sns_search(
    runtimes: Sequence[dict],
    keyword: str,
    limit: int,
    user: Optional[str],
    since: Optional[int],
    until: Optional[int],
    preview_chars: int,
) -> dict:
    if not keyword.strip():
        raise ValueError("keyword is required")
    accounts = []
    like = f"%{escape_like(keyword)}%"
    for index, runtime in enumerate(runtimes):
        path = sns_path(runtime)
        status, error = source_status(path, "SnsTimeLine")
        if status != "ok":
            accounts.append(
                {
                    "account_scope": account_label(runtime, index),
                    "status": status,
                    "keyword": keyword,
                    "count": 0,
                    "results": [],
                    "error": error,
                }
            )
            continue

        contacts = load_contacts(contact_path(runtime))
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT tid, user_name, content FROM SnsTimeLine "
            "WHERE content LIKE ? ESCAPE '\\' ORDER BY tid DESC LIMIT ?",
            (like, max(limit * 20, limit, 200)),
        ).fetchall()
        conn.close()
        records = [
            record
            for record in (sns_row_to_record(row, contacts, preview_chars) for row in rows)
            if include_sns_record(record, user, since, until)
        ][:limit]
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "status": "ok",
                "keyword": keyword,
                "count": len(records),
                "results": records,
            }
        )
    return {"accounts": accounts}


def theme_counts_from_texts(texts: Iterable[str]) -> list[dict]:
    counts: Counter[str] = Counter()
    for text in texts:
        lowered = text.lower()
        for theme, keywords in SUMMARY_THEME_PATTERNS.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                counts[theme] += 1
    return [{"theme": theme, "count": count} for theme, count in counts.most_common()]


def cmd_enrichment_summary(runtimes: Sequence[dict], limit: int, preview_chars: int) -> dict:
    accounts = []
    for index, runtime in enumerate(runtimes):
        favorites = cmd_favorites([runtime], limit, None, None, preview_chars)["accounts"][0]
        sns = cmd_sns_feed([runtime], limit, None, None, None, preview_chars)["accounts"][0]
        favorite_previews = [item.get("preview", "") for item in favorites.get("favorites", [])]
        sns_previews = [item.get("preview", "") for item in sns.get("posts", [])]
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "favorites": {
                    "status": favorites.get("status"),
                    "total": favorites.get("total", 0),
                    "by_type": favorites.get("by_type", []),
                    "recent": favorites.get("favorites", []),
                },
                "sns": {
                    "status": sns.get("status"),
                    "total": sns.get("total", 0),
                    "recent": sns.get("posts", []),
                },
                "theme_counts": theme_counts_from_texts([*favorite_previews, *sns_previews]),
            }
        )
    return {"accounts": accounts}


def cmd_stats(runtimes: Sequence[dict], chat: str, since: Optional[int], until: Optional[int]) -> dict:
    accounts = []
    for index, runtime in enumerate(runtimes):
        contacts = load_contacts(contact_path(runtime))
        tools = message_tools()
        connections = tools["open_message_connections"](message_paths(runtime))
        try:
            try:
                target_id, target_name = tools["resolve_target_across"](connections, contacts, None, chat)
            except SystemExit as exc:
                accounts.append(
                    {
                        "account_scope": account_label(runtime, index),
                        "chat": chat,
                        "total": 0,
                        "by_type": [],
                        "top_senders": [],
                        "by_hour": [{"hour": hour, "count": 0} for hour in range(24)],
                        "error": str(exc),
                    }
                )
                continue
        finally:
            for _, _, conn in connections:
                conn.close()
        messages = query_target_rows(runtime, target_id, 0, since, until, 1_000)
        by_type = Counter(message.get("type") for message in messages)
        by_sender = Counter(message.get("sender") for message in messages if message.get("sender"))
        by_hour = Counter(datetime.fromtimestamp(message["timestamp"]).hour for message in messages if message.get("timestamp"))
        accounts.append(
            {
                "account_scope": account_label(runtime, index),
                "chat": target_name,
                "total": len(messages),
                "by_type": [{"type": key, "count": value} for key, value in by_type.most_common()],
                "top_senders": [{"sender": key, "count": value} for key, value in by_sender.most_common(10)],
                "by_hour": [{"hour": hour, "count": by_hour.get(hour, 0)} for hour in range(24)],
            }
        )
    return {"accounts": accounts}


def print_output(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Account-scoped fast queries over synced WeChat message shards")
    parser.add_argument("--sync-manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--account-id")
    parser.add_argument("--all-accounts", action="store_true", help="Query all synced accounts instead of the first matching account")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sessions = subparsers.add_parser("sessions")
    sessions.add_argument("-n", "--limit", type=int, default=20)

    history = subparsers.add_parser("history")
    history.add_argument("chat")
    history.add_argument("-n", "--limit", type=int, default=50)
    history.add_argument("--since")
    history.add_argument("--until")
    history.add_argument("--preview-chars", type=int, default=240)

    search = subparsers.add_parser("search")
    search.add_argument("keyword")
    search.add_argument("--chat")
    search.add_argument("-n", "--limit", type=int, default=20)
    search.add_argument("--since")
    search.add_argument("--until")
    search.add_argument("--preview-chars", type=int, default=240)

    new_messages = subparsers.add_parser("new-messages")
    new_messages.add_argument("-n", "--limit", type=int, default=100)
    new_messages.add_argument("--state", default=str(DEFAULT_STATE))
    new_messages.add_argument("--preview-chars", type=int, default=240)

    stats = subparsers.add_parser("stats")
    stats.add_argument("chat")
    stats.add_argument("--since")
    stats.add_argument("--until")

    favorites = subparsers.add_parser("favorites")
    favorites.add_argument("-n", "--limit", type=int, default=20)
    favorites.add_argument("--query")
    favorites.add_argument("--type", dest="favorite_type")
    favorites.add_argument("--preview-chars", type=int, default=180)

    sns_feed = subparsers.add_parser("sns-feed")
    sns_feed.add_argument("-n", "--limit", type=int, default=20)
    sns_feed.add_argument("--user")
    sns_feed.add_argument("--since")
    sns_feed.add_argument("--until")
    sns_feed.add_argument("--preview-chars", type=int, default=180)

    sns_search = subparsers.add_parser("sns-search")
    sns_search.add_argument("keyword")
    sns_search.add_argument("-n", "--limit", type=int, default=20)
    sns_search.add_argument("--user")
    sns_search.add_argument("--since")
    sns_search.add_argument("--until")
    sns_search.add_argument("--preview-chars", type=int, default=180)

    enrichment_summary = subparsers.add_parser("enrichment-summary")
    enrichment_summary.add_argument("-n", "--limit", type=int, default=8)
    enrichment_summary.add_argument("--preview-chars", type=int, default=160)

    args = parser.parse_args()
    try:
        runtimes = load_runtimes(Path(args.sync_manifest).expanduser(), args.account_id, args.all_accounts)
        if args.command == "sessions":
            payload = cmd_sessions(runtimes, args.limit)
        elif args.command == "history":
            payload = cmd_history(
                runtimes,
                args.chat,
                args.limit,
                parse_time(args.since),
                parse_time(args.until, end_of_day=True),
                args.preview_chars,
            )
        elif args.command == "search":
            payload = cmd_search(
                runtimes,
                args.keyword,
                args.chat,
                args.limit,
                parse_time(args.since),
                parse_time(args.until, end_of_day=True),
                args.preview_chars,
            )
        elif args.command == "new-messages":
            payload = cmd_new_messages(runtimes, args.limit, Path(args.state).expanduser(), args.preview_chars)
        elif args.command == "stats":
            payload = cmd_stats(runtimes, args.chat, parse_time(args.since), parse_time(args.until, end_of_day=True))
        elif args.command == "favorites":
            payload = cmd_favorites(runtimes, args.limit, args.query, args.favorite_type, args.preview_chars)
        elif args.command == "sns-feed":
            payload = cmd_sns_feed(
                runtimes,
                args.limit,
                args.user,
                parse_time(args.since),
                parse_time(args.until, end_of_day=True),
                args.preview_chars,
            )
        elif args.command == "sns-search":
            payload = cmd_sns_search(
                runtimes,
                args.keyword,
                args.limit,
                args.user,
                parse_time(args.since),
                parse_time(args.until, end_of_day=True),
                args.preview_chars,
            )
        elif args.command == "enrichment-summary":
            payload = cmd_enrichment_summary(runtimes, args.limit, args.preview_chars)
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:
        sys.exit(f"[!] {exc}")
    print_output(payload, args.json)


if __name__ == "__main__":
    main()
