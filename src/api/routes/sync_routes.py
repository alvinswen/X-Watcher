"""数据同步 API 路由。

提供数据导出下载、导入预览和导入执行端点。
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.sync.domain.models import (
    ConflictStrategy,
    ExportPackage,
    SyncCategory,
)
from src.sync.format.json_format import CURRENT_SCHEMA_VERSION, DateTimeEncoder
from src.sync.services.export_service import ExportService
from src.sync.services.import_service import ImportService
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/sync", tags=["sync"])


def _parse_categories_str(value: str | None) -> list[SyncCategory] | None:
    """解析逗号分隔的分类字符串。"""
    if not value:
        return None
    cats = []
    for item in value.split(","):
        item = item.strip()
        if item and item in SyncCategory.__members__:
            cats.append(SyncCategory(item))
    return cats or None


def _parse_strategy(value: str | None) -> ConflictStrategy:
    """解析冲突策略字符串。"""
    if not value:
        return ConflictStrategy.skip
    try:
        return ConflictStrategy(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的冲突策略: {value}，可选: skip, overwrite, merge",
        )


def _parse_datetime(value: str | None) -> datetime | None:
    """解析 ISO 格式日期时间字符串。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的日期时间格式: {value}，请使用 ISO 8601 格式",
        )


def _parse_upload_file(content: bytes) -> ExportPackage:
    """解析上传的 JSON 文件为 ExportPackage。"""
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="导出文件格式错误：顶层必须是 JSON 对象")
    if "metadata" not in raw:
        raise HTTPException(status_code=400, detail="导出文件格式错误：缺少 metadata 字段")
    if "data" not in raw:
        raise HTTPException(status_code=400, detail="导出文件格式错误：缺少 data 字段")

    file_version = raw["metadata"].get("schema_version", 0)
    if file_version > CURRENT_SCHEMA_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"schema 版本不兼容：文件版本 {file_version}，当前支持最高版本 {CURRENT_SCHEMA_VERSION}",
        )

    try:
        from src.sync.format.json_format import read_export_file
        from src.sync.domain.models import ExportFilters, ExportMetadata

        meta_raw = raw["metadata"]
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
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"导出文件解析失败: {e}")


@router.post("/export")
async def export_data(
    request: dict[str, Any] | None = None,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> StreamingResponse:
    """导出数据为 JSON 文件下载。"""
    params = request or {}
    categories: list[SyncCategory] | None = None
    if "categories" in params and params["categories"]:
        categories = []
        for c in params["categories"]:
            if c in SyncCategory.__members__:
                categories.append(SyncCategory(c))
        categories = categories or None

    since = _parse_datetime(params.get("since"))
    until = _parse_datetime(params.get("until"))
    authors = params.get("authors") or None
    instance_id = params.get("instance_id") or "web-export"

    def _do_export() -> ExportPackage:
        svc = ExportService()
        return svc.export(
            categories=categories,
            since=since,
            until=until,
            authors=authors,
            instance_id=instance_id,
        )

    pkg = await asyncio.to_thread(_do_export)

    # 序列化为 JSON
    data = pkg.model_dump(mode="json")
    content = json.dumps(data, cls=DateTimeEncoder, ensure_ascii=False, indent=2)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"x-watcher-export-{ts}.json"

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/import/preview")
async def import_preview(  # type: ignore[no-untyped-def]  # 无 response_model·补返回标注会被 FastAPI≥0.89 提升为响应 schema 致 OpenAPI 漂移(A3 repro E7 实证)·保持无标注
    file: UploadFile = File(...),
    categories: str | None = Form(None),
    strategy: str | None = Form(None),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    """预览导入操作（dry-run）。"""
    content = await file.read()
    pkg = _parse_upload_file(content)
    cats = _parse_categories_str(categories)
    conflict_strategy = _parse_strategy(strategy)

    def _do_preview() -> Any:
        svc = ImportService()
        return svc.import_data(
            package=pkg,
            categories=cats,
            strategy=conflict_strategy,
            dry_run=True,
        )

    result = await asyncio.to_thread(_do_preview)

    # 构建响应
    stats = {}
    for table, s in result.stats.items():
        stats[table] = {
            "inserted": s.inserted,
            "updated": s.updated,
            "skipped": s.skipped,
            "errors": s.errors,
            "total": s.total,
        }

    return {
        "metadata": pkg.metadata.model_dump(mode="json"),
        "stats": stats,
        "errors": result.errors,
        "success": result.success,
        "dry_run": True,
    }


@router.post("/import/execute")
async def import_execute(  # type: ignore[no-untyped-def]  # 无 response_model·补返回标注会被 FastAPI≥0.89 提升为响应 schema 致 OpenAPI 漂移(A3 repro E7 实证)·保持无标注
    file: UploadFile = File(...),
    categories: str | None = Form(None),
    strategy: str | None = Form(None),
    _admin: UserDomain = Depends(get_current_admin_user),
):
    """执行实际导入操作。"""
    content = await file.read()
    pkg = _parse_upload_file(content)
    cats = _parse_categories_str(categories)
    conflict_strategy = _parse_strategy(strategy)

    def _do_import() -> Any:
        svc = ImportService()
        return svc.import_data(
            package=pkg,
            categories=cats,
            strategy=conflict_strategy,
            dry_run=False,
        )

    result = await asyncio.to_thread(_do_import)

    stats = {}
    for table, s in result.stats.items():
        stats[table] = {
            "inserted": s.inserted,
            "updated": s.updated,
            "skipped": s.skipped,
            "errors": s.errors,
            "total": s.total,
        }

    return {
        "stats": stats,
        "errors": result.errors,
        "success": result.success,
        "dry_run": False,
    }
