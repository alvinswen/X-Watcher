#!/usr/bin/env python3
"""Safely wipe generated subject artifacts from the file data root."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _subject_ids(data_root: Path) -> list[str]:
    index = _load_json(data_root / "subjects" / "index.json")
    ids = index.get("subject_ids")
    if isinstance(ids, list):
        return [str(item) for item in ids if str(item)]
    subjects_dir = data_root / "subjects"
    return sorted(path.stem for path in subjects_dir.glob("*.json") if path.name != "index.json")


def _artifact_files(data_root: Path, subject_id: str, include_matches: bool) -> list[Path]:
    subject_dir = data_root / "subjects" / subject_id
    patterns = [
        "digests/*.jsonl",
        "digests/*.json",
        "review/latest.json",
        "review/history/*.json",
    ]
    if include_matches:
        patterns.append("matches/*.jsonl")
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in subject_dir.glob(pattern) if path.is_file())
    return sorted(files)


def _reset_pending(data_root: Path, subject_id: str, *, dry_run: bool) -> bool:
    subject_path = data_root / "subjects" / f"{subject_id}.json"
    subject = _load_json(subject_path)
    if not subject:
        return False
    changed = bool(subject.get("pending_classify") or subject.get("pending_review"))
    if dry_run:
        return changed
    subject["pending_classify"] = False
    subject["pending_review"] = False
    _write_json(subject_path, subject)
    return changed


def _remove_empty_dirs(subject_dir: Path) -> None:
    for rel in [
        Path("review/history"),
        Path("review"),
        Path("digests"),
        Path("matches"),
    ]:
        path = subject_dir / rel
        with suppress(OSError):
            path.rmdir()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wipe subject digest/review artifacts from XWATCHER_DATA_ROOT.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--subject-id", help="Only wipe one subject")
    group.add_argument("--all", action="store_true", help="Wipe all subjects")
    parser.add_argument(
        "--include-matches",
        action="store_true",
        help="Also wipe subject match shards",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete files after typing YES",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    data_root_value = os.environ.get("XWATCHER_DATA_ROOT")
    if not data_root_value:
        print("ERROR: XWATCHER_DATA_ROOT is required", file=sys.stderr)
        return 2
    data_root = Path(data_root_value).expanduser().resolve()
    subjects = _subject_ids(data_root) if args.all else [args.subject_id]
    subject_files = {
        subject_id: _artifact_files(data_root, subject_id, args.include_matches)
        for subject_id in subjects
    }
    pending_subjects = [
        subject_id for subject_id in subjects if _reset_pending(data_root, subject_id, dry_run=True)
    ]

    mode = "APPLY" if args.confirm else "DRY-RUN"
    print(f"{mode}: data_root={data_root}")
    print(f"subjects={len(subjects)} include_matches={args.include_matches}")
    for subject_id, files in subject_files.items():
        print(f"- {subject_id}: files={len(files)}")
        for path in files:
            print(f"  delete {path}")
        if subject_id in pending_subjects:
            print("  reset pending_classify/pending_review")

    if not args.confirm:
        print("DRY-RUN only; rerun with --confirm and type YES to delete.")
        return 0

    answer = input("Type YES to delete the listed artifacts: ")
    if answer != "YES":
        print("Cancelled; no files were deleted.")
        return 1

    deleted = 0
    for subject_id, files in subject_files.items():
        for path in files:
            try:
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                pass
        _reset_pending(data_root, subject_id, dry_run=False)
        _remove_empty_dirs(data_root / "subjects" / subject_id)
    print(f"Deleted files={deleted}; reset_pending_subjects={len(pending_subjects)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
