import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def load_messages(messages_path: Path) -> List[dict]:
    items = []
    with messages_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def count_attachment_files(markdown_root: Path) -> int:
    total = 0
    for attachment_dir in markdown_root.glob("*/attachments"):
        if not attachment_dir.is_dir():
            continue
        total += sum(1 for path in attachment_dir.rglob("*") if path.is_file())
    return total


TECHNICAL_KEYWORDS = {
    "aeskey", "appattach", "appid", "appinfo", "appmsg", "bufid", "cdata", "clientmsgid",
    "content", "duration", "endflag", "forwardflag", "fromusername", "length", "md5",
    "msg", "msgsource", "null", "scene", "signature", "size", "source", "thumb", "title",
    "type", "username", "version", "voiceformat", "voicelength", "voicemsg", "voicemd",
    "voiceurl", "wxid",
}

ENGLISH_KEYWORD_ALLOWLIST = {
    "agent", "agents", "ai", "api", "claude", "code", "codex", "cursor", "deepseek",
    "github", "gpt", "hermes", "mcp", "openai", "openclaw", "prompt", "sop", "skill",
    "skills", "workflow", "xhs",
}


def keyword_text(item: dict) -> str:
    text = item.get("formatted_markdown") or ""
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\bwxid_[a-z0-9_]+:?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return text


def useful_keyword(word: str) -> bool:
    word = word.lower()
    if word in TECHNICAL_KEYWORDS:
        return False
    if re.search(r"\d", word):
        return False
    if len(word) >= 12 and re.fullmatch(r"[a-z0-9_]+", word):
        return False
    if re.fullmatch(r"[a-z]+", word) and word not in ENGLISH_KEYWORD_ALLOWLIST:
        return False
    return True


def compute_stats(items: List[dict], markdown_root: Path) -> dict:
    total = len(items)
    if total == 0:
        return {
            "total": 0,
            "first_date": "无",
            "last_date": "无",
            "span_days": 0,
            "daily_avg": 0,
            "type_dist": [],
            "sender_top": [],
            "monthly_trend": [],
            "hour_dist": [{"hour": h, "count": 0} for h in range(24)],
            "weekday_dist": [{"day": day, "count": 0} for day in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]],
            "busiest_day": "无",
            "busiest_count": 0,
            "keywords": [],
            "link_count": 0,
            "media_count": 0,
            "file_count": count_attachment_files(markdown_root),
            "note": "没有聊天数据",
        }

    timestamps = [item["timestamp"] for item in items if item.get("timestamp")]
    if timestamps:
        dates = sorted(timestamps)
        first_date = dates[0][:10]
        last_date = dates[-1][:10]
        first_dt = datetime.fromisoformat(first_date)
        last_dt = datetime.fromisoformat(last_date)
        span_days = (last_dt - first_dt).days + 1
    else:
        first_date = "未知"
        last_date = "未知"
        span_days = 0

    type_counter = Counter(item.get("type_name", "unknown") for item in items)
    sender_counter = Counter(item.get("sender_name", "") for item in items if item.get("sender_name"))

    daily = Counter()
    monthly = Counter()
    hourly = Counter()
    weekday = Counter()
    link_count = 0
    media_count = 0
    file_count = count_attachment_files(markdown_root)

    texts = []
    keyword_texts = []
    for item in items:
        text = (item.get("decoded_text") or "") + "\n" + (item.get("formatted_markdown") or "")
        texts.append(text)
        keyword_texts.append(keyword_text(item))
        if re.search(r"https?://", text):
            link_count += 1
        if item.get("type_name") in {"image", "video", "voice", "emoji"}:
            media_count += 1
        if item.get("timestamp"):
            dt_value = datetime.fromisoformat(item["timestamp"])
            daily[dt_value.strftime("%Y-%m-%d")] += 1
            monthly[dt_value.strftime("%Y-%m")] += 1
            hourly[dt_value.hour] += 1
            weekday[dt_value.weekday()] += 1

    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", " ".join(keyword_texts))
    stopwords = {
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一个", "这个", "那个",
        "可以", "没有", "然后", "但是", "因为", "所以", "the", "and", "for", "that", "this", "with",
        "http", "https", "www", "com", "org", "html",
    }
    word_counter = Counter(
        word.lower()
        for word in words
        if word.lower() not in stopwords and useful_keyword(word)
    )

    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    busiest_day, busiest_count = daily.most_common(1)[0] if daily else ("未知", 0)

    return {
        "total": total,
        "first_date": first_date,
        "last_date": last_date,
        "span_days": span_days,
        "daily_avg": round(total / max(span_days, 1), 1),
        "type_dist": [{"name": k, "value": v} for k, v in type_counter.most_common()],
        "sender_top": [{"name": k, "value": v} for k, v in sender_counter.most_common(20)],
        "monthly_trend": [{"month": k, "count": v} for k, v in sorted(monthly.items())],
        "hour_dist": [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)],
        "weekday_dist": [{"day": weekday_names[d], "count": weekday.get(d, 0)} for d in range(7)],
        "busiest_day": busiest_day,
        "busiest_count": busiest_count,
        "keywords": [{"name": k, "value": v} for k, v in word_counter.most_common(80)],
        "link_count": link_count,
        "media_count": media_count,
        "file_count": file_count,
    }


def build_analysis_input(manifest: dict, stats: dict) -> str:
    top_senders = "\n".join(
        f"- {item['name']}: {item['value']} 条" for item in stats.get("sender_top", [])[:10]
    ) or "- 无"
    top_keywords = "\n".join(
        f"- {item['name']}: {item['value']}" for item in stats.get("keywords", [])[:20]
    ) or "- 无"

    return f"""# 微信聊天分析输入

## 会话信息
- 对象名称：{manifest.get('target_name')}
- 对象 ID：{manifest.get('target_id')}
- 消息数量：{manifest.get('message_count')}

## 时间范围
- 第一条日期：{stats.get('first_date')}
- 最后一条日期：{stats.get('last_date')}
- 覆盖天数：{stats.get('span_days')}
- 日均消息数：{stats.get('daily_avg')}
- 最活跃日期：{stats.get('busiest_day')}（{stats.get('busiest_count')} 条）

## 高频发言人
{top_senders}

## 高频关键词
{top_keywords}

## 信号指标
- 链接消息数：{stats.get('link_count')}
- 媒体消息数：{stats.get('media_count')}
- 附件文件数：{stats.get('file_count')}

## 数据路径
- messages_jsonl：{manifest.get('messages_jsonl')}
- markdown_root：{manifest.get('markdown_root')}
- output_root：{manifest.get('output_root')}

## 希望 AI 生成的内容
- 摘要
- 高价值信息
- 待办事项
- 垃圾过滤摘要
- 保留原始聊天记录用于核对
"""


def main():
    parser = argparse.ArgumentParser(description="Build analysis bundle for exported WeChat chat")
    parser.add_argument("--export-dir", required=True)
    args = parser.parse_args()

    export_dir = Path(args.export_dir).expanduser()
    manifest_path = export_dir / "manifest.json"
    messages_path = export_dir / "messages.jsonl"
    stats_path = export_dir / "stats.json"
    analysis_input_path = export_dir / "analysis_input.md"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = load_messages(messages_path)
    stats = compute_stats(items, Path(manifest["markdown_root"]))

    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_input_path.write_text(build_analysis_input(manifest, stats), encoding="utf-8")
    print(json.dumps({
        "stats": str(stats_path),
        "analysis_input": str(analysis_input_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
