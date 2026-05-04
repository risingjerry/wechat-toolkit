import argparse
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from discover_databases import discover_accounts
from extract_key import default_wechat_app
from wechat_apps import discover_wechat_apps


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def frida_status() -> dict:
    if not module_available("frida"):
        return {"ok": False, "message": "Python module frida is missing"}
    try:
        import frida

        device = frida.get_local_device()
        return {"ok": True, "message": f"local device: {device.name}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def pip_install_hint() -> str:
    return f"{sys.executable} -m pip install -r {PROJECT_ROOT / 'requirements.txt'}"


def run_checks() -> dict:
    wechat_app = Path(default_wechat_app())
    wechat_bin = wechat_app / "Contents/MacOS/WeChat"
    accounts = discover_accounts()
    apps = discover_wechat_apps()
    checks = {
        "platform": {
            "ok": platform.system() == "Darwin",
            "message": platform.platform(),
        },
        "python": {
            "ok": sys.version_info >= (3, 9),
            "message": sys.version.split()[0],
        },
        "packages": {
            "ok": module_available("frida") and module_available("Crypto") and module_available("zstandard"),
            "items": {
                "frida": module_available("frida"),
                "Crypto": module_available("Crypto"),
                "zstandard": module_available("zstandard"),
            },
            "install_hint": pip_install_hint(),
        },
        "frida": frida_status(),
        "wechat_app": {
            "ok": wechat_bin.exists(),
            "path": str(wechat_app),
            "message": str(wechat_bin),
            "apps": apps,
        },
        "wechat_data": {
            "ok": bool(accounts),
            "account_count": len(accounts),
            "accounts": [
                {
                    "account_key": account.get("account_key"),
                    "account_id": account.get("account_id"),
                    "has_message_db": bool(account.get("message_db")),
                    "has_contact_db": bool(account.get("contact_db")),
                }
                for account in accounts
            ],
        },
        "xcode_cli_tools": {
            "ok": command_available("xcrun"),
            "message": "xcrun found" if command_available("xcrun") else "xcrun not found",
        },
    }
    required = ["platform", "python", "packages", "frida", "wechat_app", "wechat_data"]
    return {
        "project_root": str(PROJECT_ROOT),
        "ok": all(checks[name]["ok"] for name in required),
        "checks": checks,
    }


def print_human(report: dict) -> None:
    print("WeChat Chat Analysis Doctor")
    print(f"Project: {report['project_root']}")
    print(f"Overall: {'OK' if report['ok'] else 'BLOCKED'}")
    print("")
    for name, check in report["checks"].items():
        status = "OK" if check.get("ok") else "MISSING"
        detail = check.get("message") or check.get("path") or ""
        print(f"- {name}: {status} {detail}")
        if name == "packages" and not check.get("ok"):
            print(f"  Install: {check['install_hint']}")
        if name == "wechat_data":
            print(f"  Accounts: {check.get('account_count', 0)}")


def main():
    parser = argparse.ArgumentParser(description="Check whether local WeChat export prerequisites are ready")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--install-deps", action="store_true", help="Install Python dependencies from requirements.txt")
    args = parser.parse_args()

    if args.install_deps:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(PROJECT_ROOT / "requirements.txt")])

    report = run_checks()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_human(report)

    if not report["ok"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
