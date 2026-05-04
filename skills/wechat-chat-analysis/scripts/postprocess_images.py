#!/usr/bin/env python3
"""Post-process exported WeChat markdown files: inline decoded images and attach file links."""
import base64
import html
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import zstandard as zstd
except ImportError:
    sys.exit("[!] zstandard not installed. Run: pip install zstandard")


def decode_content(raw: bytes) -> bytes:
    if not raw:
        return b""
    if raw[:4] == b"\x28\xb5\x2f\xFD":
        try:
            return zstd.ZstdDecompressor().decompress(raw, max_output_size=100 * 1024 * 1024)
        except Exception:
            return raw
    return raw


def xml_attr(s: str, tag: str, attr: str) -> str:
    m = re.search(rf'<{tag}[^>]*\b{attr}="([^"]+)"', s, re.DOTALL)
    return html.unescape(m.group(1).strip()) if m else ""


def xml_field(s: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.DOTALL)
    return html.unescape(m.group(1).strip()) if m else ""


def try_decode_image(file_path: Path) -> Optional[Path]:
    """Try XOR-based image decoding. Returns path to decoded file on success."""
    if not file_path.exists():
        return None
    data = file_path.read_bytes()
    signatures = [
        (b"\xff\xd8\xff", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"GIF8", ".gif"),
        (b"BM", ".bmp"),
    ]
    for start_offset in range(0, 64):
        body = data[start_offset:]
        for xor_key in range(256):
            probe = bytes(b ^ xor_key for b in body[:16])
            decoded_body = bytes(b ^ xor_key for b in body)
            for sig, ext in signatures:
                if probe.startswith(sig):
                    out = file_path.with_suffix(ext)
                    out.write_bytes(decoded_body)
                    return out
            if len(probe) >= 12 and probe[:4] == b"RIFF":
                webp_probe = bytes(b ^ xor_key for b in body[8:12])
                if webp_probe == b"WEBP":
                    out = file_path.with_suffix(".webp")
                    out.write_bytes(decoded_body)
                    return out
    return None


def load_messages_jsonl(messages_path: Path) -> List[Dict]:
    records = []
    for line in messages_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def resolve_sender_name(sender_id: int, sender_lookup: Dict[int, str], contacts: Dict) -> str:
    user_name = sender_lookup.get(sender_id, "")
    if not user_name:
        return "未知"
    if user_name in contacts:
        info = contacts[user_name]
        for key in ("remark", "nickname", "alias"):
            val = (info.get(key) or "").strip()
            if val:
                return val
    return user_name


def get_image_md5_from_xml(text: str) -> str:
    return xml_attr(text, "img", "md5") or xml_attr(text, "img", "aeskey") or ""


def format_image_block(md5: str, attachment_dir: Path, month_dir: Path, size_hints: dict) -> str:
    """Match files by size hints (like export_chat.py) and produce descriptive links."""
    if not attachment_dir.exists():
        return "[图片]"

    files = list(attachment_dir.glob("*"))
    size_map = {}  # size -> list of files with that size

    for f in files:
        if f.suffix == ".dat":
            sz = f.stat().st_size
            size_map.setdefault(sz, []).append(f)
            size_map.setdefault(sz - 31, []).append(f)  # try with header offset

    candidates = {"thumb": None, "mid": None, "hd": None}
    for kind, expected in size_hints.items():
        if not expected:
            continue
        # Try exact match and +31 offset
        for sz in (expected, expected + 31):
            if sz in size_map:
                # Pick the .dat file with the right suffix for the kind
                for f in size_map[sz]:
                    if kind == "thumb" and f.name.endswith("_t.dat"):
                        candidates[kind] = f
                        break
                    elif kind == "hd" and f.name.endswith("_h.dat"):
                        candidates[kind] = f
                        break
                    elif kind == "mid" and not f.name.endswith("_t.dat") and not f.name.endswith("_h.dat"):
                        candidates[kind] = f
                        break
                if candidates[kind]:
                    break

    links = []
    for kind, label in [("thumb", "缩略图"), ("mid", "图片"), ("hd", "原图")]:
        f = candidates[kind]
        if f:
            rel = f.relative_to(month_dir)
            links.append(f"[{label}]({rel.as_posix()})")

    if links:
        return "[图片]\n\n" + " | ".join(links)

    # Fallback: all .dat files
    for f in sorted(files):
        if f.suffix == ".dat":
            rel = f.relative_to(month_dir)
            links.append(f"[附件]({rel.as_posix()})")

    if links:
        return "[图片]\n\n" + " | ".join(links)
    return "[图片]"


