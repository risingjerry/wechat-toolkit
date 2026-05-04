import argparse
import json
from datetime import datetime
from pathlib import Path


def write_group_ai(export_dir: Path, manifest: dict, stats: dict) -> None:
    ai_dir = export_dir / "ai"
    daily_dir = ai_dir / "daily_digest"
    daily_dir.mkdir(parents=True, exist_ok=True)

    (ai_dir / "weekly_topics.md").write_text(
        "# 每周主题\n\n待 AI 根据 `analysis_input.md`、`stats.json` 和近期聊天 Markdown 生成。\n",
        encoding="utf-8",
    )
    (ai_dir / "action_items.md").write_text(
        "# 待办事项\n\n待 AI 从群聊中提取待办、机会、请求、决策和截止时间。\n",
        encoding="utf-8",
    )
    (ai_dir / "high_signal_digest.md").write_text(
        "# 高信号摘要\n\n待 AI 过滤闲聊、表情和重复内容后生成高信息密度摘要。\n",
        encoding="utf-8",
    )

    day = stats.get("last_date") or datetime.now().strftime("%Y-%m-%d")
    (daily_dir / f"{day}.md").write_text(
        f"# {manifest.get('target_name')} 群日报\n\n日期：{day}\n\n待 AI 仅基于该日聊天生成日报。\n",
        encoding="utf-8",
    )


def write_contact_ai(export_dir: Path) -> None:
    ai_dir = export_dir / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    templates = {
        "relationship_brief.md": "# 关系简报\n\n待 AI 总结对方关注点、长期主题、合作背景和未完成话题。\n",
        "recent_changes.md": "# 最近变化\n\n待 AI 提炼本次导出中的新增重点、态度变化和上下文变化。\n",
        "followups.md": "# 跟进事项\n\n待 AI 生成待回复、待跟进事项、建议动作和优先级。\n",
        "high_value_notes.md": "# 高价值笔记\n\n待 AI 提炼长期有价值的信息、链接、承诺、决策和可复用经验。\n",
    }
    for name, content in templates.items():
        (ai_dir / name).write_text(content, encoding="utf-8")


def write_filehelper_ai(export_dir: Path) -> None:
    ai_dir = export_dir / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    (ai_dir / "inbox_digest.md").write_text(
        "# 文件传输助手摘要\n\n待 AI 提炼链接、灵感、任务、素材和待整理内容。\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="Create AI artifact scaffolding for exported WeChat chats")
    parser.add_argument("--export-dir", action="append", required=True)
    args = parser.parse_args()

    results = []
    for export_dir_value in args.export_dir:
        export_dir = Path(export_dir_value).expanduser()
        manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        stats = json.loads((export_dir / "stats.json").read_text(encoding="utf-8")) if (export_dir / "stats.json").exists() else {}
        target_type = manifest.get("target_type")
        if target_type == "group":
            write_group_ai(export_dir, manifest, stats)
        elif target_type == "contact":
            write_contact_ai(export_dir)
        else:
            write_filehelper_ai(export_dir)
        results.append({"export_dir": str(export_dir), "target_type": target_type})

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
