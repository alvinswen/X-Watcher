"""单 JSON 文档原子读写引擎(低频目录实体)。封装 atomic.atomic_replace。"""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.atomic import atomic_replace


def read_doc(path: Path) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_doc(path: Path, obj: dict) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_replace(Path(path), payload.encode("utf-8"))