def format_voice_block(text: str, attachment_dir: Path, month_dir: Path) -> str:
    voice_len = xml_attr(text, "voicemsg", "voicelength")
    length_s = f" ({voice_len}ms)" if voice_len else ""
    if not attachment_dir.exists():
        return f"[语音{length_s}]"
    files = list(attachment_dir.glob("*"))
    links = []
    for f in sorted(files):
        rel = f.relative_to(month_dir)
        links.append(f"[音频]({rel.as_posix()})")
    if links:
        return f"[语音{length_s}]\n\n" + "\n".join(links)
    return f"[语音{length_s}]"


def format_other_media(text: str, attachment_dir: Path, month_dir: Path) -> str:
    if not attachment_dir.exists():
        return None
    files = list(attachment_dir.glob("*"))
    links = []
    for f in sorted(files):
        rel = f.relative_to(month_dir)
        links.append(f"[附件]({rel.as_posix()})")
    if links:
        return "\n\n".join(links)
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", required=True)
    args = parser.parse_args()

    export_dir = Path(args.export_dir).expanduser()
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    target_name = manifest["target_name"]
    messages_path = export_dir / "messages.jsonl"
    markdown_root = Path(manifest["markdown_root"])

    records = load_messages_jsonl(messages_path)
    updated = 0

    for record in records:
        lt = record.get("local_type")
        ts = record.get("timestamp")
        if not ts:
            continue
        month_key = ts[:7]
        month_md = markdown_root / month_key
        attach_dir = month_md / "attachments"
        decoded_text = record.get("decoded_text") or ""
        type_name = record.get("type_name") or ""
        sender_name = record.get("sender_name") or ""
        day_key = ts[:10]
        time_part = ts[11:19]
        raw_content = record.get("decoded_text") or ""

        if lt == 3:  # image
            md5 = get_image_md5_from_xml(raw_content)
            size_hints = {
                "thumb": int(xml_attr(raw_content, "img", "cdnthumblength") or 0),
                "mid": int(xml_attr(raw_content, "img", "length") or 0),
                "hd": int(xml_attr(raw_content, "img", "hdlength") or 0),
            }
            body = format_image_block(md5, attach_dir, month_md, size_hints)
        elif lt == 34:  # voice
            body = format_voice_block(raw_content, attach_dir, month_md)
        elif lt in (43, 47):  # video/emoji
            body = format_other_media(raw_content, attach_dir, month_md)
        else:
            body = None

        current = record.get("formatted_markdown") or ""
        has_links = lambda s: "[附件]" in s or "[缩略图]" in s or "[图片]" in s or "[原图]" in s
        current_link_count = current.count("|") + 1 if has_links(current) else 0
        new_link_count = body.count("|") + 1 if body and has_links(body) else 0

        # Update if: we found matches AND (current had no links, or current shows ALL files in dir)
        attach_count = len(list(attach_dir.glob("*.dat"))) if attach_dir.exists() else 999
        is_fallback = current_link_count >= min(5, attach_count)

        if body and new_link_count > 0 and (current_link_count == 0 or is_fallback):
            record["formatted_markdown"] = body
            updated += 1

    # Rewrite messages.jsonl
    with messages_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Updated {updated} / {len(records)} records")

    # Rewrite markdown files
    by_day = {}
    for record in records:
        ts = record.get("timestamp")
        if not ts:
            continue
        day_key = ts[:10]
        by_day.setdefault(day_key, []).append(record)

    for day_key in sorted(by_day.keys()):
        month = day_key[:7]
        month_md = markdown_root / month
        lines = [f"# {day_key} · {target_name}", ""]
        for rec in sorted(by_day[day_key], key=lambda r: r.get("timestamp") or ""):
            ts = rec.get("timestamp") or ""
            sender = rec.get("sender_name") or ""
            type_name = rec.get("type_name") or ""
            time_part = ts[11:19] if len(ts) > 11 else "??"
            body = rec.get("formatted_markdown") or "_(空)_"
            lines.append(f"## {time_part} · {sender} · {type_name}")
            lines.append("")
            lines.append(body)
            lines.append("")
        content = "\n".join(lines)
        (month_md / f"{day_key}.md").write_text(content, encoding="utf-8")
        print(f"Rewrote {month_md / day_key}.md")

    print("Done.")


if __name__ == "__main__":
    main()
