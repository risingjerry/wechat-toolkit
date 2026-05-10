import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from account_runtime import account_to_runtime, load_sync_manifest, select_account
from export_chat import export_chat
from export_targets import build_bundle
from extract_key import default_wechat_app
from list_targets import list_targets
from shortlist_targets import filter_by_types, rank_targets
from wechat_apps import discover_wechat_apps, resolve_wechat_app


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DECRYPTED_ROOT = PROJECT_ROOT / "decrypted"
OUTPUT_ROOT = PROJECT_ROOT / "output"
SYNC_MANIFEST = DECRYPTED_ROOT / "sync_manifest.json"
KEYS_LOG = DECRYPTED_ROOT / "wechat_keys.log"
KEY_STORE = DECRYPTED_ROOT / "key_store.json"


def prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def yes_no(text: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    value = prompt(f"{text} ({default_text})").lower()
    if not value:
        return default
    return value in {"y", "yes", "是", "好", "1"}


def run_command(args: List[str]) -> None:
    print("")
    print("+ " + " ".join(args))
    subprocess.check_call(args)


def ensure_not_installed_skill_dir() -> None:
    path = str(PROJECT_ROOT)
    installed_markers = [
        f"{Path.home()}/.agents/skills/",
        f"{Path.home()}/.codex/skills/",
        f"{Path.home()}/.claude/skills/",
        f"{Path.home()}/.hermes/skills/",
        f"{Path.home()}/.openclaw/skills/",
    ]
    if any(path.startswith(marker) for marker in installed_markers):
        sys.exit(
            "This wizard must run from a project workspace, not from the installed skill folder.\n"
            "Run: python3 ~/.agents/skills/wechat-chat-analysis/scripts/init_project.py --workspace ~/WeChatChatExport --run"
        )


def print_privacy_notice() -> None:
    print("微信聊天记录本地导出")
    print("")
    print("这个工具只用于导出你本人 macOS 账号下、你有权访问的微信聊天。")
    print("解密后的数据库、聊天 Markdown/JSONL 和可选媒体文件都会只保存在本地目录：")
    print(f"  {PROJECT_ROOT}")
    print("不要在未获授权的情况下上传、分享或处理他人的私人聊天。")
    print("")
    if prompt("输入 YES 继续") != "YES":
        sys.exit("已取消")


def ready_accounts() -> List[dict]:
    if not SYNC_MANIFEST.exists():
        return []
    manifest = load_sync_manifest(SYNC_MANIFEST)
    return [
        account for account in manifest.get("accounts", [])
        if account.get("message", {}).get("status") == "ok"
    ]


def account_container_name(account: dict) -> str:
    if account.get("container_name"):
        return account["container_name"]
    account_key = account.get("account_key") or ""
    return account_key.split(":", 1)[0] if ":" in account_key else ""


def filter_accounts_for_args(accounts: List[dict], args) -> List[dict]:
    if args.container_name:
        return [account for account in accounts if account_container_name(account) == args.container_name]
    if args.bundle_id:
        return [account for account in accounts if account_container_name(account) == args.bundle_id]
    return accounts


def sync_command(args, keys_log: Optional[Path] = None) -> List[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "sync_databases.py"),
    ]
    if keys_log:
        command.extend(["--keys-log", str(keys_log)])
    if args.container_name:
        command.extend(["--container-name", args.container_name])
    elif args.bundle_id:
        command.extend(["--container-name", args.bundle_id])
    return command


def sync_with_stored_keys(args) -> bool:
    if not KEY_STORE.exists():
        return False
    print("")
    print("检测到本地 key_store.json，先尝试免登录同步最新本地数据库。")
    run_command(sync_command(args))
    return True


def capture_and_sync(args) -> None:
    print("")
    print("当前还没有可用的解密账号，或本地 key_store.json 不能解密目标账号。")
    print("接下来会启动微信，你只需要登录并保持微信打开。")
    print("不需要点击联系人、群聊或文件传输助手。")
    print("如果同步仍提示缺少目标账号的 key，再重新捕获并多等待一会儿。")
    print("如果目标微信已经在运行，请先退出它。")
    if not yes_no("现在开始一次性捕获 key", default=True):
        sys.exit("已取消")

    wechat_app = Path(resolve_wechat_app(bundle_id=args.bundle_id, app_path=args.wechat_app)).expanduser()
    run_command([
        sys.executable,
        str(SCRIPT_DIR / "extract_key.py"),
        "--mode",
        "spawn",
        "--wechat-app",
        str(wechat_app),
        "--out",
        str(KEYS_LOG),
        "--wait",
        str(args.key_wait),
        "--min-usable-keys",
        str(args.min_usable_keys),
        "--settle-seconds",
        str(args.key_settle_seconds),
        "--reset",
    ])

    run_command(sync_command(args, keys_log=KEYS_LOG))

    if KEYS_LOG.exists() and yes_no("临时 keylog 已导入 key_store.json，是否删除临时 keylog", default=True):
        KEYS_LOG.unlink()
        print(f"Deleted: {KEYS_LOG}")


def choose_account_interactively(accounts: List[dict]) -> dict:
    if len(accounts) == 1:
        return accounts[0]
    print("")
    print("选择账号：")
    for index, account in enumerate(accounts, start=1):
        print(f"{index}. {account.get('account_key')} container={account_container_name(account)} message={account.get('message', {}).get('status')}")
    while True:
        value = prompt("账号序号", "1")
        if value.isdigit() and 1 <= int(value) <= len(accounts):
            return accounts[int(value) - 1]
        print("账号序号无效")


