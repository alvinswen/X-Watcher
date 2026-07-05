"""单 JSON 文档原子读写引擎(低频目录实体)。封装 atomic.atomic_replace。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from src.storage.atomic import atomic_replace


def read_doc(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def atomic_write_doc(path: Path, obj: dict[str, Any]) -> None:
    payload = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_replace(Path(path), payload.encode("utf-8"))
