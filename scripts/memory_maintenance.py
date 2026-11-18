"""
JARVIS memory maintenance (safe by default: reports only, changes nothing without --apply).

Background: earlier versions of the test suite ran against the real data folder. They left
test records in the memory stores and one test deleted the ChromaDB collection on every run.
Every memory is also mirrored in memory_fallback.json, so the semantic index can be rebuilt.

Usage (from the project root, with the venv active):
    python scripts/memory_maintenance.py                      # report only
    python scripts/memory_maintenance.py --purge-test-data    # preview removal of test records
    python scripts/memory_maintenance.py --adopt-unowned      # preview assigning owner-less records to you
    python scripts/memory_maintenance.py --rebuild-index      # preview re-indexing ChromaDB from the JSON mirror
    ... add --apply to actually do it (a timestamped backup of data/memory is made first)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.paths import LOCAL_OWNER_ID, memory_dir  # noqa: E402

TEST_OWNER = re.compile(r"^(user_[a-z0-9]+_[ab]|user_(alpha|beta|a|b)|test_.*|attacker|.*_test)$")
TEST_ID = re.compile(r"^(test_|legacy_)")


def _load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _owner_counts(items) -> dict:
    counts: dict = {}
    for owner in items:
        counts[owner] = counts.get(owner, 0) + 1
    return counts


def _is_test_entry(doc_id: str, owner) -> bool:
    return bool(TEST_ID.match(doc_id or "")) or bool(owner and TEST_OWNER.match(owner))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--purge-test-data", action="store_true")
    ap.add_argument("--adopt-unowned", action="store_true")
    ap.add_argument("--rebuild-index", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write changes (otherwise preview only)")
    args = ap.parse_args()

    mdir = memory_dir()
    json_path = mdir / "memory_fallback.json"
    convo_path = mdir / "conversations.json"
    store = _load(json_path, {})
    turns = _load(convo_path, [])

    print(f"Memory folder: {mdir}")
    print(f"Long-term (JSON mirror): {len(store)} records by owner {_owner_counts((v.get('metadata') or {}).get('user_id') for v in store.values())}")
    print(f"Conversation turns:      {len(turns)} by owner {_owner_counts(t.get('user_id') for t in turns)}")

    if args.purge_test_data:
        store_new = {k: v for k, v in store.items()
                     if not _is_test_entry(k, (v.get("metadata") or {}).get("user_id"))}
        turns_new = [t for t in turns if not _is_test_entry("", t.get("user_id"))]
        print(f"[purge] would remove {len(store) - len(store_new)} test records and {len(turns) - len(turns_new)} test turns")
        store, turns = store_new, turns_new

    if args.adopt_unowned:
        n_store = sum(1 for v in store.values() if not (v.get("metadata") or {}).get("user_id"))
        n_turns = sum(1 for t in turns if not t.get("user_id"))
        for v in store.values():
            meta = v.setdefault("metadata", {})
            if not meta.get("user_id"):
                meta["user_id"] = LOCAL_OWNER_ID
        for t in turns:
            if not t.get("user_id"):
                t["user_id"] = LOCAL_OWNER_ID
        print(f"[adopt] would assign {n_store} records and {n_turns} turns to '{LOCAL_OWNER_ID}'")

    if not args.apply:
        if args.purge_test_data or args.adopt_unowned or args.rebuild_index:
            print("\nPreview only. Re-run with --apply to make these changes.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = mdir.parent / f"memory-backup-{stamp}"
    shutil.copytree(mdir, backup)
    print(f"Backup written to {backup}")

    if args.purge_test_data or args.adopt_unowned:
        json_path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
        convo_path.write_text(json.dumps(turns, indent=2, ensure_ascii=False), encoding="utf-8")
        print("JSON stores updated.")

    if args.rebuild_index:
        from core.memory import JarvisMemory
        mem = JarvisMemory()
        if mem._collection is None:
            print("ChromaDB is not available; nothing to rebuild.")
            return 1
        collection = mem._collection
        existing = collection.get(include=[])
        if existing.get("ids"):
            collection.delete(ids=existing["ids"])
        ids, docs, metas = [], [], []
        for doc_id, entry in store.items():
            meta = {k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                    for k, v in (entry.get("metadata") or {}).items() if v is not None}
            ids.append(doc_id)
            docs.append(str(entry.get("content", "")))
            metas.append(meta or {"category": "knowledge"})
        for i in range(0, len(ids), 64):
            collection.add(ids=ids[i:i + 64], documents=docs[i:i + 64], metadatas=metas[i:i + 64])
        print(f"Re-indexed {len(ids)} records into ChromaDB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
