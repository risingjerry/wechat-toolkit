#!/usr/bin/env python3
"""Product-facing wrapper for the local WeChat toolkit plugin.

The CLI keeps user-facing features coarse:
- chat: export/analyze WeChat conversations
- multiopen: inspect or launch multi-open WeChat apps
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
CHAT_PROJECT_DIR_NAME = "wechat-chat-analysis"
DEFAULT_CHAT_PROJECT = Path.cwd() / CHAT_PROJECT_DIR_NAME
EMBEDDED_CHAT_SKILL = PLUGIN_ROOT / "skills" / "wechat-chat-analysis"
MULTIFIX_ICON_ROOT = PLUGIN_ROOT / "assets" / "wechat-multifix-icons" / "icons"
PLIST_BUDDY = Path("/usr/libexec/PlistBuddy")
LSREGISTER = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
THEME_ICONS = {
    "black": "AppIcon-black.icns",
    "黑": "AppIcon-black.icns",
    "黑底": "AppIcon-black.icns",
    "cyan": "AppIcon-cyan.icns",
    "青": "AppIcon-cyan.icns",
    "青底": "AppIcon-cyan.icns",
    "purple": "AppIcon-purple.icns",
    "紫": "AppIcon-purple.icns",
    "紫底": "AppIcon-purple.icns",
    "orange": "AppIcon-orange.icns",
    "橙": "AppIcon-orange.icns",
    "橙底": "AppIcon-orange.icns",
    "navy": "AppIcon-navy.icns",
    "深蓝": "AppIcon-navy.icns",
    "深蓝底": "AppIcon-navy.icns",
    "darkgray": "AppIcon-darkgray.icns",
    "深灰": "AppIcon-darkgray.icns",
    "深灰底": "AppIcon-darkgray.icns",
}


def run_command(args: List[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(str(arg) for arg in args), flush=True)
    env = os.environ.copy()
    if args and str(args[0]) == "uv":
        env.setdefault("UV_CACHE_DIR", "/private/tmp/wechat-toolkit-uv-cache")
    subprocess.check_call([str(arg) for arg in args], cwd=str(cwd) if cwd else None, env=env)


def python_runner(packages: List[str] | None = None) -> List[str]:
    packages = packages or []
    if shutil.which("uv"):
        command = ["uv", "run"]
        for package in packages:
            command.extend(["--with", package])
        command.append("python")
        return command
    return [sys.executable]


def resolve_chat_project(project: Path) -> Path:
    project = project.expanduser().resolve()
    if project.name == CHAT_PROJECT_DIR_NAME:
        return project
    return project / CHAT_PROJECT_DIR_NAME


def project_scripts(project: Path) -> Path:
    scripts = resolve_chat_project(project) / "scripts"
    if not scripts.exists():
        raise SystemExit(
            f"wechat-chat-analysis project not initialized: {resolve_chat_project(project)}. "
            "Run: wechat_toolkit.py chat init"
        )
    return scripts


def first_connect_app(args: argparse.Namespace) -> Path:
    if args.wechat_app:
        return Path(args.wechat_app).expanduser().resolve()
    prefix = "com.tencent.xinWeChat"
    bundle_id = args.bundle_id or prefix
    if bundle_id == prefix:
        return Path("/Applications/WeChat.app")
    if bundle_id.startswith(prefix):
        suffix = bundle_id[len(prefix):]
        if suffix.isdigit():
            return Path(f"/Applications/WeChat{suffix}.app")
    return Path("/Applications/WeChat.app")


def app_processes(app: Path) -> List[dict]:
    app = app.expanduser().resolve()
    app_prefix = str(app) + "/"
    main_binary = str(app / "Contents" / "MacOS" / "WeChat")
    result = subprocess.run(["ps", "-axo", "pid=,command="], check=False, capture_output=True, text=True)
    processes = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        if not pid_text.isdigit():
            continue
        is_main = command == main_binary or command.startswith(main_binary + " ")
        if is_main or command.startswith(app_prefix):
            processes.append({
                "pid": int(pid_text),
                "command": command,
                "is_main": is_main,
            })
    return processes


def stop_app_if_running(app: Path, timeout: int = 25) -> dict:
    processes = app_processes(app)
    if not processes:
        return {"app": str(app), "was_running": False, "terminated_pids": []}

    pids = [item["pid"] for item in processes]
    main_pids = [item["pid"] for item in processes if item["is_main"]] or pids
    print(json.dumps({
        "status": "restarting-target-wechat",
        "app": str(app),
        "reason": "target app is already running; first-connect needs a fresh login/startup key capture",
        "main_pids": main_pids,
        "process_count": len(processes),
    }, ensure_ascii=False), flush=True)

    for pid in main_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not app_processes(app):
            return {"app": str(app), "was_running": True, "terminated_pids": pids}
        time.sleep(1)

    remaining = app_processes(app)
    remaining_pids = [item["pid"] for item in remaining]
    raise SystemExit(
        "Timed out waiting for target WeChat app to quit before first-connect. "
        f"Please quit {app} manually and retry. Remaining PIDs: {remaining_pids}"
    )


def chat_init(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    init_script = EMBEDDED_CHAT_SKILL / "scripts" / "init_project.py"
    if not init_script.exists():
        raise SystemExit(f"embedded wechat-chat-analysis init script not found: {init_script}")
    command = [sys.executable, init_script, "--workspace", project]
    if args.force:
        command.append("--force")
    if args.install_deps:
        command.append("--install-deps")
    run_command(command)


def chat_status(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    scripts = project / "scripts"
    manifest = project / "decrypted" / "sync_manifest.json"
    key_store = project / "decrypted" / "key_store.json"
    initialized = scripts.exists()
    payload = {
        "feature": "chat-export-analysis",
        "project": str(project),
        "initialized": initialized,
        "embedded_template_exists": EMBEDDED_CHAT_SKILL.exists(),
        "manifest_exists": manifest.exists(),
        "key_store_exists": key_store.exists(),
        "next_actions": [
            "init" if not initialized else ("first-connect" if not key_store.exists() else "update-backup"),
            "export",
            "ai",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.run_doctor:
        scripts = project_scripts(project)
        run_command(python_runner(["frida-tools", "pycryptodome", "zstandard"]) + [scripts / "doctor.py"], cwd=project)


def chat_first_connect(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    scripts = project_scripts(project)
    stop_app_if_running(first_connect_app(args))
    command = python_runner(["frida-tools", "pycryptodome", "zstandard"]) + [
        scripts / "extract_key.py",
        "--mode",
        "spawn",
        "--out",
        project / "decrypted" / "wechat_keys.log",
        "--reset",
    ]
    if args.wechat_app:
        command.extend(["--wechat-app", args.wechat_app])
    if args.bundle_id:
        command.extend(["--bundle-id", args.bundle_id])
    run_command(command, cwd=project)
    chat_update_backup(args)


def chat_update_backup(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    scripts = project_scripts(project)
    command = python_runner(["pycryptodome"]) + [scripts / "sync_databases.py"]
    if args.container_name:
        command.extend(["--container-name", args.container_name])
    if args.account_id:
        command.extend(["--account-id", args.account_id])
    run_command(command, cwd=project)


def chat_export(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    scripts = project_scripts(project)
    command = python_runner(["zstandard"]) + [
        scripts / "export_targets.py",
        "--sync-manifest",
        project / "decrypted" / "sync_manifest.json",
        "--output-dir",
        project / "output",
        "--name",
        args.target_name,
    ]
    if args.account_id:
        command.extend(["--account-id", args.account_id])
    else:
        command.append("--first-ok")
    if args.target_type == "group":
        command.append("--groups")
    elif args.target_type == "filehelper":
        command.append("--filehelper")
    else:
        command.append("--contacts")
    if args.incremental:
        command.append("--incremental")
    if args.no_attachments:
        command.append("--no-attachments")
    run_command(command, cwd=project)


def chat_ai(args: argparse.Namespace) -> None:
    project = resolve_chat_project(args.project)
    scripts = project_scripts(project)
    export_dir = Path(args.export_dir).expanduser()
    if not export_dir.is_absolute():
        export_dir = project / "output" / export_dir
    run_command(python_runner() + [scripts / "run_ai_analysis.py", "--export-dir", export_dir], cwd=project)


def wechat_app_path(number: int) -> Path:
    return Path("/Applications/WeChat.app") if number == 1 else Path(f"/Applications/WeChat{number}.app")


def expected_bundle_id(number: int) -> str:
    return "com.tencent.xinWeChat" if number == 1 else f"com.tencent.xinWeChat{number}"


def expected_app_name(number: int) -> str:
    return "WeChat" if number == 1 else f"WeChat{number}"


def plist_value(app: Path, key: str) -> str:
    plist = app / "Contents" / "Info.plist"
    if not plist.exists():
        return ""
    result = subprocess.run(
        [str(PLIST_BUDDY), "-c", f"Print :{key}", str(plist)],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect_wechat_app(number: int) -> dict:
    app = wechat_app_path(number)
    binary = app / "Contents" / "MacOS" / "WeChat"
    bundle_id = plist_value(app, "CFBundleIdentifier")
    bundle_name = plist_value(app, "CFBundleName")
    expected_id = expected_bundle_id(number)
    return {
        "number": number,
        "name": expected_app_name(number),
        "app": str(app),
        "exists": app.exists(),
        "binary": str(binary),
        "binary_exists": binary.exists(),
        "bundle_id": bundle_id,
        "expected_bundle_id": expected_id,
        "bundle_name": bundle_name,
        "needs_repair": number > 1 and (not app.exists() or bundle_id != expected_id),
    }


def resolve_icon(theme: str) -> Path:
    icon_name = THEME_ICONS.get(theme.strip().lower()) or THEME_ICONS.get(theme.strip()) or THEME_ICONS["black"]
    icon = MULTIFIX_ICON_ROOT / icon_name
    if not icon.exists():
        raise SystemExit(f"wechat-multifix icon not found: {icon}")
    return icon


def run_multifix_step(command: List[object], dry_run: bool) -> None:
    if dry_run:
        print("+ " + " ".join(str(item) for item in command), flush=True)
        return
    run_command([str(item) for item in command])


def multiopen_status(args: argparse.Namespace) -> None:
    apps = [inspect_wechat_app(number) for number in range(1, args.max_number + 1)]
    print(json.dumps({
        "feature": "wechat-multiopen",
        "apps": apps,
        "ready": any(item["binary_exists"] for item in apps),
        "repair_needed": [item for item in apps if item["needs_repair"]],
        "multifix_source": "bundled wechat-multifix skill",
        "themes": sorted({value.replace("AppIcon-", "").replace(".icns", "") for value in THEME_ICONS.values()}),
    }, ensure_ascii=False, indent=2))


def multiopen_install_or_repair(args: argparse.Namespace) -> None:
    number = args.number
    if number < 2:
        raise SystemExit("multiopen install/repair starts from WeChat2. Use --number 2 or higher.")
    source = Path("/Applications/WeChat.app")
    target = wechat_app_path(number)
    before = inspect_wechat_app(number)
    icon = resolve_icon(args.theme)
    dry_run = args.dry_run

    if not source.exists():
        raise SystemExit(f"source WeChat app not found: {source}")
    if target.exists() and not before["needs_repair"] and not args.force:
        print(json.dumps({
            "status": "ok",
            "message": f"{expected_app_name(number)} 状态正常，无需修复。使用 --force 可强制重建。",
            "app": before,
        }, ensure_ascii=False, indent=2))
        return

    run_multifix_step(["rm", "-rf", target], dry_run)
    run_multifix_step(["cp", "-R", source, target], dry_run)
    info_plist = target / "Contents" / "Info.plist"
    run_multifix_step([PLIST_BUDDY, "-c", f"Set :CFBundleIdentifier {expected_bundle_id(number)}", info_plist], dry_run)
    run_multifix_step([PLIST_BUDDY, "-c", f"Set :CFBundleName {expected_app_name(number)}", info_plist], dry_run)
    run_multifix_step(["xattr", "-cr", target], dry_run)
    run_multifix_step(["codesign", "--force", "--deep", "--sign", "-", target], dry_run)
    run_multifix_step(["chown", "-R", f"{getpass.getuser()}:admin", target], dry_run)
    run_multifix_step(["cp", icon, target / "Contents" / "Resources" / "AppIcon.icns"], dry_run)
    run_multifix_step(["codesign", "--force", "--deep", "--sign", "-", target], dry_run)
    if LSREGISTER.exists():
        run_multifix_step([LSREGISTER, "-f", target], dry_run)

    after = inspect_wechat_app(number) if not dry_run else {"dry_run": True}
    if args.launch and not dry_run:
        run_command(["open", "-n", target])
    print(json.dumps({
        "status": "dry_run" if dry_run else "installed_or_repaired",
        "feature": "wechat-multiopen",
        "source_skill": "wechat-multifix",
        "number": number,
        "theme": args.theme,
        "icon": str(icon),
        "before": before,
        "after": after,
        "reminder": [
            "微信更新后如果 WeChat2 打不开，直接说「修复微信多开」。",
            "通知权限需要用户手动在 WeChat2 和 macOS 系统设置里打开。",
        ],
    }, ensure_ascii=False, indent=2))


def multiopen_launch(args: argparse.Namespace) -> None:
    targets = [Path(value).expanduser() for value in args.app]
    if args.all_known or not targets:
        targets = [wechat_app_path(1), wechat_app_path(2)]
    launched = []
    for app in targets:
        if not app.exists():
            print(json.dumps({"status": "missing", "app": str(app)}, ensure_ascii=False))
            continue
        run_command(["open", "-n", app])
        launched.append(str(app))
    print(json.dumps({"status": "launched", "apps": launched}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WeChat Toolkit plugin CLI")
    parser.add_argument("--project", type=Path, default=DEFAULT_CHAT_PROJECT, help="wechat-chat-analysis project path or parent workspace")

    subparsers = parser.add_subparsers(dest="feature", required=True)

    chat = subparsers.add_parser("chat", help="WeChat chat export and analysis")
    chat_sub = chat.add_subparsers(dest="action", required=True)

    init = chat_sub.add_parser("init")
    init.add_argument("--force", action="store_true")
    init.add_argument("--install-deps", action="store_true")
    init.set_defaults(func=chat_init)

    status = chat_sub.add_parser("status")
    status.add_argument("--run-doctor", action="store_true")
    status.set_defaults(func=chat_status)

    first_connect = chat_sub.add_parser("first-connect")
    first_connect.add_argument("--wechat-app")
    first_connect.add_argument("--bundle-id")
    first_connect.add_argument("--container-name")
    first_connect.add_argument("--account-id")
    first_connect.set_defaults(func=chat_first_connect)

    update = chat_sub.add_parser("update-backup")
    update.add_argument("--container-name")
    update.add_argument("--account-id")
    update.set_defaults(func=chat_update_backup)

    export = chat_sub.add_parser("export")
    export.add_argument("--target-name", required=True)
    export.add_argument("--target-type", choices=["contact", "group", "filehelper"], default="contact")
    export.add_argument("--account-id")
    export.add_argument("--incremental", action="store_true")
    export.add_argument("--no-attachments", action="store_true")
    export.set_defaults(func=chat_export)

    ai = chat_sub.add_parser("ai")
    ai.add_argument("--export-dir", required=True)
    ai.set_defaults(func=chat_ai)

    multiopen = subparsers.add_parser("multiopen", help="WeChat one-click multi-open")
    multi_sub = multiopen.add_subparsers(dest="action", required=True)

    mo_status = multi_sub.add_parser("status")
    mo_status.add_argument("--max-number", type=int, default=2)
    mo_status.set_defaults(func=multiopen_status)

    install = multi_sub.add_parser("install")
    install.add_argument("--number", type=int, default=2)
    install.add_argument("--theme", default="black")
    install.add_argument("--force", action="store_true")
    install.add_argument("--launch", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    install.set_defaults(func=multiopen_install_or_repair)

    repair = multi_sub.add_parser("repair")
    repair.add_argument("--number", type=int, default=2)
    repair.add_argument("--theme", default="black")
    repair.add_argument("--force", action="store_true")
    repair.add_argument("--launch", action="store_true")
    repair.add_argument("--dry-run", action="store_true")
    repair.set_defaults(func=multiopen_install_or_repair)

    launch = multi_sub.add_parser("launch")
    launch.add_argument("--app", action="append", default=[])
    launch.add_argument("--all-known", action="store_true")
    launch.set_defaults(func=multiopen_launch)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
