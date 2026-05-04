import argparse
import json
import subprocess
from pathlib import Path
from typing import List, Optional


SEARCH_ROOTS = [
    Path("/Applications"),
    Path.home() / "Applications",
    Path.home() / "Desktop",
]


def plist_value(app_path: Path, key: str) -> str:
    info_plist = app_path / "Contents/Info.plist"
    if not info_plist.exists():
        return ""
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", str(info_plist.with_suffix("")), key],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def executable_path(app_path: Path) -> Optional[Path]:
    executable_name = plist_value(app_path, "CFBundleExecutable") or "WeChat"
    candidate = app_path / "Contents/MacOS" / executable_name
    if candidate.exists():
        return candidate
    fallback = app_path / "Contents/MacOS/WeChat"
    if fallback.exists():
        return fallback
    return None


def looks_like_wechat(app_path: Path) -> bool:
    bundle_id = plist_value(app_path, "CFBundleIdentifier")
    executable = executable_path(app_path)
    name = app_path.name.lower()
    return bool(executable) and (
        "wechat" in name
        or "微信" in app_path.name
        or "xinwechat" in bundle_id.lower()
        or "wechat" in bundle_id.lower()
    )


def discover_wechat_apps() -> List[dict]:
    apps = {}
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for app_path in sorted(root.glob("*.app")):
            if not looks_like_wechat(app_path):
                continue
            executable = executable_path(app_path)
            bundle_id = plist_value(app_path, "CFBundleIdentifier")
            display_name = plist_value(app_path, "CFBundleDisplayName") or plist_value(app_path, "CFBundleName") or app_path.stem
            apps[str(app_path)] = {
                "app_path": str(app_path),
                "bundle_id": bundle_id,
                "display_name": display_name,
                "executable": str(executable) if executable else "",
            }
    return sorted(apps.values(), key=lambda item: (item.get("bundle_id") or "", item["app_path"]))


def resolve_wechat_app(bundle_id: Optional[str] = None, app_path: Optional[str] = None) -> str:
    if app_path:
        return str(Path(app_path).expanduser())
    apps = discover_wechat_apps()
    if bundle_id:
        for app in apps:
            if app.get("bundle_id") == bundle_id:
                return app["app_path"]
        raise FileNotFoundError(f"No WeChat app found for bundle id: {bundle_id}")
    for preferred in ("/Applications/WeChat.app", str(Path.home() / "Applications/WeChat.app"), str(Path.home() / "Desktop/WeChat.app")):
        path = Path(preferred)
        if (path / "Contents/MacOS").exists():
            return str(path)
    if apps:
        return apps[0]["app_path"]
    return "/Applications/WeChat.app"


def resolve_wechat_executable(bundle_id: Optional[str] = None, app_path: Optional[str] = None) -> str:
    resolved_app = Path(resolve_wechat_app(bundle_id=bundle_id, app_path=app_path))
    executable = executable_path(resolved_app)
    if executable:
        return str(executable)
    return str(resolved_app / "Contents/MacOS/WeChat")


def main():
    parser = argparse.ArgumentParser(description="Discover local WeChat app bundles")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    apps = discover_wechat_apps()
    if args.json:
        print(json.dumps(apps, ensure_ascii=False, indent=2))
        return

    for index, app in enumerate(apps, start=1):
        print(f"{index}. {app['display_name']} | bundle_id={app['bundle_id'] or '-'}")
        print(f"   app: {app['app_path']}")
        print(f"   bin: {app['executable']}")


if __name__ == "__main__":
    main()
