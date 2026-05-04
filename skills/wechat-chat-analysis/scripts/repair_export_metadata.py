import json
from pathlib import Path
from typing import Dict


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_ROOT = PROJECT_ROOT / "output"


def normalize_attachment_index(index: Dict[str, dict], export_dir: Path) -> Dict[str, dict]:
    normalized = {}
    marker = "/output/"
    expected_prefix = str(export_dir / "markdown")

    for month, info in (index or {}).items():
        dir_value = info.get("dir")
        file_values = info.get("files", [])

        def repair_path(value: str) -> str:
            if not value:
                return value
            path = Path(value)
            if path.is_absolute():
                text = str(path)
                first = text.find(marker)
                second = text.find(marker, first + len(marker)) if first != -1 else -1
                if second != -1:
                    text = text[:first] + text[second:]
                return text
            text = value
            first = text.find("output/")
            second = text.find("output/", first + len("output/")) if first != -1 else -1
            if second != -1:
                text = text[second:]
            return str((PROJECT_ROOT / text).resolve())

        repaired_dir = repair_path(dir_value) if dir_value else None
        repaired_files = [repair_path(value) for value in file_values]

        if repaired_dir and "/output/" in repaired_dir and expected_prefix in repaired_dir and repaired_dir.count("/output/") > 1:
            repaired_dir = repaired_dir.replace(f"{export_dir}/output", str(PROJECT_ROOT / "output"), 1)

        normalized[month] = {
            "dir": repaired_dir,
            "files": repaired_files,
        }

    return normalized


def repair_export(export_dir: Path) -> bool:
    changed = False
    for filename in ("state.json", "manifest.json"):
        file_path = export_dir / filename
        if not file_path.exists():
            continue
        data = json.loads(file_path.read_text(encoding="utf-8"))
        old = json.dumps(data.get("attachment_months", {}), ensure_ascii=False, sort_keys=True)
        data["attachment_months"] = normalize_attachment_index(data.get("attachment_months", {}), export_dir)
        new = json.dumps(data.get("attachment_months", {}), ensure_ascii=False, sort_keys=True)
        if old != new:
            file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            changed = True
    return changed


def main():
    if not OUTPUT_ROOT.exists():
        print("[]")
        return

    repaired = []
    for export_dir in sorted(path for path in OUTPUT_ROOT.iterdir() if path.is_dir()):
        if repair_export(export_dir):
            repaired.append(str(export_dir))
    print(json.dumps(repaired, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
