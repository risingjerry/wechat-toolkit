import argparse
import json
from pathlib import Path
from typing import List

from account_runtime import resolve_runtime
from list_targets import list_targets
from select_targets import matches_name_filters


def filter_by_types(targets: List[dict], target_types: List[str]) -> List[dict]:
    if not target_types:
        return targets
    return [target for target in targets if target["target_type"] in target_types]


def rank_targets(targets: List[dict], queries: List[str]) -> List[dict]:
    if not queries:
        return targets

    ranked = []
    lowered_queries = [query.lower().strip() for query in queries if query.strip()]
    for target in targets:
        name = (target.get("target_name") or "").lower()
        target_id = (target.get("target_id") or "").lower()
        score = None
        for query in lowered_queries:
            if name == query or target_id == query:
                score = 0 if score is None else min(score, 0)
            elif name.startswith(query) or target_id.startswith(query):
                score = 1 if score is None else min(score, 1)
            elif query in name or query in target_id:
                score = 2 if score is None else min(score, 2)
        if score is not None:
            ranked.append((score, -(target.get("message_count") or 0), target))

    ranked.sort(key=lambda item: (item[0], item[1], (item[2].get("target_name") or "").lower()))
    return [item[2] for item in ranked]


def main():
    parser = argparse.ArgumentParser(description="Return a shortlist of WeChat targets for interactive refine flow")
    parser.add_argument("--sync-manifest")
    parser.add_argument("--account-id")
    parser.add_argument("--message-db")
    parser.add_argument("--contact-db")
    parser.add_argument("--target-type", action="append", choices=["contact", "group", "filehelper"])
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    if args.sync_manifest:
        runtime = resolve_runtime(Path(args.sync_manifest).expanduser(), account_id=args.account_id)
        message_db = Path(runtime["message_db"]).expanduser()
        contact_db = Path(runtime["contact_db"]).expanduser() if runtime.get("contact_db") else None
    else:
        message_db = Path(args.message_db).expanduser()
        contact_db = Path(args.contact_db).expanduser() if args.contact_db else None

    targets = list_targets(message_db, contact_db)
    targets = filter_by_types(targets, args.target_type or [])
    ranked = rank_targets(targets, args.queries or [])

    output = {
        "query": args.queries or [],
        "target_types": args.target_type or [],
        "count": len(ranked),
        "shortlist": ranked[: args.limit],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
