"""Subject 索引小工具。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from src.storage import paths
from src.storage.doc_store import atomic_write_doc, read_doc

_SUBJECT_ID_RE = re.compile(r"^sub_[a-z0-9]{8}$")


def load_subject_ids(data_root: Path) -> list[str]:
    doc = read_doc(paths.subject_index(data_root))
    if not doc:
        return []
    ids = doc.get("subject_ids", [])
    if not isinstance(ids, list):
        return []
    return [str(item) for item in ids if isinstance(item, str)]


def save_subject_ids(data_root: Path, subject_ids: list[str]) -> None:
    unique: list[str] = []
    seen: set[str] = set()
    for subject_id in subject_ids:
        if subject_id not in seen:
            seen.add(subject_id)
            unique.append(subject_id)
    atomic_write_doc(paths.subject_index(data_root), {"subject_ids": unique})


def new_subject_id(data_root: Path) -> str:
    existing = set(load_subject_ids(data_root))
    while True:
        subject_id = f"sub_{uuid.uuid4().hex[:8]}"
        if subject_id not in existing and _SUBJECT_ID_RE.match(subject_id):
            return subject_id
