#!/usr/bin/env python3
"""Generate a WeChat business opportunity radar from exported chats.

The report is intentionally generated under output/_reports because it can
contain private contact names and redacted message snippets.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT_CRM_PATH = Path(__file__).resolve().parents[1] / "crm_dashboard.json"
DEFAULT_REPORT_DIR = DEFAULT_OUTPUT_ROOT / "_reports"
DEFAULT_OVERRIDES_PATH = Path(__file__).resolve().parents[1] / "opportunity_overrides.json"
DEFAULT_SYNC_MANIFEST = Path(__file__).resolve().parents[1] / "decrypted" / "sync_manifest.json"
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

IGNORE_TARGETS = {"微信团队", "文件传输助手"}
CONTACT_STAGE_SCORE = {
    "意向客户": 12,
    "产品咨询": 9,
    "已付费": 7,
    "新线索": 6,
    "待分类": 3,
    "流失": 1,
}

RELATIONSHIP_SCORE = {
    "客户": 10,
    "合作推广": 8,
    "同行/资源合作": 4,
    "我方购买/学习对象": -2,
    "粉丝/免费咨询": 0,
    "流失/退款客户": -4,
    "对我营销": -8,
    "待分类": 2,
}

SIGNAL_PATTERNS = {
    "购买/报名": ["多少钱", "价格", "怎么收费", "收费", "报名", "付费", "购买", "下单", "课程", "训练营", "加入", "会员", "订阅", "开通"],
    "合作/渠道": ["合作", "商务", "商务运营", "推广", "推广一下", "测评", "广告", "代理", "渠道", "分销", "资源置换", "有渠道", "找大佬的课", "品牌方", "上架课程", "豆包合作", "带货"],
    "明确求助": ["请教", "求助", "帮我", "有没有", "怎么做", "怎么弄", "如何", "可以分享", "推荐", "无从下手", "不知道干嘛"],
    "痛点/焦虑": ["焦虑", "卡住", "痛点", "搞不定", "不会", "不知道", "没思路", "没效果", "效率低", "累死", "麻烦", "无从下手"],
    "售后/问题": ["报错", "失败", "不行", "打不开", "登不上", "不能用", "没反应", "密码", "错误", "卡住"],
}

THEME_PATTERNS = {
    "企业 AI 落地": ["企业", "落地", "业务", "场景", "方案", "规划", "知识库", "数据清洗", "大模型"],
    "Agent / 自动化": ["agent", "智能体", "自动化", "工作流", "执行", "工具调用", "claude code", "codex", "hermes"],
    "工具安装与配置": ["安装", "配置", "报错", "打不开", "登不上", "api", "中转", "订阅", "充值", "魔法"],
    "课程 / 付费产品": ["课程", "训练营", "付费", "报名", "会员", "教程", "知识付费", "怎么学"],
    "合作推广": ["合作", "推广", "测评", "广告", "渠道", "分销", "商务", "代理"],
    "内容与流量": ["小红书", "抖音", "视频", "选题", "内容", "流量", "变现", "公众号"],
    "个人知识库": ["obsidian", "知识库", "笔记", "vault", "wiki", "raw", "claude code"],
}

QUESTION_MARKERS = ("?", "？", "吗", "呢", "如何", "怎么", "有没有", "谁有", "求", "请教", "推荐")
BUSINESS_MARKERS = ("AI", "ai", "大模型", "Agent", "agent", "Claude", "Codex", "Hermes", "课程", "付费", "企业", "落地", "知识库", "小红书", "流量", "变现")
DIRECT_NEED_MARKERS = ("我想", "想咨询", "想问", "请问", "请教", "求助", "帮我", "帮忙", "需要", "能不能", "有没有", "怎么", "如何", "多少钱", "怎么收费", "课程如何", "哪里买", "哪里可以", "求推荐")
STRONG_DIRECT_MARKERS = ("我的需求", "我想咨询", "想咨询你", "想问", "请问", "请教", "求助", "帮我", "帮忙", "多少钱", "怎么收费", "接测评", "宣传合作", "合作的需求")
BROADCAST_MARKERS = ("@所有人", "朋友们", "欢迎各位", "群规", "统一回复", "倒计时", "直播链接", "正式启动", "优惠最后", "课程表", "第二弹", "最后 1 小时", "最后1小时", "恢复原价", "报名开启", "报名已经", "加入链接", "年度最低价", "优惠加入")
PARTNER_MARKERS = ("推广合作", "宣传合作", "测评推广", "商务合作", "商务运营", "品牌方", "带货合作", "置换", "寄一套产品", "出一期内容", "素材、报价", "合作方式", "出版社", "带货", "接测评", "产品宣传", "渠道在买课程", "分销", "上架课程", "豆包合作", "推广一下", "有新产品", "产品方")
STRONG_PARTNER_MARKERS = ("推广合作", "宣传合作", "测评推广", "商务合作", "商务运营", "品牌方", "带货合作", "寄一套产品", "出版社", "接测评", "产品宣传", "渠道在买课程", "上架课程", "豆包合作", "推广一下", "有新产品")
CUSTOMER_MARKERS = ("课程", "培训", "想学", "怎么学", "报名", "多少钱", "怎么收费", "帮忙安装", "付费处理", "知识付费", "安装问题", "配置", "报错", "不行", "打不开", "登不上", "hermes", "claude", "codex", "openclaw", "知识库", "小白", "我的需求", "定制", "咨询一下")
PAYMENT_TEXT_MARKERS = ("付过去了", "已经转", "转过去了", "付款了", "已付款", "已付", "付费了", "知识付费是必须", "手机端我付费了", "付费处理")
PARTNER_DEFER_MARKERS = ("暂时还不考虑", "后面有机会", "后续可以再合作", "以后再合作", "再谈视频合作")
PARTNER_ACTIVE_MARKERS = ("已经收到了", "收到了告诉你", "拍摄的脚本", "寄一套产品", "置换为主", "有档期")
INBOUND_MARKETING_MARKERS = ("加入链接", "报名链接", "点击链接", "加入成功", "报名成功", "私我", "恢复原价", "年度最低价", "优惠", "倒计时", "开播", "直播间", "报名开启", "报名入口", "对接会员权益", "发放新圈友资料", "优惠加入", "加入可以", "感兴趣可以", "私我加入")
INBOUND_OFFER_MARKERS = ("生财有术", "大航海", "训练营", "社群", "会员权益", "课程", "直播", "圈友", "报名", "加入", "原价", "优惠")
OWNER_NAME_HINTS = ("大号", "小号", "本人", "自己", "自用")
SUPERSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹", "01234567890123456789")


@dataclass
class Message:
    timestamp: str
    sender: str
    text: str
    raw_text: str
    type_name: str
    target_name: str
    account_scope: str = ""
    chat_type: str = "contact"

    @property
    def date(self) -> str:
        return self.timestamp[:10] if self.timestamp else ""


@dataclass
class Signal:
    category: str
    date: str
    sender: str
    text: str
    score: int
    source: str
    reply_gap: str = ""
    account_scope: str = ""


@dataclass
class ContactRadar:
    name: str
    relationship_type: str
    deal_status: str
    stage: str
    msg_count: int
    last_date: str
    days_since: int | None
    score: int
    reasons: list[str] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    payment_signals: list[Signal] = field(default_factory=list)
    suggested_action: str = ""
    opener: str = ""
    account_scope: str = ""


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone())


def normalize_text(text: str) -> str:
    text = unescape(text or "").strip()
    title_match = re.search(r"<title>(.*?)</title>", text, flags=re.DOTALL | re.IGNORECASE)
    if title_match:
        text = title_match.group(1).strip()
    cdata_match = re.search(r"<!\[CDATA\[(.*?)\]\]>", text, flags=re.DOTALL)
    if cdata_match and len(cdata_match.group(1).strip()) > 2:
        text = cdata_match.group(1).strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def redact(text: str, limit: int = 180) -> str:
    text = normalize_text(text)
    text = re.sub(r"sk-[A-Za-z0-9_-]{16,}", "[API_KEY_REDACTED]", text)
    text = re.sub(r"wxid_[A-Za-z0-9_\\-]+", "[WXID_REDACTED]", text)
    text = re.sub(r"\b1[3-9]\d{9}\b", "[PHONE_REDACTED]", text)
    text = re.sub(r"\b\d{6}(?:19|20)?\d{2}\d{2}\d{2}\d{3}[0-9Xx]\b", "[ID_REDACTED]", text)
    text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL_REDACTED]", text)
    text = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[TOKEN_REDACTED]", text)
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def clean_name(name: str) -> str:
    normalized = normalize_text(name).translate(SUPERSCRIPT_DIGITS)
    normalized = re.sub(r"[\x00-\x1f\x7f]+", "", normalized).strip()
    normalized = re.sub(r"\d{6,}", "[NUMBER_REDACTED]", normalized)
    normalized = re.sub(r"1[3-9]\d{9}", "[PHONE_REDACTED]", normalized)
    return normalized or "未命名联系人"


def safe_account_scope(account_dir: Path | None) -> str:
    if not account_dir:
        return "default"
    return account_dir.name.split("__", 1)[0] or "default"


def classify_chat(manifest: dict[str, Any]) -> str:
    target_id = str(manifest.get("target_id") or "")
    target_name = clean_name(manifest.get("target_name") or "")
    target_type = str(manifest.get("target_type") or "")
    if target_name in IGNORE_TARGETS or target_id == "filehelper":
        return "system"
    if target_id.endswith("@chatroom") or target_type == "group":
        return "group"
    if target_id in {"brandsessionholder", "@placeholder_foldgroup"}:
        return "folded"
    if target_id in {"mphelper", "qqsafe"}:
        return "official_account"
    if target_id.startswith(("gh_", "biz_", "@")):
        return "official_account"
    return "contact"


def base_name(name: str) -> str:
    normalized = clean_name(name)
    normalized = re.sub(r"（[^）]*）", "", normalized)
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    return normalized.strip()


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return None


def recency_score(days_since: int | None) -> int:
    if days_since is None:
        return 0
    if days_since <= 1:
        return 6
    if days_since <= 3:
        return 5
    if days_since <= 7:
        return 3
    if days_since <= 14:
        return 1
    if days_since > 30:
        return -2
    return 0


def detect_categories(text: str) -> list[str]:
    lowered = text.lower()
    categories = []
    for category, keywords in SIGNAL_PATTERNS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            categories.append(category)
    return categories


def keyword_count(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword.lower() in lowered)


def extract_payment_amount(raw_text: str) -> str:
    patterns = [
        r"<feedesc><!\[CDATA\[(.*?)\]\]></feedesc>",
        r"收到转账([0-9.]+)元",
        r"￥\s*([0-9.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text)
        if match:
            return match.group(1).strip()
    return ""


def detect_payment_signals(messages: list[Message], owner_names: set[str], target_name: str) -> list[Signal]:
    signals: list[Signal] = []
    for message in messages:
        if message.sender in owner_names:
            continue
        raw = message.raw_text
        if "微信转账" in raw or "<type>2000</type>" in raw:
            amount = extract_payment_amount(raw)
            snippet = f"微信转账 {amount}" if amount else "微信转账"
            signals.append(
                Signal(
                    category="付款/转账",
                    date=message.date,
                    sender=clean_name(message.sender or target_name),
                    text=redact(snippet),
                    score=20,
                    source=target_name,
                )
            )
            continue
        if "微信红包" in raw or "<![CDATA[2001]]>" in raw or "<type>2001</type>" in raw:
            signals.append(
                Signal(
                    category="付款/红包",
                    date=message.date,
                    sender=clean_name(message.sender or target_name),
                    text="微信红包",
                    score=16,
                    source=target_name,
                )
            )
            continue
        if any(marker in message.text for marker in PAYMENT_TEXT_MARKERS):
            signals.append(
                Signal(
                    category="付款/文本确认",
                    date=message.date,
                    sender=clean_name(message.sender or target_name),
                    text=redact(message.text),
                    score=14,
                    source=target_name,
                )
            )
    return sorted(signals, key=lambda signal: (-signal.score, signal.date))


def classify_contact(messages: list[Message], owner_names: set[str], target_name: str) -> tuple[str, str, list[str], list[Signal]]:
    contact_messages = [message for message in messages if message.sender not in owner_names and message.type_name != "system"]
    owner_messages = [message for message in messages if message.sender in owner_names]
    contact_text = " ".join(message.text for message in contact_messages)
    all_text = " ".join(message.text for message in messages)
    owner_text = " ".join(message.text for message in owner_messages)

    payment_signals = detect_payment_signals(messages, owner_names, target_name)
    partner_score = keyword_count(contact_text, PARTNER_MARKERS)
    customer_score = keyword_count(contact_text, CUSTOMER_MARKERS)

    reasons: list[str] = []
    has_strong_partner = any(marker in contact_text for marker in STRONG_PARTNER_MARKERS)
    inbound_marketing = is_inbound_marketing(contact_messages, owner_messages)

    if payment_signals:
        reasons.append("已有付款/红包证据")
        relationship_type = "客户"
        deal_status = "已成交"
    elif inbound_marketing and not has_strong_partner:
        relationship_type = "对我营销"
        deal_status = "对方营销/不跟进"
    elif (partner_score >= 2 and partner_score >= customer_score) or has_strong_partner:
        relationship_type = "合作推广"
        if any(marker in all_text for marker in PARTNER_ACTIVE_MARKERS):
            deal_status = "样品/合作推进中"
        elif any(marker in owner_text for marker in PARTNER_DEFER_MARKERS):
            deal_status = "已婉拒/暂缓"
        else:
            deal_status = "待评估合作"
    elif customer_score > 0:
        relationship_type = "客户"
        if any(marker in contact_text for marker in ("多少钱", "怎么收费", "想学", "想咨询", "课程", "报名", "定制")):
            deal_status = "高意向未成交"
        elif any(marker in contact_text for marker in ("报错", "不行", "打不开", "登不上", "安装问题", "配置")):
            deal_status = "售后/问题"
        else:
            deal_status = "待判断需求"
    else:
        relationship_type = "待分类"
        deal_status = "待分类"

    if partner_score:
        reasons.append(f"合作信号 {partner_score}")
    if customer_score:
        reasons.append(f"客户需求信号 {customer_score}")
    if inbound_marketing:
        reasons.append("对方单向营销")
    return relationship_type, deal_status, reasons, payment_signals


def is_direct_need(text: str) -> bool:
    return any(marker in text for marker in DIRECT_NEED_MARKERS)


def is_broadcast_like(text: str) -> bool:
    if not any(marker in text for marker in BROADCAST_MARKERS):
        return False
    return not any(marker in text for marker in STRONG_DIRECT_MARKERS)


def is_actionable_signal(text: str, categories: list[str]) -> bool:
    if not categories:
        return False
    if is_broadcast_like(text):
        return False
    if len(text) > 500 and not any(marker in text for marker in STRONG_DIRECT_MARKERS):
        return False
    if "售后/问题" in categories:
        return True
    if "合作/渠道" in categories and any(marker in text for marker in ("合作", "想咨询", "想问", "有渠道", "找", "接", "推广", "商务", "品牌", "上架课程", "豆包")):
        return True
    purchase_need = any(marker in text for marker in ("多少钱", "价格", "怎么收费", "想学", "想咨询", "课程如何", "有没有", "开通", "订阅", "哪里买", "怎么买", "购买gpt", "想报名", "怎么报名"))
    purchase_need = purchase_need or bool(re.search(r"(报名|付费|购买).{0,8}(吗|呢|？|\?)", text))
    if "购买/报名" in categories and purchase_need:
        return True
    if "明确求助" in categories and is_direct_need(text):
        return True
    if "痛点/焦虑" in categories and is_direct_need(text):
        return True
    return False


def theme_hits(text: str) -> list[str]:
    lowered = text.lower()
    return [theme for theme, keywords in THEME_PATTERNS.items() if any(keyword.lower() in lowered for keyword in keywords)]


def read_messages(export_dir: Path, account_scope: str = "", chat_type: str = "contact") -> list[Message]:
    path = export_dir / "messages.jsonl"
    if not path.exists():
        return []

    messages: list[Message] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_text = raw.get("decoded_text") or ""
            text = normalize_text(raw_text)
            if not text:
                continue
            messages.append(
                Message(
                    timestamp=raw.get("timestamp") or "",
                    sender=raw.get("sender_name") or "",
                    text=text,
                    raw_text=raw_text,
                    type_name=raw.get("type_name") or "",
                    target_name=raw.get("target_name") or "",
                    account_scope=account_scope,
                    chat_type=chat_type,
                )
            )
    return messages


def iter_manifest_paths(output_root: Path) -> list[tuple[Path, str]]:
    manifest_paths: list[tuple[Path, str]] = []
    account_root = output_root / "_accounts"
    if account_root.is_dir():
        for manifest_path in sorted(account_root.glob("*/*/manifest.json")):
            manifest_paths.append((manifest_path, safe_account_scope(manifest_path.parents[1])))
        return manifest_paths
    if output_root.name == "_accounts":
        for manifest_path in sorted(output_root.glob("*/*/manifest.json")):
            manifest_paths.append((manifest_path, safe_account_scope(manifest_path.parents[1])))
        return manifest_paths
    for manifest_path in sorted(output_root.glob("*/manifest.json")):
        if manifest_path.parent.name.startswith("_"):
            continue
        manifest_paths.append((manifest_path, "default"))
    return manifest_paths


def load_exports(output_root: Path) -> list[dict[str, Any]]:
    exports = []
    for manifest_path, account_scope in iter_manifest_paths(output_root):
        manifest = load_json(manifest_path, {})
        target_name = manifest.get("target_name") or manifest_path.parent.name
        if target_name in IGNORE_TARGETS:
            continue
        chat_type = classify_chat(manifest)
        manifest["radar_chat_type"] = chat_type
        manifest["account_scope"] = account_scope
        stats = load_json(manifest_path.parent / "stats.json", {})
        messages = read_messages(manifest_path.parent, account_scope=account_scope, chat_type=chat_type)
        exports.append(
            {
                "dir": manifest_path.parent,
                "account_scope": account_scope,
                "chat_type": chat_type,
                "manifest": manifest,
                "stats": stats,
                "messages": messages,
            }
        )
    return exports


def infer_owner_names(exports: list[dict[str, Any]]) -> set[str]:
    counts: Counter[str] = Counter()
    target_names = {item["manifest"].get("target_name") for item in exports}
    for item in exports:
        if item.get("chat_type") != "contact":
            continue
        target_name = item["manifest"].get("target_name")
        for message in item["messages"]:
            if message.sender and message.sender != target_name and message.sender not in target_names:
                counts[message.sender] += 1
    if not counts:
        return set()
    owner, owner_count = counts.most_common(1)[0]
    owners = {owner}
    for name, count in counts.most_common(5):
        if count >= max(3, owner_count * 0.25):
            owners.add(name)
    return owners


def build_crm_lookup(crm_path: Path) -> dict[str, dict[str, Any]]:
    crm = load_json(crm_path, {})
    return {clean_name(item.get("name")): item for item in crm.get("contacts", []) if item.get("name")}


def load_overrides(path: Path) -> dict[str, Any]:
    raw = load_json(path, {})
    contact_overrides = {}
    for name, override in raw.get("contacts", {}).items():
        contact_overrides[clean_name(name)] = override
    inbound_marketing_senders = {
        name
        for name, override in contact_overrides.items()
        if override.get("relationship_type") == "对我营销"
    }
    inbound_marketing_senders.update(base_name(name) for name in list(inbound_marketing_senders))
    return {
        "self_accounts": {clean_name(name) for name in raw.get("self_accounts", [])},
        "contacts": contact_overrides,
        "inbound_marketing_senders": inbound_marketing_senders,
    }


def account_database_path(account: dict[str, Any], category: str) -> Path | None:
    for database in account.get("databases", []):
        if (
            database.get("category") == category
            and database.get("status") in {"ok", "plain"}
            and (database.get("current_output") or database.get("output"))
        ):
            return Path(database.get("current_output") or database.get("output")).expanduser()
    return None


def favorite_type_label(value: int | None) -> str:
    if value is None:
        return "unknown"
    return FAVORITE_TYPE_MAP.get(value, f"type{value}")


def summarize_favorites(path: Path | None, text_limit: int = 160) -> tuple[dict[str, Any], list[str]]:
    if not path or not path.exists():
        return {"status": "unavailable", "total": 0, "by_type": []}, []
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        if not table_exists(conn, "fav_db_item"):
            conn.close()
            return {"status": "unavailable", "total": 0, "by_type": [], "reason": "table_missing"}, []
        total = conn.execute("SELECT COUNT(*) AS count FROM fav_db_item").fetchone()["count"]
        by_type_rows = conn.execute("SELECT type, COUNT(*) AS count FROM fav_db_item GROUP BY type ORDER BY count DESC").fetchall()
        rows = conn.execute(
            "SELECT type, content FROM fav_db_item ORDER BY update_time DESC, local_id DESC LIMIT ?",
            (text_limit,),
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {"status": "unavailable", "total": 0, "by_type": [], "reason": "sqlite_error"}, []
    texts = [normalize_text(row["content"] or "") for row in rows]
    return (
        {
            "status": "ok",
            "total": total,
            "by_type": [{"type": favorite_type_label(row["type"]), "count": row["count"]} for row in by_type_rows],
            "sampled_recent_items": len(rows),
        },
        [text for text in texts if text],
    )


def summarize_sns(path: Path | None, text_limit: int = 200) -> tuple[dict[str, Any], list[str]]:
    if not path or not path.exists():
        return {"status": "unavailable", "total": 0}, []
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        if not table_exists(conn, "SnsTimeLine"):
            conn.close()
            return {"status": "unavailable", "total": 0, "reason": "table_missing"}, []
        total = conn.execute("SELECT COUNT(*) AS count FROM SnsTimeLine").fetchone()["count"]
        rows = conn.execute("SELECT content FROM SnsTimeLine ORDER BY tid DESC LIMIT ?", (text_limit,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return {"status": "unavailable", "total": 0, "reason": "sqlite_error"}, []
    texts = [normalize_text(row["content"] or "") for row in rows]
    return {"status": "ok", "total": total, "sampled_recent_posts": len(rows)}, [text for text in texts if text]


def build_enrichment(sync_manifest_path: Path) -> dict[str, Any]:
    if not sync_manifest_path.exists():
        return {"status": "unavailable", "accounts": [], "theme_counts": []}
    manifest = load_json(sync_manifest_path, {})
    account_rows = []
    aggregate_themes: Counter[str] = Counter()
    total_favorites = 0
    total_sns_posts = 0

    for account in manifest.get("accounts", []):
        account_scope = account.get("container_name") or safe_account_scope(Path(account.get("account_root", "")))
        favorite_summary, favorite_texts = summarize_favorites(account_database_path(account, "favorite"))
        sns_summary, sns_texts = summarize_sns(account_database_path(account, "sns"))
        theme_counts: Counter[str] = Counter()
        for text in [*favorite_texts, *sns_texts]:
            for theme in theme_hits(text):
                theme_counts[theme] += 1
                aggregate_themes[theme] += 1
        total_favorites += int(favorite_summary.get("total") or 0)
        total_sns_posts += int(sns_summary.get("total") or 0)
        account_rows.append(
            {
                "account_scope": account_scope,
                "favorites": favorite_summary,
                "sns": sns_summary,
                "theme_counts": [{"theme": theme, "count": count} for theme, count in theme_counts.most_common(8)],
            }
        )

    return {
        "status": "ok",
        "total_favorites": total_favorites,
        "total_sns_posts": total_sns_posts,
        "accounts": account_rows,
        "theme_counts": [{"theme": theme, "count": count} for theme, count in aggregate_themes.most_common(10)],
    }


def is_self_account_name(name: str, overrides: dict[str, Any]) -> bool:
    if name in overrides.get("self_accounts", set()):
        return True
    lowered = name.lower()
    return any(hint in name for hint in OWNER_NAME_HINTS) and any(token in lowered for token in ("hh", "jerry", "杰瑞斯"))


def is_ignored_sender(sender: str, ignored_senders: set[str]) -> bool:
    sender_name = clean_name(sender)
    sender_base = base_name(sender_name)
    return any(
        ignored == sender_name
        or ignored == sender_base
        or (ignored and ignored in sender_name)
        or (sender_base and sender_base in ignored)
        for ignored in ignored_senders
    )


def is_inbound_marketing(contact_messages: list[Message], owner_messages: list[Message]) -> bool:
    if not contact_messages:
        return False
    contact_text = " ".join(message.text for message in contact_messages)
    marketing_text = is_inbound_marketing_text(contact_text)
    marketing_score = keyword_count(contact_text, INBOUND_MARKETING_MARKERS)
    one_way = len(owner_messages) <= 1 and len(contact_messages) >= 3
    repetitive = len(contact_messages) >= 5 and marketing_score >= 3
    return (one_way and marketing_text) or repetitive


def is_inbound_marketing_text(text: str) -> bool:
    marketing_score = keyword_count(text, INBOUND_MARKETING_MARKERS)
    offer_score = keyword_count(text, INBOUND_OFFER_MARKERS)
    has_cta_link = "http" in text.lower() and marketing_score >= 1
    selling_to_me = offer_score >= 2 and any(marker in text for marker in ("你也想", "你需要", "想加入", "加入成功", "感兴趣", "优惠加入", "点击链接", "加入可以"))
    return marketing_score >= 2 and (has_cta_link or selling_to_me or offer_score >= 3)


def contact_signals(item: dict[str, Any], owner_names: set[str]) -> list[Signal]:
    target_name = clean_name(item["manifest"].get("target_name") or item["dir"].name)
    signals: list[Signal] = []
    messages = item["messages"]
    for index, message in enumerate(messages):
        if message.sender in owner_names:
            continue
        if message.type_name == "system":
            continue
        categories = detect_categories(message.text)
        if not is_actionable_signal(message.text, categories):
            continue
        base = 4 + 2 * len(categories)
        if "购买/报名" in categories:
            base += 4
        if "合作/渠道" in categories:
            base += 3
        if "明确求助" in categories:
            base += 2

        later_owner_reply = any(next_msg.sender in owner_names for next_msg in messages[index + 1 : index + 8])
        reply_gap = "" if later_owner_reply else "后续 7 条内未见你回复"
        if reply_gap:
            base += 4

        signals.append(
            Signal(
                category=" / ".join(categories),
                date=message.date,
                sender=clean_name(message.sender or target_name),
                text=redact(message.text),
                score=base,
                source=target_name,
                reply_gap=reply_gap,
            )
        )
    return sorted(signals, key=lambda signal: (-signal.score, signal.date), reverse=False)


def make_contact_radar(
    exports: list[dict[str, Any]],
    crm_lookup: dict[str, dict[str, Any]],
    owner_names: set[str],
    overrides: dict[str, Any],
    now: datetime,
) -> list[ContactRadar]:
    results: list[ContactRadar] = []
    for item in exports:
        manifest = item["manifest"]
        if item.get("chat_type") != "contact":
            continue
        name = clean_name(manifest.get("target_name") or item["dir"].name)
        if name in IGNORE_TARGETS:
            continue
        if is_self_account_name(name, overrides):
            continue
        stats = item["stats"]
        crm = crm_lookup.get(name, {})
        stage = crm.get("stage") or "待分类"
        msg_count = int(stats.get("total") or manifest.get("message_count") or 0)
        last_date = stats.get("last_date") or ""
        days_since = crm.get("days_since")
        if days_since is None and last_date:
            last_dt = parse_time(last_date)
            if last_dt:
                days_since = (now - last_dt).days

        relationship_type, deal_status, relationship_reasons, payment_signals = classify_contact(item["messages"], owner_names, name)
        manual_override = overrides.get("contacts", {}).get(name, {})
        if manual_override.get("ignore"):
            continue
        if manual_override:
            relationship_type = manual_override.get("relationship_type") or relationship_type
            deal_status = manual_override.get("deal_status") or deal_status
            reason = manual_override.get("reason")
            if reason:
                relationship_reasons.insert(0, f"人工校正：{reason}")
            if deal_status in {"已成交", "疑似已成交"} and reason and not payment_signals:
                payment_signals = [
                    Signal(
                        category="人工确认",
                        date=last_date or "",
                        sender="人工校正",
                        text=redact(reason),
                        score=18,
                        source=name,
                        account_scope=item.get("account_scope", ""),
                    )
                ]
        if relationship_type == "客户" and deal_status != "已成交" and stage == "已付费":
            deal_status = "疑似已成交"
        signals = [] if relationship_type == "对我营销" else contact_signals(item, owner_names)
        score = RELATIONSHIP_SCORE.get(relationship_type, 2) + CONTACT_STAGE_SCORE.get(stage, 2) + recency_score(days_since)
        if deal_status == "高意向未成交":
            score += 10
        elif deal_status == "已成交":
            score += 6
        elif deal_status == "疑似已成交":
            score += 3
        elif deal_status == "待评估合作":
            score += 8
        elif deal_status == "样品/合作推进中":
            score += 5
        elif deal_status == "已婉拒/暂缓":
            score -= 8
        elif deal_status == "对方营销/不跟进":
            score -= 15
        if msg_count >= 100:
            score += 3
        elif msg_count >= 30:
            score += 2
        elif msg_count >= 10:
            score += 1
        score += sum(signal.score for signal in signals[:3])
        score += sum(signal.score for signal in payment_signals[:1])

        reasons = []
        reasons.append(relationship_type)
        reasons.append(deal_status)
        if stage:
            reasons.append(stage)
        reasons.extend(relationship_reasons[:2])
        if days_since is not None:
            reasons.append(f"{days_since} 天未跟进" if days_since > 0 else "今天仍有互动")
        for signal in signals[:2]:
            reasons.append(signal.category)
        if signals and signals[0].reply_gap:
            reasons.append("疑似未回复")

        suggested_action = suggest_contact_action(relationship_type, deal_status, stage, signals, payment_signals)
        opener = suggest_opener(name, relationship_type, deal_status, stage, signals, payment_signals)
        results.append(
            ContactRadar(
                name=name,
                relationship_type=relationship_type,
                deal_status=deal_status,
                stage=stage,
                msg_count=msg_count,
                last_date=last_date,
                days_since=days_since,
                score=score,
                reasons=reasons[:5],
                signals=signals[:5],
                payment_signals=payment_signals[:3],
                suggested_action=suggested_action,
                opener=opener,
                account_scope=item.get("account_scope", ""),
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.days_since if item.days_since is not None else 9999, -item.msg_count))


def suggest_contact_action(relationship_type: str, deal_status: str, stage: str, signals: list[Signal], payment_signals: list[Signal]) -> str:
    categories = " ".join(signal.category for signal in signals[:3])
    if relationship_type == "同行/资源合作":
        return "不要当客户追单；把对方当内容、流量、渠道或案例共创对象，先明确双方资源和下一次合作动作。"
    if relationship_type == "我方购买/学习对象":
        return "这是你向对方学习/购买/加入后的资料关系，不纳入客户跟进；只在需要复盘竞品或社群打法时回看。"
    if relationship_type == "粉丝/免费咨询":
        return "低优先级，不主动销售；适合沉淀成 FAQ、公开内容或轻量社群答疑素材。"
    if relationship_type == "流失/退款客户":
        return "不要按待成交追；只做退款原因复盘，必要时低频维护关系。"
    if relationship_type == "对我营销":
        return "归档为对方营销，不纳入客户跟进；只有你主动想买或谈资源互换时再处理。"
    if relationship_type == "合作推广":
        if deal_status == "样品/合作推进中":
            return "推进合作交付：确认脚本、发布时间、验收口径和是否需要后续报价。"
        if deal_status == "已婉拒/暂缓":
            return "低优先级归档；除非对方给预算或明确排期，否则不主动追。"
        return "确认合作类型：付费投放、带货分佣、置换测评、还是联合项目；先问预算和交付要求。"
    if deal_status == "疑似已成交":
        return "旧阶段显示已付费但未找到明确转账证据；先核对是否已交付，再决定复购/转介绍或补成交记录。"
    if deal_status == "已成交" or payment_signals:
        if "售后/问题" in categories:
            return "这是已成交客户，优先处理交付/售后，再做复购或案例沉淀。"
        return "这是已成交客户，不再当作待成交线索；做交付回访、复购、转介绍或案例挖掘。"
    if "购买/报名" in categories:
        return "补一条低压力确认：对方现在卡在价格、报名、交付还是案例；给出一个明确下一步。"
    if "合作/渠道" in categories:
        return "确认合作目标、可置换资源、预算/分成方式；约一个 15 分钟语音。"
    if "售后/问题" in categories:
        return "先解决具体问题，再顺手沉淀成 FAQ 或教程素材。"
    if stage == "已付费":
        return "做一次使用回访，挖复购、转介绍或案例。"
    if stage == "产品咨询":
        return "把咨询归到一个明确场景，给一个最小可执行方案。"
    if stage == "新线索":
        return "轻触达，问对方现在最想解决的一个问题。"
    return "补一条上下文型跟进，判断是否仍有需求。"


def suggest_opener(name: str, relationship_type: str, deal_status: str, stage: str, signals: list[Signal], payment_signals: list[Signal]) -> str:
    if relationship_type in {"同行/资源合作", "我方购买/学习对象", "粉丝/免费咨询", "流失/退款客户"}:
        return ""
    if relationship_type == "对我营销":
        return ""
    if relationship_type == "合作推广":
        if deal_status == "样品/合作推进中":
            return f"{name}，样品我这边已经收到/在推进了。我先把脚本方向确认一下，你们这边有没有必须露出的卖点或发布时间要求？"
        if deal_status == "已婉拒/暂缓":
            return f"{name}，上次合作我这边暂时没排上。后面如果你们有明确预算或更适合 AI 工具用户的选题，可以再发我看看。"
        return f"{name}，我看你之前提到合作。你们这次更偏付费投放、置换测评，还是按转化分佣？预算和交付要求也一起发我，我判断下是否适合。"
    if deal_status == "疑似已成交":
        return f"{name}，我这边记录你之前应该已经开始使用/付费了。最近还有哪一步卡住，或者有没有需要我继续帮你推进的地方？"
    if deal_status == "已成交" or payment_signals:
        return f"{name}，你这边之前已经付过/开始交付了。最近用下来还有哪一步最卡？我可以顺手帮你梳理下一步。"
    if signals:
        snippet = signals[0].text
        if "购买/报名" in signals[0].category:
            return f"{name}，你之前问到「{snippet[:36]}」。现在还需要我帮你判断适合哪种方案吗？"
        if "售后/问题" in signals[0].category:
            return f"{name}，你上次那个问题现在解决了吗？如果还卡着，直接把当前状态发我，我帮你判断下一步。"
        if "合作/渠道" in signals[0].category:
            return f"{name}，你之前提到「{snippet[:36]}」。这件事现在还有需要我继续判断或推进的地方吗？"
        return f"{name}，你之前提到「{snippet[:36]}」。这件事现在进展到哪一步了？"
    if stage == "已付费":
        return f"{name}，你这边最近用下来有没有哪一步最卡？我想顺手把常见问题整理成一版更好用的说明。"
    return f"{name}，最近你这边 AI 工具/业务落地还有没有一个最想先解决的问题？我可以帮你判断一下优先级。"


def has_business_question(text: str) -> bool:
    return any(marker in text for marker in QUESTION_MARKERS) and any(marker in text for marker in BUSINESS_MARKERS)


def group_opportunities(exports: list[dict[str, Any]], owner_names: set[str], ignored_senders: set[str], now: datetime) -> list[Signal]:
    opportunities: list[Signal] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in exports:
        manifest = item["manifest"]
        if item.get("chat_type") != "group":
            continue
        raw_group_name = manifest.get("target_name") or item["dir"].name
        group_name = clean_name(raw_group_name)
        messages = item["messages"]
        for index, message in enumerate(messages):
            if message.type_name == "system":
                continue
            if message.sender in owner_names or message.sender == raw_group_name:
                continue
            if is_ignored_sender(message.sender, ignored_senders):
                continue
            if is_broadcast_like(message.text) or is_inbound_marketing_text(message.text):
                continue
            categories = detect_categories(message.text)
            actionable = is_actionable_signal(message.text, categories)
            if not actionable and not has_business_question(message.text):
                continue
            if len(message.text) > 700 and not is_direct_need(message.text):
                continue

            sender = clean_name(message.sender)
            signature = (group_name, sender, message.date, redact(message.text, limit=80))
            if signature in seen:
                continue
            seen.add(signature)

            score = 5 + 2 * len(categories)
            if "购买/报名" in categories or "合作/渠道" in categories:
                score += 5
            if "明确求助" in categories:
                score += 4
            msg_time = parse_time(message.timestamp)
            if msg_time:
                score += recency_score((now - msg_time).days)

            later_owner_reply = any(next_msg.sender in owner_names for next_msg in messages[index + 1 : index + 12])
            reply_gap = "" if later_owner_reply else "后续 11 条内未见你回复"
            if reply_gap:
                score += 5

            opportunities.append(
                Signal(
                    category=" / ".join(categories) if categories else "业务问题",
                    date=message.date,
                    sender=sender,
                    text=redact(message.text),
                    score=score,
                    source=group_name,
                    reply_gap=reply_gap,
                    account_scope=item.get("account_scope", ""),
                )
            )
    return sorted(opportunities, key=lambda signal: (-signal.score, signal.date))


def build_themes(exports: list[dict[str, Any]], owner_names: set[str], ignored_senders: set[str]) -> list[dict[str, Any]]:
    theme_counts: dict[str, Counter[str]] = defaultdict(Counter)
    theme_examples: dict[str, list[Signal]] = defaultdict(list)
    for item in exports:
        manifest = item["manifest"]
        if item.get("chat_type") not in {"contact", "group"}:
            continue
        source = clean_name(manifest.get("target_name") or item["dir"].name)
        for message in item["messages"]:
            if message.type_name == "system" or message.sender in owner_names:
                continue
            if is_ignored_sender(message.sender, ignored_senders):
                continue
            if is_broadcast_like(message.text) or is_inbound_marketing_text(message.text):
                continue
            for theme in theme_hits(message.text):
                theme_counts[theme]["messages"] += 1
                if message.sender:
                    theme_counts[theme][f"sender:{message.sender}"] += 1
                if len(theme_examples[theme]) < 4 and len(message.text) >= 8:
                    theme_examples[theme].append(
                        Signal(
                            category=theme,
                            date=message.date,
                            sender=clean_name(message.sender),
                            text=redact(message.text, limit=140),
                            score=1,
                            source=source,
                            account_scope=item.get("account_scope", ""),
                        )
                    )

    rows = []
    for theme, counts in theme_counts.items():
        sender_count = sum(1 for key in counts if key.startswith("sender:"))
        rows.append(
            {
                "theme": theme,
                "message_count": counts["messages"],
                "sender_count": sender_count,
                "examples": theme_examples[theme],
            }
        )
    return sorted(rows, key=lambda row: (-row["message_count"], -row["sender_count"]))


def markdown_table(rows: list[list[str]], headers: list[str]) -> str:
    def cell(value: str) -> str:
        return str(value).replace("\n", " ").replace("|", "\\|")

    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def render_report(
    contacts: list[ContactRadar],
    groups: list[Signal],
    themes: list[dict[str, Any]],
    enrichment: dict[str, Any],
    exports: list[dict[str, Any]],
    owner_names: set[str],
    self_accounts: set[str],
    now: datetime,
) -> str:
    contact_count = len(contacts)
    group_count = sum(1 for item in exports if item.get("chat_type") == "group")
    message_count = sum(len(item["messages"]) for item in exports)
    date = now.strftime("%Y-%m-%d")
    account_scopes = sorted({item.get("account_scope", "default") for item in exports})
    chat_type_counts = Counter(item.get("chat_type", "unknown") for item in exports)

    customer_prospects = [
        contact
        for contact in contacts
        if contact.relationship_type == "客户" and contact.deal_status not in {"已成交", "疑似已成交"} and contact.score >= 10
    ][:20]
    converted_customers = [
        contact
        for contact in contacts
        if contact.relationship_type == "客户" and contact.deal_status in {"已成交", "疑似已成交"}
    ][:20]
    partners = [
        contact
        for contact in contacts
        if contact.relationship_type == "合作推广" and contact.score >= 10
    ][:20]
    relationship_non_customer = [
        contact
        for contact in contacts
        if contact.relationship_type in {"同行/资源合作", "我方购买/学习对象", "粉丝/免费咨询", "流失/退款客户"}
    ][:30]
    inbound_marketers = [
        contact
        for contact in contacts
        if contact.relationship_type == "对我营销"
    ][:20]
    uncategorized = [contact for contact in contacts if contact.relationship_type == "待分类"]
    hot_groups = groups[:30]

    relationship_counts = Counter(contact.relationship_type for contact in contacts)
    status_counts = Counter(contact.deal_status for contact in contacts)

    lines = [
        f"# 微信商机雷达 - {date}",
        "",
        "## 数据范围",
        "",
        f"- 账号范围：{', '.join(account_scopes) if account_scopes else '无'}",
        f"- 私聊联系人：{contact_count}",
        f"- 群聊：{group_count}",
        f"- 已过滤公众号/系统/折叠入口：公众号 {chat_type_counts.get('official_account', 0)}；系统 {chat_type_counts.get('system', 0)}；折叠 {chat_type_counts.get('folded', 0)}",
        f"- 可分析消息：{message_count}",
        f"- 收藏条目：{enrichment.get('total_favorites', 0)}；本地朋友圈缓存：{enrichment.get('total_sns_posts', 0)}",
        f"- 识别到的本人昵称：{', '.join(sorted(owner_names)) if owner_names else '未识别'}",
        f"- 已排除自有账号：{', '.join(sorted(self_accounts)) if self_accounts else '无'}",
        f"- 客户：{relationship_counts.get('客户', 0)}；合作推广：{relationship_counts.get('合作推广', 0)}；同行/资源合作：{relationship_counts.get('同行/资源合作', 0)}；粉丝/免费咨询：{relationship_counts.get('粉丝/免费咨询', 0)}；对我营销：{relationship_counts.get('对我营销', 0)}；待分类：{relationship_counts.get('待分类', 0)}",
        f"- 已成交客户：{status_counts.get('已成交', 0)}；疑似已成交：{status_counts.get('疑似已成交', 0)}；高意向未成交：{status_counts.get('高意向未成交', 0)}；待评估合作：{status_counts.get('待评估合作', 0)}",
        "",
        "## 客户：高意向未成交 / 待转化",
        "",
    ]

    if customer_prospects:
        rows = []
        for contact in customer_prospects:
            signal = contact.signals[0] if contact.signals else None
            rows.append(
                [
                    str(contact.score),
                    contact.deal_status,
                    contact.name,
                    contact.last_date or "",
                    "；".join(contact.reasons),
                    signal.text if signal else "",
                    contact.suggested_action,
                ]
            )
        lines.append(markdown_table(rows, ["分", "状态", "联系人", "最近", "为什么", "信号摘录", "建议动作"]))
    else:
        lines.append("暂无高意向待转化客户。")

    lines.extend(["", "## 已成交 / 疑似已成交客户：交付 / 复购 / 转介绍", ""])
    if converted_customers:
        rows = []
        for contact in converted_customers:
            payment = contact.payment_signals[0].text if contact.payment_signals else ""
            signal = contact.signals[0].text if contact.signals else ""
            rows.append(
                [
                    str(contact.score),
                    contact.deal_status,
                    contact.name,
                    contact.last_date or "",
                    payment,
                    "；".join(contact.reasons),
                    signal,
                    contact.suggested_action,
                ]
            )
        lines.append(markdown_table(rows, ["分", "状态", "联系人", "最近", "成交证据", "为什么", "近期信号", "建议动作"]))
    else:
        lines.append("暂无已成交客户证据。")

    lines.extend(["", "## 合作推广 / 商务合作", ""])
    if partners:
        rows = []
        for contact in partners:
            signal = contact.signals[0] if contact.signals else None
            rows.append(
                [
                    str(contact.score),
                    contact.deal_status,
                    contact.name,
                    contact.last_date or "",
                    "；".join(contact.reasons),
                    signal.text if signal else "",
                    contact.suggested_action,
                ]
            )
        lines.append(markdown_table(rows, ["分", "状态", "合作方", "最近", "为什么", "信号摘录", "建议动作"]))
    else:
        lines.append("暂无高优先级合作推广方。")

    lines.extend(["", "## 非客户关系：资源 / 学习 / 免费咨询 / 退款", ""])
    if relationship_non_customer:
        rows = []
        for contact in relationship_non_customer:
            rows.append(
                [
                    contact.relationship_type,
                    contact.deal_status,
                    contact.name,
                    contact.last_date or "",
                    "；".join(contact.reasons),
                    contact.suggested_action,
                ]
            )
        lines.append(markdown_table(rows, ["关系", "状态", "联系人", "最近", "为什么", "建议动作"]))
    else:
        lines.append("暂无需要单独归档的非客户关系。")

    lines.extend(["", "## 对我营销 / 卖课：不纳入客户跟进", ""])
    if inbound_marketers:
        rows = []
        for contact in inbound_marketers:
            rows.append(
                [
                    contact.deal_status,
                    contact.name,
                    contact.last_date or "",
                    "；".join(contact.reasons),
                    contact.suggested_action,
                ]
            )
        lines.append(markdown_table(rows, ["状态", "联系人", "最近", "为什么", "建议动作"]))
    else:
        lines.append("暂无明显对我营销联系人。")

    if uncategorized:
        lines.extend(["", "## 待分类联系人", ""])
        rows = [[contact.name, contact.last_date or "", str(contact.msg_count)] for contact in uncategorized[:20]]
        lines.append(markdown_table(rows, ["联系人", "最近", "消息数"]))

    lines.extend(["", "## 可直接发送的开场白", ""])
    opener_contacts = customer_prospects[:6] + converted_customers[:4] + partners[:6]
    for index, contact in enumerate(opener_contacts[:16], 1):
        lines.append(f"{index}. **{contact.name}**：{contact.opener}")

    lines.extend(["", "## 群聊未处理机会", ""])
    if hot_groups:
        rows = []
        for signal in hot_groups:
            rows.append([str(signal.score), signal.date, signal.source, signal.sender, signal.category, signal.reply_gap, signal.text])
        lines.append(markdown_table(rows, ["分", "日期", "群", "发言人", "类型", "回复状态", "信号摘录"]))
    else:
        lines.append("暂无明显群聊机会。")

    lines.extend(["", "## 收藏与朋友圈辅助信号", ""])
    enrichment_accounts = enrichment.get("accounts", [])
    if enrichment_accounts:
        rows = []
        for account in enrichment_accounts:
            favorite = account.get("favorites", {})
            sns = account.get("sns", {})
            account_themes = "；".join(f"{item['theme']} {item['count']}" for item in account.get("theme_counts", [])[:4])
            rows.append(
                [
                    account.get("account_scope", ""),
                    favorite.get("status", "unavailable"),
                    str(favorite.get("total", 0)),
                    sns.get("status", "unavailable"),
                    str(sns.get("total", 0)),
                    account_themes,
                ]
            )
        lines.append(markdown_table(rows, ["账号", "收藏状态", "收藏数", "朋友圈状态", "朋友圈数", "近期辅助主题"]))
        if enrichment.get("theme_counts"):
            lines.append("")
            theme_line = "；".join(f"{item['theme']} {item['count']}" for item in enrichment.get("theme_counts", [])[:8])
            lines.append(f"- 近期收藏/朋友圈主题摘要：{theme_line}")
    else:
        lines.append("未发现可用的收藏或朋友圈缓存。")

    lines.extend(["", "## 客户语言与需求主题", ""])
    if themes:
        rows = [[row["theme"], str(row["message_count"]), str(row["sender_count"])] for row in themes[:12]]
        lines.append(markdown_table(rows, ["主题", "消息数", "发言人数"]))
        lines.append("")
        for row in themes[:8]:
            lines.append(f"### {row['theme']}")
            for example in row["examples"][:3]:
                lines.append(f"- {example.date} / {example.source} / {example.sender}：{example.text}")
            lines.append("")
    else:
        lines.append("暂无足够主题信号。")

    lines.extend(
        [
            "## 下一步工作流",
            "",
            "1. 先处理 `客户：高意向未成交 / 待转化`，这是最接近收入的部分。",
            "2. `已成交 / 疑似已成交客户` 不再当待成交线索追，要先核对交付状态，再做复购、案例和转介绍。",
            "3. `合作推广 / 商务合作` 单独看预算、交付要求、排期和是否匹配你的受众。",
            "4. `对我营销 / 卖课` 默认不跟进，避免把别人发给你的广告误当成客户意向。",
            "5. 群聊机会只处理高分项：先在群里补一句有价值的回复，再选择是否私聊。",
            "6. 每周把 `客户语言与需求主题` 前 5 个主题转成内容选题、FAQ 或产品说明。",
            "",
            "> 报告中的长数字、API key、wxid、邮箱、手机号、身份证号已做正则脱敏。仍建议只在本地使用，不公开同步。",
            "",
        ]
    )
    return "\n".join(lines)


def write_json_report(
    path: Path,
    contacts: list[ContactRadar],
    groups: list[Signal],
    themes: list[dict[str, Any]],
    enrichment: dict[str, Any],
    now: datetime,
) -> None:
    group_state_map: dict[tuple[str, str], dict[str, Any]] = {}
    for signal in groups:
        key = (signal.account_scope, signal.source)
        item = group_state_map.setdefault(
            key,
            {
                "account_scope": signal.account_scope,
                "group": signal.source,
                "opportunity_count": 0,
                "top_score": 0,
                "latest_date": "",
                "top_categories": Counter(),
            },
        )
        item["opportunity_count"] += 1
        item["top_score"] = max(item["top_score"], signal.score)
        if signal.date > item["latest_date"]:
            item["latest_date"] = signal.date
        if signal.category:
            item["top_categories"][signal.category] += 1
    group_states = []
    for item in group_state_map.values():
        top_categories = item.pop("top_categories")
        item["top_categories"] = [{"category": key, "count": value} for key, value in top_categories.most_common(5)]
        group_states.append(item)
    group_states.sort(key=lambda item: (-item["top_score"], -item["opportunity_count"], item["group"]))
    data = {
        "generated_at": now.isoformat(),
        "relationship_states": [
            {
                "account_scope": contact.account_scope,
                "name": contact.name,
                "relationship_type": contact.relationship_type,
                "deal_status": contact.deal_status,
                "stage": contact.stage,
                "score": contact.score,
                "last_date": contact.last_date,
                "suggested_action": contact.suggested_action,
            }
            for contact in contacts
        ],
        "group_states": group_states,
        "contacts": [
            {
                "account_scope": contact.account_scope,
                "name": contact.name,
                "relationship_type": contact.relationship_type,
                "deal_status": contact.deal_status,
                "stage": contact.stage,
                "score": contact.score,
                "msg_count": contact.msg_count,
                "last_date": contact.last_date,
                "days_since": contact.days_since,
                "reasons": contact.reasons,
                "suggested_action": contact.suggested_action,
                "opener": contact.opener,
                "payment_signals": [signal.__dict__ for signal in contact.payment_signals],
                "signals": [signal.__dict__ for signal in contact.signals],
            }
            for contact in contacts
        ],
        "enrichment": enrichment,
        "group_opportunities": [signal.__dict__ for signal in groups],
        "themes": [
            {
                "theme": row["theme"],
                "message_count": row["message_count"],
                "sender_count": row["sender_count"],
                "examples": [signal.__dict__ for signal in row["examples"]],
            }
            for row in themes
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def week_id(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def render_weekly_report(
    contacts: list[ContactRadar],
    groups: list[Signal],
    themes: list[dict[str, Any]],
    enrichment: dict[str, Any],
    now: datetime,
) -> str:
    weekly_id = week_id(now)
    customer_actions = [
        contact for contact in contacts
        if contact.relationship_type == "客户" and contact.deal_status not in {"已成交", "疑似已成交"}
    ][:15]
    converted = [
        contact for contact in contacts
        if contact.relationship_type == "客户" and contact.deal_status in {"已成交", "疑似已成交"}
    ][:10]
    partners = [contact for contact in contacts if contact.relationship_type == "合作推广"][:10]
    relationship_counts = Counter(contact.relationship_type for contact in contacts)
    status_counts = Counter(contact.deal_status for contact in contacts)
    lines = [
        f"# 微信商机周报 - {weekly_id}",
        "",
        "## 本周处理队列",
        "",
        f"- 待转化客户：{len(customer_actions)}",
        f"- 已成交/疑似已成交客户：{len(converted)}",
        f"- 合作推广对象：{len(partners)}",
        f"- 群聊机会：{len(groups)}",
        f"- 收藏条目：{enrichment.get('total_favorites', 0)}；本地朋友圈缓存：{enrichment.get('total_sns_posts', 0)}",
        f"- 客户：{relationship_counts.get('客户', 0)}；合作推广：{relationship_counts.get('合作推广', 0)}；对我营销：{relationship_counts.get('对我营销', 0)}",
        f"- 已成交：{status_counts.get('已成交', 0)}；高意向未成交：{status_counts.get('高意向未成交', 0)}；待评估合作：{status_counts.get('待评估合作', 0)}",
        "",
        "## 优先跟进",
        "",
    ]
    if customer_actions:
        rows = [
            [str(contact.score), contact.account_scope, contact.deal_status, contact.name, contact.suggested_action]
            for contact in customer_actions[:10]
        ]
        lines.append(markdown_table(rows, ["分", "账号", "状态", "联系人", "建议动作"]))
    else:
        lines.append("暂无待转化客户。")
    lines.extend(["", "## 合作与复购", ""])
    rows = [
        [contact.relationship_type, contact.account_scope, contact.deal_status, contact.name, contact.suggested_action]
        for contact in (converted[:5] + partners[:5])
    ]
    if rows:
        lines.append(markdown_table(rows, ["关系", "账号", "状态", "对象", "建议动作"]))
    else:
        lines.append("暂无合作或复购队列。")
    lines.extend(["", "## 内容/产品主题", ""])
    if themes:
        rows = [[row["theme"], str(row["message_count"]), str(row["sender_count"])] for row in themes[:8]]
        lines.append(markdown_table(rows, ["主题", "消息数", "发言人数"]))
    else:
        lines.append("暂无主题数据。")
    if enrichment.get("theme_counts"):
        lines.extend(["", "## 收藏/朋友圈辅助主题", ""])
        rows = [[item["theme"], str(item["count"])] for item in enrichment.get("theme_counts", [])[:8]]
        lines.append(markdown_table(rows, ["主题", "近期样本数"]))
    lines.extend(["", "> 周报由同一份账号隔离 radar 数据生成，默认只保留摘要和建议动作。", ""])
    return "\n".join(lines)


def write_weekly_json_report(
    path: Path,
    contacts: list[ContactRadar],
    groups: list[Signal],
    themes: list[dict[str, Any]],
    enrichment: dict[str, Any],
    now: datetime,
) -> None:
    data = {
        "generated_at": now.isoformat(),
        "week": week_id(now),
        "relationship_counts": Counter(contact.relationship_type for contact in contacts),
        "deal_status_counts": Counter(contact.deal_status for contact in contacts),
        "follow_up_queue": [
            {
                "account_scope": contact.account_scope,
                "name": contact.name,
                "relationship_type": contact.relationship_type,
                "deal_status": contact.deal_status,
                "score": contact.score,
                "suggested_action": contact.suggested_action,
            }
            for contact in contacts[:30]
        ],
        "group_opportunity_count": len(groups),
        "enrichment": enrichment,
        "top_themes": [
            {
                "theme": row["theme"],
                "message_count": row["message_count"],
                "sender_count": row["sender_count"],
            }
            for row in themes[:12]
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a business opportunity radar report from WeChat exports")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="WeChat export output root")
    parser.add_argument("--crm", default=str(DEFAULT_CRM_PATH), help="CRM dashboard JSON path")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directory for generated reports")
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES_PATH), help="Manual correction JSON path")
    parser.add_argument("--sync-manifest", default=str(DEFAULT_SYNC_MANIFEST), help="Synced account database manifest")
    parser.add_argument("--date", default="", help="Override report date as YYYY-MM-DD")
    args = parser.parse_args()

    output_root = Path(args.output_root).expanduser().resolve()
    crm_path = Path(args.crm).expanduser().resolve()
    report_dir = Path(args.report_dir).expanduser().resolve()
    overrides_path = Path(args.overrides).expanduser().resolve()
    sync_manifest_path = Path(args.sync_manifest).expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.strptime(args.date, "%Y-%m-%d") if args.date else datetime.now()
    exports = load_exports(output_root)
    crm_lookup = build_crm_lookup(crm_path)
    overrides = load_overrides(overrides_path)
    owner_names = infer_owner_names(exports)
    owner_names.update(overrides.get("self_accounts", set()))
    contacts = make_contact_radar(exports, crm_lookup, owner_names, overrides, now)
    ignored_senders = overrides.get("inbound_marketing_senders", set())
    groups = group_opportunities(exports, owner_names, ignored_senders, now)
    themes = build_themes(exports, owner_names, ignored_senders)
    enrichment = build_enrichment(sync_manifest_path)

    stamp = now.strftime("%Y-%m-%d")
    md_path = report_dir / f"opportunity_radar_{stamp}.md"
    json_path = report_dir / f"opportunity_radar_{stamp}.json"
    weekly_md_path = report_dir / f"opportunity_radar_weekly_{week_id(now)}.md"
    weekly_json_path = report_dir / f"opportunity_radar_weekly_{week_id(now)}.json"
    md_path.write_text(
        render_report(contacts, groups, themes, enrichment, exports, owner_names, overrides.get("self_accounts", set()), now),
        encoding="utf-8",
    )
    write_json_report(json_path, contacts, groups, themes, enrichment, now)
    weekly_md_path.write_text(render_weekly_report(contacts, groups, themes, enrichment, now), encoding="utf-8")
    write_weekly_json_report(weekly_json_path, contacts, groups, themes, enrichment, now)

    print(f"Markdown report: {md_path}")
    print(f"JSON report: {json_path}")
    print(f"Weekly Markdown report: {weekly_md_path}")
    print(f"Weekly JSON report: {weekly_json_path}")
    counts = Counter(contact.relationship_type for contact in contacts)
    statuses = Counter(contact.deal_status for contact in contacts)
    print(f"Customers: {counts.get('客户', 0)}")
    print(f"Promotion partners: {counts.get('合作推广', 0)}")
    print(f"Inbound marketers: {counts.get('对我营销', 0)}")
    print(f"Converted customers: {statuses.get('已成交', 0)}")
    print(f"Suspected converted customers: {statuses.get('疑似已成交', 0)}")
    print(f"High-intent prospects: {statuses.get('高意向未成交', 0)}")
    print(f"Group opportunities: {len(groups)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
