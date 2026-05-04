import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
PROJECT_DIR_NAME = "wechat-chat-analysis"


def resolve_project_root(workspace: Path) -> Path:
    workspace = workspace.expanduser().resolve()
    if workspace.name == PROJECT_DIR_NAME:
        return workspace
    return workspace / PROJECT_DIR_NAME


def copy_file(source: Path, target: Path, force: bool = False) -> None:
    if target.exists() and not force:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def init_project(workspace: Path, force: bool = False) -> Path:
    project_root = resolve_project_root(workspace)
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (project_root / "decrypted").mkdir(parents=True, exist_ok=True)
    (project_root / "output").mkdir(parents=True, exist_ok=True)

    for pattern in ("*.py", "*.sh"):
        for source in sorted((SKILL_ROOT / "scripts").glob(pattern)):
            copy_file(source, scripts_dir / source.name, force=force)

    copy_file(SKILL_ROOT / "requirements.txt", project_root / "requirements.txt", force=force)

    gitignore = project_root / ".gitignore"
    if force or not gitignore.exists():
        gitignore.write_text(
            "\n".join(
                [
                    "decrypted/",
                    "output/",
                    "key_store.json",
                    "*.log",
                    "__pycache__/",
                    ".DS_Store",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return project_root


def main():
    parser = argparse.ArgumentParser(description="Create a local project workspace for WeChat chat export")
    parser.add_argument("--workspace", default=os.getcwd(), help="Parent folder or final wechat-chat-analysis folder")
    parser.add_argument("--force", action="store_true", help="Overwrite scripts in the project workspace")
    parser.add_argument("--install-deps", action="store_true", help="Install Python dependencies after initialization")
    parser.add_argument("--run", action="store_true", help="Start the guided export wizard after initialization")
    args = parser.parse_args()

    project_root = init_project(Path(args.workspace), force=args.force)
    print(f"Initialized: {project_root}")
    print(f"Python: {sys.executable}")

    if args.install_deps:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(project_root / "requirements.txt")])

    if args.run:
        wizard = project_root / "scripts" / "guided_export.py"
        os.execv(sys.executable, [sys.executable, str(wizard)])


if __name__ == "__main__":
    main()
