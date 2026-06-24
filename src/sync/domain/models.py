"""数据同步领域模型。

定义导出/导入相关的枚举、数据结构和配置。
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SyncCategory(str, Enum):
    """可同步的数据分类。"""

    config = "config"
    content = "content"


class ConflictStrategy(str, Enum):
    """导入冲突解决策略。"""

    skip = "skip"
    overwrite = "overwrite"
    merge = "merge"


class ExportFilters(BaseModel):
    """导出过滤条件。"""

    since: datetime | None = None
    until: datetime | None = None
    authors: list[str] | None = None


class ExportMetadata(BaseModel):
    """导出文件的元数据。"""

    format_version: str = "1.0"
    schema_version: int = 1
    exported_at: datetime
    source_instance_id: str
    categories: list[str]
    filters: ExportFilters = Field(default_factory=ExportFilters)
    counts: dict[str, int] = Field(default_factory=dict)


class ExportPackage(BaseModel):
    """完整的导出数据包。"""

    metadata: ExportMetadata
    data: dict[str, Any] = Field(default_factory=dict)


class ImportStats(BaseModel):
    """单个表的导入统计。"""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.skipped + self.errors


class ImportResult(BaseModel):
    """导入操作的完整结果。"""

    success: bool = True
    stats: dict[str, ImportStats] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    dry_run: bool = False
