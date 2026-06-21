"""迁移框架共享工具:naive 化、迁移报告。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def naive(dt: datetime | None) -> datetime | None:
    """aware datetime → naive UTC(对齐文件层 naive 约定);naive 原样返回。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class MigrationReport:
    entity: str
    pg_count: int
    written: int = 0
    validated: int = 0
    mismatches: list[str] = field(default_factory=list)
    dropped_columns: list[str] = field(default_factory=list)  # pg 有而文件层设计性不存

    @property
    def ok(self) -> bool:
        return (
            not self.mismatches
            and self.pg_count == self.written == self.validated
        )

    def line(self) -> str:
        flag = "OK " if self.ok else "FAIL"
        drop = f" dropped={self.dropped_columns}" if self.dropped_columns else ""
        miss = f" mismatches={len(self.mismatches)}" if self.mismatches else ""
        return f"[{flag}] {self.entity:14} pg={self.pg_count} written={self.written} validated={self.validated}{drop}{miss}"
