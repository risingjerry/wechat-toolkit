#!/usr/bin/env python3
"""Installer and updater support for the WeChat Toolkit Codex plugin."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_MARKETPLACE_NAME = "wechat-local-toolkit"
DEFAULT_PLUGIN_NAME = "wechat-toolkit"
DEFAULT_REPO_URL = "https://github.com/risingjerry/wechat-toolkit.git"
DEFAULT_BRANCH = "main"
INSTALL_STATE = ".wechat-toolkit-install.json"
LAUNCH_AGENT_LABEL = "com.dontbesilent.wechat-toolkit-updater"
AUTO_UPDATE_HOUR = 4
AUTO_UPDATE_MINUTE = 0


def run(args: list[str], cwd: Path | None = None, quiet: bool = False) -> str:
    if not quiet:
        print("+ " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=str(cwd) if cwd else None, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def plugin_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def marketplace_root_from_plugin() -> Path:
    return plugin_dir().parents[1]


def state_path(marketplace_root: Path) -> Path:
    return marketplace_root / INSTALL_STATE


def load_state(marketplace_root: Path | None = None) -> dict:
    root = marketplace_root or marketplace_root_from_plugin()
    path = state_path(root)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "marketplace_name": DEFAULT_MARKETPLACE_NAME,
        "plugin_name": DEFAULT_PLUGIN_NAME,
        "repo_url": DEFAULT_REPO_URL,
        "branch": DEFAULT_BRANCH,
        "plugin_subdir": ".",
        "marketplace_root": str(root),
    }


def save_state(marketplace_root: Path, state: dict) -> None:
    marketplace_root.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    state_path(marketplace_root).write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def json_escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def replace_section(text: str, header: str, body: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        if lines[i].strip() == header:
            replaced = True
            out.append(header)
            out.extend(body.splitlines())
            i += 1
            while i < len(lines) and not lines[i].startswith("["):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(header)
        out.extend(body.splitlines())
    return "\n".join(out).rstrip() + "\n"


def update_codex_config(marketplace_root: Path, marketplace_name: str, plugin_name: str) -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    config = codex_home / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    original = config.read_text(encoding="utf-8") if config.exists() else ""

    marketplace_header = f"[marketplaces.{marketplace_name}]"
    marketplace_body = "\n".join(
        [
            f"last_updated = {json_escape(now_iso())}",
            'source_type = "local"',
            f"source = {json_escape(str(marketplace_root))}",
        ]
    )
    plugin_header = f'[plugins."{plugin_name}@{marketplace_name}"]'
    plugin_body = "enabled = true"

    updated = replace_section(original, marketplace_header, marketplace_body)
    updated = replace_section(updated, plugin_header, plugin_body)
    config.write_text(updated, encoding="utf-8")


def write_marketplace_json(marketplace_root: Path, marketplace_name: str, plugin_name: str) -> None:
    path = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": marketplace_name,
        "interface": {"displayName": "微信本地工具"},
        "plugins": [
            {
                "name": plugin_name,
                "source": {"source": "local", "path": f"./plugins/{plugin_name}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_plugin(source_dir: Path, marketplace_root: Path, plugin_name: str, plugin_subdir: str, quiet: bool = False) -> None:
    source_plugin = source_dir if plugin_subdir == "." else source_dir / plugin_subdir
    manifest = source_plugin / ".codex-plugin" / "plugin.json"
    if not manifest.exists():
        raise SystemExit(f"Plugin manifest not found: {manifest}")

    target = marketplace_root / "plugins" / plugin_name
    target.mkdir(parents=True, exist_ok=True)
    run(
        [
            "rsync",
            "-a",
            "--delete",
            "--exclude",
            ".git",
            "--exclude",
            "__pycache__",
            "--exclude",
            ".DS_Store",
            f"{source_plugin}/",
            f"{target}/",
        ],
        quiet=quiet,
    )


def configure(args: argparse.Namespace) -> None:
    marketplace_root = args.marketplace_root.expanduser().resolve()
    state = {
        "marketplace_name": args.marketplace_name,
        "plugin_name": args.plugin_name,
        "repo_url": args.repo_url,
        "branch": args.branch,
        "plugin_subdir": args.plugin_subdir,
        "marketplace_root": str(marketplace_root),
        "source_dir": str(marketplace_root / ".source"),
    }
    write_marketplace_json(marketplace_root, args.marketplace_name, args.plugin_name)
    update_codex_config(marketplace_root, args.marketplace_name, args.plugin_name)
    save_state(marketplace_root, state)
    write_update_command(marketplace_root)
    if args.auto_update != "0":
        install_launch_agent(marketplace_root, quiet=args.quiet)
    elif args.quiet is False:
        print("Auto-update disabled by WECHAT_TOOLKIT_AUTO_UPDATE=0")


def write_update_command(marketplace_root: Path) -> None:
    bin_dir = Path(os.environ.get("WECHAT_TOOLKIT_BIN_DIR", str(Path.home() / ".local" / "bin"))).expanduser()
    bin_dir.mkdir(parents=True, exist_ok=True)
    command = bin_dir / "wechat-toolkit-update"
    updater = marketplace_root / "plugins" / DEFAULT_PLUGIN_NAME / "scripts" / "self_update.py"
    command.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"python3 {json_escape(str(updater))} update \"$@\"\n",
        encoding="utf-8",
    )
    command.chmod(0o755)


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"


def install_launch_agent(marketplace_root: Path, quiet: bool = False) -> None:
    plist_path = launch_agent_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    updater = marketplace_root / "plugins" / DEFAULT_PLUGIN_NAME / "scripts" / "self_update.py"
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [sys.executable, str(updater), "update", "--quiet"],
        "StartCalendarInterval": {"Hour": AUTO_UPDATE_HOUR, "Minute": AUTO_UPDATE_MINUTE},
        "RunAtLoad": False,
        "StandardOutPath": str(marketplace_root / "update.log"),
        "StandardErrorPath": str(marketplace_root / "update.log"),
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle)
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=False, capture_output=True)
    if not quiet:
        print(f"Installed daily auto-updater: {plist_path}")


def uninstall_launch_agent(_args: argparse.Namespace) -> None:
    plist_path = launch_agent_path()
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False, capture_output=True)
    if plist_path.exists():
        plist_path.unlink()
    print(f"Removed auto-updater: {plist_path}")


def update(args: argparse.Namespace) -> None:
    marketplace_root = marketplace_root_from_plugin()
    state = load_state(marketplace_root)
    source_dir = Path(state.get("source_dir") or marketplace_root / ".source").expanduser()
    repo_url = state.get("repo_url", DEFAULT_REPO_URL)
    branch = state.get("branch", DEFAULT_BRANCH)
    plugin_subdir = state.get("plugin_subdir", ".")
    plugin_name = state.get("plugin_name", DEFAULT_PLUGIN_NAME)
    marketplace_name = state.get("marketplace_name", DEFAULT_MARKETPLACE_NAME)

    if not source_dir.exists():
        run(["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(source_dir)], quiet=args.quiet)
    else:
        run(["git", "-C", str(source_dir), "remote", "set-url", "origin", repo_url], quiet=args.quiet)
        run(["git", "-C", str(source_dir), "fetch", "--prune", "origin", branch], quiet=args.quiet)
        local = run(["git", "-C", str(source_dir), "rev-parse", "HEAD"], quiet=True)
        remote = run(["git", "-C", str(source_dir), "rev-parse", f"origin/{branch}"], quiet=True)
        if local == remote and not args.force:
            if not args.quiet:
                print("wechat-toolkit is already up to date.")
            return
        run(["git", "-C", str(source_dir), "checkout", branch], quiet=args.quiet)
        run(["git", "-C", str(source_dir), "reset", "--hard", f"origin/{branch}"], quiet=args.quiet)

    sync_plugin(source_dir, marketplace_root, plugin_name, plugin_subdir, quiet=args.quiet)
    write_marketplace_json(marketplace_root, marketplace_name, plugin_name)
    update_codex_config(marketplace_root, marketplace_name, plugin_name)
    state["last_update_status"] = "ok"
    save_state(marketplace_root, state)
    if not args.quiet:
        print("wechat-toolkit updated. Restart Codex to load plugin changes.")


def status(_args: argparse.Namespace) -> None:
    marketplace_root = marketplace_root_from_plugin()
    state = load_state(marketplace_root)
    source_dir = Path(state.get("source_dir") or marketplace_root / ".source")
    current = ""
    remote = ""
    if source_dir.exists():
        current = run(["git", "-C", str(source_dir), "rev-parse", "--short", "HEAD"], quiet=True)
        try:
            remote = run(["git", "-C", str(source_dir), "rev-parse", "--short", f"origin/{state.get('branch', DEFAULT_BRANCH)}"], quiet=True)
        except subprocess.CalledProcessError:
            remote = ""
    print(
        json.dumps(
            {
                "marketplace_root": str(marketplace_root),
                "plugin_dir": str(plugin_dir()),
                "source_dir": str(source_dir),
                "repo_url": state.get("repo_url"),
                "branch": state.get("branch"),
                "current": current,
                "remote": remote,
                "launch_agent": str(launch_agent_path()),
                "auto_update_installed": launch_agent_path().exists(),
                "auto_update_schedule": f"daily {AUTO_UPDATE_HOUR:02d}:{AUTO_UPDATE_MINUTE:02d} local time",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and update the WeChat Toolkit Codex plugin")
    sub = parser.add_subparsers(dest="command", required=True)

    configure_parser = sub.add_parser("configure")
    configure_parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    configure_parser.add_argument("--branch", default=DEFAULT_BRANCH)
    configure_parser.add_argument("--plugin-subdir", default=".")
    configure_parser.add_argument("--marketplace-name", default=DEFAULT_MARKETPLACE_NAME)
    configure_parser.add_argument("--marketplace-root", type=Path, required=True)
    configure_parser.add_argument("--plugin-name", default=DEFAULT_PLUGIN_NAME)
    configure_parser.add_argument("--auto-update", default="1")
    configure_parser.add_argument("--quiet", action="store_true")
    configure_parser.set_defaults(func=configure)

    update_parser = sub.add_parser("update")
    update_parser.add_argument("--quiet", action="store_true")
    update_parser.add_argument("--force", action="store_true")
    update_parser.set_defaults(func=update)

    launch_parser = sub.add_parser("install-launchagent")
    launch_parser.add_argument("--quiet", action="store_true")
    launch_parser.set_defaults(func=lambda args: install_launch_agent(marketplace_root_from_plugin(), quiet=args.quiet))

    uninstall_parser = sub.add_parser("uninstall-launchagent")
    uninstall_parser.set_defaults(func=uninstall_launch_agent)

    status_parser = sub.add_parser("status")
    status_parser.set_defaults(func=status)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
