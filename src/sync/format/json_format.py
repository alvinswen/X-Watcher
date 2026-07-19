"""JSON 文件读写和 schema 版本校验。"""

import json
from datetime import datetime
from pathlib import Path

from src.sync.domain.models import ExportFilters, ExportMetadata, ExportPackage

CURRENT_SCHEMA_VERSION = 1


class DateTimeEncoder(json.JSONEncoder):
    """支持 datetime 的 JSON 编码器。"""

    def default(self, obj: object) -> object:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def write_export_file(
    package: ExportPackage,
    path: Path,
    pretty: bool = False,
) -> None:
    """将导出数据包写入 JSON 文件。"""
    data = package.model_dump(mode="json")
    indent = 2 if pretty else None
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, cls=DateTimeEncoder, ensure_ascii=False, indent=indent)


def read_export_file(path: Path, force: bool = False) -> ExportPackage:
    """从 JSON 文件读取导出数据包。

    Args:
        path: JSON 文件路径
        force: 跳过 schema 版本兼容性检查

    Returns:
        ExportPackage 实例

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 格式错误或版本不兼容
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError("导出文件格式错误：顶层必须是 JSON 对象")

    if "metadata" not in raw:
        raise ValueError("导出文件格式错误：缺少 metadata 字段")

    if "data" not in raw:
        raise ValueError("导出文件格式错误：缺少 data 字段")

    meta_raw = raw["metadata"]

    # Schema 版本兼容性检查
    file_version = meta_raw.get("schema_version", 0)
    if not force and file_version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"schema 版本不兼容：文件版本 {file_version}，"
            f"当前支持最高版本 {CURRENT_SCHEMA_VERSION}。"
            f"使用 --force 跳过检查。"
        )

    # 解析 filters
    filters_raw = meta_raw.get("filters", {})
    filters = ExportFilters(
        since=filters_raw.get("since"),
        until=filters_raw.get("until"),
        authors=filters_raw.get("authors"),
    )

    metadata = ExportMetadata(
        format_version=meta_raw.get("format_version", "1.0"),
        schema_version=file_version,
        exported_at=meta_raw["exported_at"],
        source_instance_id=meta_raw.get("source_instance_id", "unknown"),
        categories=meta_raw.get("categories", []),
        filters=filters,
        counts=meta_raw.get("counts", {}),
    )

    return ExportPackage(metadata=metadata, data=raw["data"])
