import argparse
import json
import sys
from pathlib import Path
from typing import List

from list_targets import list_targets


def matches_name_filters(target: dict, filters: List[str]) -> bool:
    haystacks = [
        (target.get("target_name") or "").lower(),
        (target.get("target_id") or "").lower(),
    ]
    return any(filter_text.lower() in hay for filter_text in filters for hay in haystacks)


def main():
    parser = argparse.ArgumentParser(description="Select WeChat targets for export")
    parser.add_argument("--message-db", required=True)
    parser.add_argument("--contact-db")
    parser.add_argument("--contacts", action="store_true")
    parser.add_argument("--groups", action="store_true")
    parser.add_argument("--filehelper", action="store_true")
    parser.add_argument("--all-contacts", action="store_true")
    parser.add_argument("--all-groups", action="store_true")
    parser.add_argument("--everything", action="store_true")
    parser.add_argument("--name", action="append", dest="names")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    message_db = Path(args.message_db).expanduser()
    if not message_db.exists():
        sys.exit(f"[!] message db not found: {message_db}")

    contact_db = Path(args.contact_db).expanduser() if args.contact_db else None
    targets = list_targets(message_db, contact_db)

    selected = []
    for target in targets:
        target_type = target["target_type"]
        type_selected = not any([args.contacts, args.groups, args.filehelper, args.all_contacts, args.all_groups, args.everything])
        if args.everything:
            type_selected = True
        elif target_type == "contact" and (args.contacts or args.all_contacts):
            type_selected = True
        elif target_type == "group" and (args.groups or args.all_groups):
            type_selected = True
        elif target_type == "filehelper" and args.filehelper:
            type_selected = True

        name_selected = True if not args.names else matches_name_filters(target, args.names)
        if type_selected and name_selected:
            selected.append(target)

    if args.json:
        print(json.dumps(selected, ensure_ascii=False, indent=2))
        return

    for index, target in enumerate(selected, start=1):
        print(f"{index:03d}. [{target['target_type']}] {target['target_name']} | {target['target_id']}")


if __name__ == "__main__":
    main()
