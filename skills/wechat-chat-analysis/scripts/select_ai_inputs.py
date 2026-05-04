import argparse
import json
from pathlib import Path


def collect_day_files(markdown_root: Path, limit_days: int = 7) -> list:
    day_files = sorted(markdown_root.glob("*/*.md"))
    return [str(path) for path in day_files[-limit_days:]]


def build_prompt_inputs(export_dir: Path) -> dict:
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    stats = json.loads((export_dir / "stats.json").read_text(encoding="utf-8")) if (export_dir / "stats.json").exists() else {}
    state = json.loads((export_dir / "state.json").read_text(encoding="utf-8")) if (export_dir / "state.json").exists() else {}
    markdown_root = Path(manifest["markdown_root"])
    target_type = manifest.get("target_type")

    if target_type == "group":
        day_files = collect_day_files(markdown_root, limit_days=7)
    elif target_type == "contact":
        day_files = collect_day_files(markdown_root, limit_days=14)
    else:
        day_files = collect_day_files(markdown_root, limit_days=14)

    return {
        "target_type": target_type,
        "target_type_label": {"group": "群聊", "contact": "联系人", "filehelper": "文件传输助手"}.get(target_type, target_type),
        "target_name": manifest.get("target_name"),
        "export_dir": str(export_dir),
        "analysis_input": str(export_dir / "analysis_input.md"),
        "stats": str(export_dir / "stats.json"),
        "state": str(export_dir / "state.json"),
        "day_files": day_files,
        "day_files_label": "建议用于生成 AI 摘要的近期聊天 Markdown 文件",
        "last_export_time": state.get("last_export_time"),
        "message_count": manifest.get("message_count"),
        "first_date": stats.get("first_date"),
        "last_date": stats.get("last_date"),
    }


def main():
    parser = argparse.ArgumentParser(description="Choose prompt inputs for runtime AI summarization")
    parser.add_argument("--export-dir", required=True)
    args = parser.parse_args()

    export_dir = Path(args.export_dir).expanduser()
    print(json.dumps(build_prompt_inputs(export_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
