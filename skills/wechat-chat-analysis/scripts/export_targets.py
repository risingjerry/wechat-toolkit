import argparse
import json
import sys
from pathlib import Path
from typing import List

from account_runtime import resolve_runtime
from build_analysis_bundle import build_analysis_input, compute_stats, load_messages
from export_chat import export_chat
from list_targets import list_targets
from select_targets import matches_name_filters


def matches_exact_name_filters(target: dict, filters: List[str]) -> bool:
    haystacks = [
        (target.get("target_name") or "").strip().lower(),
        (target.get("target_id") or "").strip().lower(),
    ]
    return any(filter_text.strip().lower() == hay for filter_text in filters for hay in haystacks)


def build_bundle(export_dir: Path) -> None:
    manifest_path = export_dir / "manifest.json"
    messages_path = export_dir / "messages.jsonl"
    stats_path = export_dir / "stats.json"
    analysis_input_path = export_dir / "analysis_input.md"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = load_messages(messages_path)
    stats = compute_stats(items, Path(manifest["markdown_root"]))
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis_input_path.write_text(build_analysis_input(manifest, stats), encoding="utf-8")


def choose_targets(message_db: Path, contact_db: Path, target_types: List[str], names: List[str], everything: bool) -> List[dict]:
    targets = list_targets(message_db, contact_db)
    type_matched = []
    for target in targets:
        type_selected = everything or not target_types or target["target_type"] in target_types
        if type_selected:
            type_matched.append(target)
    if not names:
        return type_matched

    exact = [target for target in type_matched if matches_exact_name_filters(target, names)]
    if exact:
        return exact
    return [target for target in type_matched if matches_name_filters(target, names)]


def main():
    parser = argparse.ArgumentParser(description="Batch export selected WeChat targets")
    parser.add_argument("--message-db")
    parser.add_argument("--contact-db")
    parser.add_argument("--sync-manifest")
    parser.add_argument("--account-id")
    parser.add_argument("--first-ok", action="store_true")
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent.parent / "output"))
    parser.add_argument("--wechat-root")
    parser.add_argument("--vault")
    parser.add_argument("--folder", default="WeChat")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--no-attachments", action="store_true")
    parser.add_argument("--preserve-raw", action="store_true", help="Keep raw base64 message/source blobs in JSONL")
    parser.add_argument("--include-id-in-slug", action="store_true", help="Include target id in output folder name")
    parser.add_argument("--contacts", action="store_true")
    parser.add_argument("--groups", action="store_true")
    parser.add_argument("--filehelper", action="store_true")
    parser.add_argument("--everything", action="store_true")
    parser.add_argument("--name", action="append", dest="names")
    args = parser.parse_args()

    if args.sync_manifest:
        runtime = resolve_runtime(Path(args.sync_manifest).expanduser(), account_id=args.account_id, first_ok=args.first_ok)
        message_db = Path(runtime["message_db"]).expanduser()
        contact_db = Path(runtime["contact_db"]).expanduser() if runtime.get("contact_db") else None
        wechat_root = Path(runtime["wechat_root"]).expanduser()
    else:
        if not args.message_db:
            sys.exit("[!] Provide --message-db or --sync-manifest")
        message_db = Path(args.message_db).expanduser()
        contact_db = Path(args.contact_db).expanduser() if args.contact_db else None
        wechat_root = Path(args.wechat_root).expanduser() if args.wechat_root else None

    output_root = Path(args.output_dir).expanduser()
    vault = Path(args.vault).expanduser() if args.vault else None

    target_types = []
    if args.contacts:
        target_types.append("contact")
    if args.groups:
        target_types.append("group")
    if args.filehelper:
        target_types.append("filehelper")

    targets = choose_targets(
        message_db=message_db,
        contact_db=contact_db,
        target_types=target_types,
        names=args.names or [],
        everything=args.everything,
    )

    if not targets:
        print(json.dumps({"count": 0, "exports": [], "message": "No matching targets found"}, ensure_ascii=False, indent=2))
        return

    results = []
    for target in targets:
        manifest = export_chat(
            db_path=message_db,
            contact_db=contact_db,
            target=target["target_id"],
            target_name=None,
            output_root=output_root,
            vault=vault,
            folder=args.folder,
            wechat_root=wechat_root,
            no_attachments=args.no_attachments,
            incremental=args.incremental,
            preserve_raw=args.preserve_raw,
            include_id_in_slug=args.include_id_in_slug,
        )
        build_bundle(Path(manifest["output_root"]))
        results.append(manifest)

    print(json.dumps({"count": len(results), "exports": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