def choose_target_types() -> List[str]:
    print("")
    print("导出对象类型：")
    print("1. 联系人")
    print("2. 群聊")
    print("3. 文件传输助手")
    print("4. 全部")
    value = prompt("请选择", "1")
    if value == "2":
        return ["group"]
    if value == "3":
        return ["filehelper"]
    if value == "4":
        return ["contact", "group", "filehelper"]
    return ["contact"]


def show_targets(targets: List[dict]) -> None:
    for index, target in enumerate(targets, start=1):
        print(
            f"{index:02d}. [{target['target_type']}] {target['target_name']} | "
            f"messages={target.get('message_count', 0)} | id={target['target_id']}"
        )


def choose_targets_interactively(all_targets: List[dict], target_types: List[str]) -> List[dict]:
    candidates = filter_by_types(all_targets, target_types)
    print("")
    print(f"匹配到的对象数量：{len(candidates)}")
    print("1. 按名称或 ID 搜索后选择")
    print("2. 导出当前类型下的全部对象")
    mode = prompt("导出模式", "1")
    if mode == "2":
        if len(candidates) > 10:
            print(f"这会导出 {len(candidates)} 个会话。")
            if prompt("输入 EXPORT 确认") != "EXPORT":
                sys.exit("已取消")
        return candidates

    while True:
        query_text = prompt("搜索关键词，多个关键词用英文逗号分隔")
        queries = [item.strip() for item in query_text.split(",") if item.strip()]
        shortlist = rank_targets(candidates, queries)[:12]
        if not shortlist:
            print("没有匹配结果，请换一个关键词。")
            continue
        show_targets(shortlist)
        picked = prompt("输入要导出的序号，多个序号用英文逗号分隔；输入 r 重新搜索", "1")
        if picked.lower() == "r":
            continue
        indexes = []
        for item in picked.split(","):
            item = item.strip()
            if item.isdigit() and 1 <= int(item) <= len(shortlist):
                indexes.append(int(item) - 1)
        selected = [shortlist[index] for index in sorted(set(indexes))]
        if selected:
            return selected
        print("没有有效选择。")


def account_output_root(runtime: dict) -> Path:
    account_key = runtime.get("account_key") or runtime.get("account_id") or "unknown-account"
    safe_account_key = account_key.replace(":", "__").replace("/", "_")
    return OUTPUT_ROOT / "_accounts" / safe_account_key


def export_selected(runtime: dict, selected: List[dict], incremental: bool, no_attachments: bool, preserve_raw: bool) -> List[dict]:
    results = []
    message_db = Path(runtime["message_db"]).expanduser()
    contact_db = Path(runtime["contact_db"]).expanduser() if runtime.get("contact_db") else None
    wechat_root = Path(runtime["wechat_root"]).expanduser()
    output_root = account_output_root(runtime)
    output_root.mkdir(parents=True, exist_ok=True)
    print("")
    print(f"账号隔离导出目录：{output_root}")
    for target in selected:
        print("")
        print(f"正在导出：{target['target_name']} ({target['target_id']})")
        manifest = export_chat(
            db_path=message_db,
            contact_db=contact_db,
            target=target["target_id"],
            target_name=None,
            output_root=output_root,
            vault=None,
            folder="WeChat",
            wechat_root=wechat_root,
            no_attachments=no_attachments,
            incremental=incremental,
            preserve_raw=preserve_raw,
            include_id_in_slug=False,
        )
        build_bundle(Path(manifest["output_root"]))
        results.append(manifest)
    return results


def main():
    parser = argparse.ArgumentParser(description="Guided local WeChat chat export")
    parser.add_argument("--key-wait", type=int, default=300, help="Seconds to wait during key capture")
    parser.add_argument("--min-usable-keys", type=int, default=2, help="Auto-stop key capture after this many usable SQLCipher keys")
    parser.add_argument("--key-settle-seconds", type=int, default=8, help="Seconds to keep listening after enough keys are captured")
    parser.add_argument("--wechat-app", help="Override WeChat.app path")
    parser.add_argument("--bundle-id", help="Use this WeChat app bundle id and matching container when possible")
    parser.add_argument("--container-name", help="Only sync/export this WeChat container, for example com.tencent.xinWeChat2")
    parser.add_argument("--preserve-raw", action="store_true", help="Keep raw base64 message/source blobs in JSONL")
    args = parser.parse_args()

    ensure_not_installed_skill_dir()
    print_privacy_notice()

    apps = discover_wechat_apps()
    if apps:
        print("检测到的微信应用：")
        for app in apps:
            print(f"- {app.get('display_name')} | bundle_id={app.get('bundle_id') or '-'} | {app.get('app_path')}")

    sync_with_stored_keys(args)
    accounts = filter_accounts_for_args(ready_accounts(), args)
    if not accounts:
        capture_and_sync(args)
        accounts = filter_accounts_for_args(ready_accounts(), args)
    if not accounts:
        sys.exit("仍然没有可用的解密账号。请运行 scripts/doctor.py 排查后重试。")

    account = choose_account_interactively(accounts)
    runtime = account_to_runtime(select_account({"accounts": accounts}, account_id=account.get("account_key")))
    all_targets = list_targets(Path(runtime["message_db"]), Path(runtime["contact_db"]) if runtime.get("contact_db") else None)

    target_types = choose_target_types()
    selected = choose_targets_interactively(all_targets, target_types)
    include_attachments = yes_no("如果可用，是否复制媒体附件", default=False)
    incremental = yes_no("如果已有导出状态，是否使用增量导出", default=True)

    results = export_selected(
        runtime=runtime,
        selected=selected,
        incremental=incremental,
        no_attachments=not include_attachments,
        preserve_raw=args.preserve_raw,
    )

    print("")
    print("导出完成")
    for manifest in results:
        print(f"- {manifest['target_name']}: {manifest['message_count']} 条消息")
        print(f"  {manifest['output_root']}")


if __name__ == "__main__":
    main()
