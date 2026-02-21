#!/usr/bin/env python3
"""
SEC-001 Migration: MD5 → BLAKE2b-128

Rehashes all memory entries in an existing antaris-memory store from the
legacy 12-char MD5 format to the new 32-char BLAKE2b-128 format.

Updates all shard files, search_index.json, tag_index.json, and
access_counts.json in-place.  Creates a timestamped backup of the entire
store before making any changes.

Usage:
    python3 tools/migrate_hashes.py <path_to_store>
    python3 tools/migrate_hashes.py /Users/moro/.openclaw/workspace/antaris_memory_store

Dry-run mode (no writes):
    python3 tools/migrate_hashes.py <path_to_store> --dry-run
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def blake2b_hash(source: str, line: int, content: str) -> str:
    """Compute the new BLAKE2b-128 hash (matches MemoryEntry.__init__)."""
    return hashlib.blake2b(
        f"{source}:{line}:{content[:100]}".encode(),
        digest_size=16,
    ).hexdigest()


def md5_hash(source: str, line: int, content: str) -> str:
    """Compute the old MD5 hash for verification."""
    return hashlib.md5(
        f"{source}:{line}:{content[:100]}".encode()
    ).hexdigest()[:12]


def migrate_store(store_path: str, dry_run: bool = False) -> None:
    path = Path(store_path)
    if not path.exists():
        print(f"ERROR: Store not found: {store_path}", file=sys.stderr)
        sys.exit(1)

    print(f"antaris-memory SEC-001 Migration: MD5 → BLAKE2b-128")
    print(f"Store: {path.resolve()}")
    print(f"Mode: {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
    print()

    # Step 1: Backup
    if not dry_run:
        backup_name = f"{path.name}_md5_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = path.parent / backup_name
        shutil.copytree(path, backup_path)
        print(f"Backup created: {backup_path}")
        print()

    # Step 2: Build hash remapping table from shard files
    shards_dir = path / "shards"
    if not shards_dir.exists():
        print("No shards/ directory found. Nothing to migrate.")
        return

    old_to_new: dict[str, str] = {}
    total_entries = 0
    shard_files = sorted(shards_dir.glob("shard_*.json"))

    print(f"Processing {len(shard_files)} shard file(s)...")

    for shard_file in shard_files:
        with open(shard_file, encoding="utf-8") as f:
            try:
                shard_data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  SKIP (corrupt): {shard_file.name} — {e}")
                continue

        # Shards are dicts with a "memories" key containing a list of entry dicts.
        # Older format may be a plain list — handle both.
        if isinstance(shard_data, dict):
            entries = shard_data.get("memories", [])
        else:
            entries = shard_data  # legacy flat list

        updated_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                updated_entries.append(entry)
                continue

            content = entry.get("content", "")
            source = entry.get("source", "")
            line = entry.get("line", 0)
            old_hash = entry.get("hash", "")

            new_hash = blake2b_hash(source, line, content)

            if old_hash and old_hash != new_hash:
                old_to_new[old_hash] = new_hash

            entry["hash"] = new_hash
            updated_entries.append(entry)
            total_entries += 1

        if not dry_run:
            if isinstance(shard_data, dict):
                shard_data["memories"] = updated_entries
                with open(shard_file, "w", encoding="utf-8") as f:
                    json.dump(shard_data, f, separators=(",", ":"))
            else:
                with open(shard_file, "w", encoding="utf-8") as f:
                    json.dump(updated_entries, f, separators=(",", ":"))

    print(f"  {total_entries} entries processed, {len(old_to_new)} hashes changed.")
    print()

    # Step 3: Update search_index.json
    # Structure: {"word_index": {word: {hash: score, ...}, ...}, ...metadata...}
    search_index_path = path / "search_index.json"
    if search_index_path.exists():
        with open(search_index_path, encoding="utf-8") as f:
            try:
                si = json.load(f)
            except json.JSONDecodeError:
                si = {}

        word_index = si.get("word_index", {})
        updated_word_index = {}
        for word, hash_scores in word_index.items():
            if isinstance(hash_scores, dict):
                updated_word_index[word] = {
                    old_to_new.get(h, h): score for h, score in hash_scores.items()
                }
            else:
                updated_word_index[word] = hash_scores
        si["word_index"] = updated_word_index

        if not dry_run:
            with open(search_index_path, "w", encoding="utf-8") as f:
                json.dump(si, f, separators=(",", ":"))
        print(f"search_index.json: {len(updated_word_index)} word entries updated.")

    # Step 4: Update tag_index.json
    # Structure: {"tag_to_memories": {tag: [hash, ...], ...}, ...metadata...}
    tag_index_path = path / "tag_index.json"
    if tag_index_path.exists():
        with open(tag_index_path, encoding="utf-8") as f:
            try:
                ti = json.load(f)
            except json.JSONDecodeError:
                ti = {}

        tag_to_memories = ti.get("tag_to_memories", {})
        updated_tag_to_memories = {}
        for tag, hashes in tag_to_memories.items():
            if isinstance(hashes, list):
                updated_tag_to_memories[tag] = [old_to_new.get(h, h) for h in hashes]
            else:
                updated_tag_to_memories[tag] = hashes
        ti["tag_to_memories"] = updated_tag_to_memories

        if not dry_run:
            with open(tag_index_path, "w", encoding="utf-8") as f:
                json.dump(ti, f, separators=(",", ":"))
        print(f"tag_index.json: {len(updated_tag_to_memories)} tags updated.")

    # Step 5: Update access_counts.json
    # Structure: flat dict {hash: count}
    access_counts_path = path / "access_counts.json"
    if access_counts_path.exists():
        with open(access_counts_path, encoding="utf-8") as f:
            try:
                counts = json.load(f)
            except json.JSONDecodeError:
                counts = {}

        updated_counts = {old_to_new.get(k, k): v for k, v in counts.items()}
        if not dry_run:
            with open(access_counts_path, "w", encoding="utf-8") as f:
                json.dump(updated_counts, f, separators=(",", ":"))
        print(f"access_counts.json: {len(updated_counts)} entries updated.")

    print()
    if dry_run:
        print("DRY RUN complete. No files were modified.")
        print(f"Would have remapped {len(old_to_new)} hashes across {total_entries} entries.")
    else:
        print(f"Migration complete. {len(old_to_new)} hashes remapped.")
        print(f"Backup preserved at: {backup_path}")
        print("Run 'python3 -m antaris_memory <store_path>' to verify the migrated store.")


def main():
    parser = argparse.ArgumentParser(description="Migrate antaris-memory store from MD5 to BLAKE2b-128 hashes.")
    parser.add_argument("store_path", help="Path to the antaris_memory_store directory.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing.")
    args = parser.parse_args()
    migrate_store(args.store_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
