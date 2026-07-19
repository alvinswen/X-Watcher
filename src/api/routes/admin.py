"""Admin API 路由。

提供管理端点，包括手动触发抓取任务和查询任务状态。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from src.mcp.security import audit_log
from src.scraper import ArticleFetchService, ScrapingService, TaskRegistry, TaskStatus
from src.shared.error_messages import ARTICLE_BACKFILL_FAILED
from src.user.api.auth import get_current_admin_user
from src.user.domain.models import UserDomain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_scraping_service() -> ScrapingService:
    """获取抓取服务实例。

    无状态工厂:每次调用返回新实例,不再跨请求复用同一个模块级单例
    (CHG-032 目标 4)。调用方使用完毕后必须调用一次
    ``ScrapingService.close()`` 释放内部持有的网络连接——本文件内的抓取
    消费点已补齐该收尾动作(见 ``_close_scraping_service``),新增
    调用点须遵循同一约定。
    """
    return ScrapingService()


def get_article_fetch_service() -> ArticleFetchService:
    """Create a standalone Article service whose caller must close it."""
    return ArticleFetchService()


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例。

    ``TaskRegistry.get_instance()`` 本身即类级单例,无需模块级全局变量
    重复缓存同一引用(CHG-032 目标 4 · Q3 零风险清理)。
    """
    return TaskRegistry.get_instance()


async def _close_scraping_service(service: ScrapingService, context: str = "") -> None:
    """关闭抓取服务的连接资源(CHG-032 目标 4)。

    关闭失败仅记录警告日志,不覆盖或掩盖调用方已经产生的抓取/回溯结果
    (Loop-1 自修项:关闭失败与业务成败是两件独立的事)。

    ⚠️ 本函数与 ``src/mcp/tools/admin_tools.py`` 里的同名 helper 是**两份独立实现**,
    不要合并成一个跨文件共享函数(CHG-032 A5 加固 3)。原因:本文件在模块顶部固定
    ``from src.scraper import ScrapingService`` 并把它用作精确类型标注;而
    ``admin_tools.py`` 把 scraper 符号一律做函数体内局部 import、该 helper 用 ``Any``
    标注。两者对"抓取服务"这个符号的引入方式不同,强行合并会把模块级 scraper import
    带进 ``admin_tools.py``——而那个文件**没有** ``from __future__ import annotations``,
    模块级函数的类型标注会在模块加载期(MCP server 启动阶段)就地求值,一旦 import 缺失
    即抛 NameError。故这两份看似重复的 helper 必须各留一份,不要合并、不要"顺手统一"。

    Args:
        service: 待关闭的抓取服务实例
        context: 可选的调用来源标签(如 " (task_id=xxx)"),拼进关闭失败的告警文案,
            便于多任务并发时运维一眼看出这条告警属于哪一次调用(CHG-032 A5 加固 4)
    """
    try:
        await service.close()
    except Exception as e:
        logger.warning(f"关闭 ScrapingService 连接失败{context}: {e}")


async def _close_article_fetch_service(
    service: ArticleFetchService,
    context: str = "",
) -> None:
    """Close an Article service without masking its business result."""
    try:
        await service.close()
    except Exception as e:
        logger.warning(f"关闭 ArticleFetchService 连接失败{context}: {e}")


def _validate_username_format(username: str) -> None:
    """执行管理端严格用户名格式校验，不做剥 @ 或大小写规范化。"""
    if not (1 <= len(username) <= 15):
        raise ValueError(f"用户名 '{username}' 长度必须在 1-15 字符之间")
    if not username.replace("_", "").isalnum():
        raise ValueError(f"用户名 '{username}' 只能包含字母、数字和下划线")


class ScrapeRequest(BaseModel):
    """抓取请求模型（wire 双格式：列表或逗号分隔字符串）。"""

    usernames: list[str] | str = Field(
        ...,
        description="用户名列表或逗号分隔字符串",
    )
    limit: int = Field(
        default=100,
        strict=True,
        ge=1,
        le=1000,
        description="每用户抓取上限",
    )

    @property
    def usernames_as_str(self) -> str:
        """把双格式用户名归一为逗号分隔字符串。"""
        if isinstance(self.usernames, list):
            return ",".join(u.strip() for u in self.usernames if u.strip())
        return self.usernames

    @property
    def parsed_usernames(self) -> list[str]:
        """返回去空白、去空项后的用户名列表。"""
        return [u.strip() for u in self.usernames_as_str.split(",") if u.strip()]

    @field_validator("limit", mode="before")
    @classmethod
    def _validate_limit_range(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and not (1 <= value <= 1000):
            raise ValueError("limit 必须在 1-1000 之间")
        return value

    @model_validator(mode="after")
    def _validate(self) -> "ScrapeRequest":
        if not self.usernames_as_str.strip():
            raise ValueError("usernames 不能为空")
        parsed = self.parsed_usernames
        if not parsed:
            raise ValueError("至少需要提供一个有效的用户名")
        for username in parsed:
            _validate_username_format(username)
        return self


class ScrapeResponse(BaseModel):
    """抓取任务受理响应。"""

    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    """抓取任务状态响应。"""

    task_id: str
    task_name: str = ""
    status: Literal["pending", "running", "completed", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: dict[str, Any] = Field(
        default_factory=lambda: {
            "current": 0,
            "total": 0,
            "percentage": 0.0,
        }
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def _status_enum_to_str(cls, value: Any) -> Any:
        enum_value = getattr(value, "value", None)
        return enum_value if isinstance(enum_value, str) else value

    @field_validator("progress", mode="before")
    @classmethod
    def _progress_falsy_to_default(cls, value: Any) -> Any:
        return value or {"current": 0, "total": 0, "percentage": 0.0}

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_falsy_to_default(cls, value: Any) -> Any:
        return value or {}

    @field_serializer(
        "created_at",
        "started_at",
        "completed_at",
        when_used="json",
    )
    def _serialize_dt(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


class TaskDeletionResponse(BaseModel):
    """抓取任务删除响应。"""

    message: str


class BackfillRequest(BaseModel):
    """Article 回溯请求。"""

    all: bool = False
    username: str | None = None
    max_tweets: int = Field(default=200, strict=True, ge=1, le=1000)

    @field_validator("username", mode="after")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _validate_single_user_mode(self) -> "BackfillRequest":
        if self.all:
            return self
        username = self.username or ""
        if not username:
            raise ValueError("username 不能为空")
        _validate_username_format(username)
        return self


class BackfillSingleUserResponse(BaseModel):
    """单用户 Article 回溯响应。"""

    username: str
    result: dict[str, Any]


async def _run_scraping_task_async(task_id: str, usernames: list[str], limit: int) -> None:
    """在主事件循环中异步运行抓取任务。

    使用 asyncio.create_task 在主事件循环中执行，避免创建新的事件循环导致
    跨循环问题（摘要队列入队、数据库 session、Semaphore 等均绑定到主循环）。

    Args:
        task_id: 任务 ID
        usernames: 用户名列表
        limit: 抓取限制
    """
    import time

    from src.logging_config import trace_id_var

    # 设置 trace_id，使所有下游日志（去重、摘要）可追踪
    trace_id_var.set(task_id)

    service = get_scraping_service()
    registry = get_task_registry()

    # manual_limit 解析已下沉至 ScrapingService.scrape_users 服务层单点判断
    # (manual_limits 未传即 None 时自动解析活跃账号配置),此处不再自行读取
    # follows 仓储,避免与服务层重复查询(CHG-031 目标 1,技术决策见方案 § 九-1)。
    start_time = time.time()
    logger.info(
        f"抓取任务开始: {len(usernames)} 个用户, limit={limit}",
        extra={"task_id": task_id, "event": "scrape_task_start"},
    )

    try:
        await service.scrape_users(
            usernames=usernames,
            limit=limit,
            task_id=task_id,
        )
        elapsed = time.time() - start_time
        logger.info(
            f"抓取任务完成: 耗时 {elapsed:.1f}s",
            extra={
                "task_id": task_id,
                "event": "scrape_task_done",
                "processing_time_ms": int(elapsed * 1000),
            },
        )
    except Exception as e:
        elapsed = time.time() - start_time
        logger.exception(
            f"后台抓取任务执行失败: {e}",
            extra={
                "task_id": task_id,
                "event": "scrape_task_failed",
                "error_type": type(e).__name__,
            },
        )
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
    finally:
        # 本次抓取任务(无论成功失败)结束后关闭一次连接,CHG-032 目标 4
        # (context 传 task_id,关闭失败时告警可定位到具体任务,A5 加固 4)
        await _close_scraping_service(service, f" (task_id={task_id})")


async def _run_backfill_all_async(task_id: str, max_tweets: int) -> None:
    """后台执行批量 Article 回溯。

    逐账号顺序调用 backfill_articles_for_user，避免 API rate limit。
    通过 TaskRegistry 更新进度和最终结果。

    Args:
        task_id: 任务 ID
        max_tweets: 每个账号扫描的推文数量上限
    """
    import time

    from src.scraper.scheduled_job import get_active_follows_async

    service = get_article_fetch_service()
    registry = get_task_registry()

    start_time = time.time()
    logger.info(
        f"Article 批量回溯开始: max_tweets={max_tweets}",
        extra={"task_id": task_id, "event": "backfill_all_start"},
    )

    try:
        follows = await get_active_follows_async()
        total = len(follows)
        details: list[dict[str, Any]] = []
        summary = {"total_checked": 0, "total_found": 0, "total_skipped": 0, "total_errors": 0}

        for i, follow in enumerate(follows):
            username = follow["username"]
            registry.update_progress(task_id, i, total)

            try:
                result = await service.backfill_articles_for_user(
                    username,
                    max_tweets=max_tweets,
                )
            except Exception as e:
                logger.warning(f"Article 批量回溯跳过 {username}: {e}")
                result = {"checked": 0, "found": 0, "skipped": 0, "errors": 1}

            details.append(
                {
                    "username": username,
                    "checked": result.get("checked", 0),
                    "found": result.get("found", 0),
                    "skipped": result.get("skipped", 0),
                    "errors": result.get("errors", 0),
                }
            )
            summary["total_checked"] += result.get("checked", 0)
            summary["total_found"] += result.get("found", 0)
            summary["total_skipped"] += result.get("skipped", 0)
            summary["total_errors"] += result.get("errors", 0)

        registry.update_progress(task_id, total, total)
        elapsed = time.time() - start_time
        logger.info(
            f"Article 批量回溯完成: {total} 个账号, found={summary['total_found']}, "
            f"耗时 {elapsed:.1f}s",
            extra={"task_id": task_id, "event": "backfill_all_done"},
        )
        registry.update_task_status(
            task_id,
            TaskStatus.COMPLETED,
            result={"total_users": total, "summary": summary, "details": details},
        )
    except Exception as e:
        logger.exception(
            f"Article 批量回溯失败: {e}",
            extra={"task_id": task_id, "event": "backfill_all_failed"},
        )
        registry.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
    finally:
        # 整批账号(逐账号容错·277-284行 warning 留痕继续)处理完才关闭一次,Q2
        # (context 传 task_id,A5 加固 4)
        await _close_article_fetch_service(service, f" (task_id={task_id})")


@router.post(
    "/scrape",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ScrapeResponse,
)
async def start_scraping(
    request: ScrapeRequest,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> ScrapeResponse:
    """启动手动抓取任务。

    接收用户名列表和抓取限制，创建异步抓取任务并立即返回任务 ID。

    Args:
        request: 请求体，包含 usernames 和 limit
        background_tasks: FastAPI 后台任务管理器

    Returns:
        dict: 包含 task_id 和 status 的响应

    Raises:
        HTTPException: 409 任务冲突
    """
    registry = get_task_registry()
    registry.cleanup_expired_tasks(ttl_hours=24)

    # 检查是否有相同的任务正在运行
    for task in registry.get_all_tasks():
        if (
            task["status"] == TaskStatus.RUNNING
            and task.get("metadata", {}).get("usernames") == request.usernames_as_str
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"相同的抓取任务正在执行中: {task['task_id']}",
            )

    # 创建任务
    task_id = registry.create_task(
        task_name=f"抓取 {len(request.parsed_usernames)} 个用户",
        metadata={
            "usernames": request.usernames_as_str,
            "limit": request.limit,
        },
    )

    # 在主事件循环中创建异步任务（避免跨循环问题）
    asyncio.create_task(
        _run_scraping_task_async(
            task_id,
            request.parsed_usernames,
            request.limit,
        ),
        name=f"scrape-{task_id}",
    )

    logger.info(f"创建抓取任务: {task_id} - {request.parsed_usernames}")

    audit_log(
        "start_scraping",
        "scrape",
        params={"usernames": request.parsed_usernames, "limit": request.limit},
        source="api",
        user=_admin.name,
    )

    return ScrapeResponse(task_id=task_id, status="pending")


@router.get("/scrape/{task_id}", response_model=TaskStatusResponse)
async def get_scraping_status(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> TaskStatusResponse:
    """查询抓取任务状态。

    返回任务的当前状态、进度和结果（如果已完成）。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 任务状态详情

    Raises:
        HTTPException: 404 任务不存在
    """
    registry = get_task_registry()
    task_data = registry.get_task_status(task_id)

    if task_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    response = TaskStatusResponse(
        task_id=task_data["task_id"],
        status=task_data["status"],
        task_name=task_data.get("task_name", ""),
        result=task_data.get("result"),
        error=task_data.get("error"),
        created_at=task_data.get("created_at"),
        started_at=task_data.get("started_at"),
        completed_at=task_data.get("completed_at"),
        progress=task_data.get("progress"),
        metadata=task_data.get("metadata"),
    )

    return response


@router.get("/scrape", response_model=list[TaskStatusResponse])
async def list_scraping_tasks(
    status: Literal["pending", "running", "completed", "failed"] | None = None,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> list[TaskStatusResponse]:
    """列出所有抓取任务。

    Args:
        status: 可选的状态过滤器

    Returns:
        list[dict]: 任务列表
    """
    registry = get_task_registry()

    if status is None:
        tasks = registry.get_all_tasks()
    else:
        task_status = TaskStatus(status)
        tasks = registry.get_tasks_by_status(task_status)

    return [
        TaskStatusResponse(
            task_id=t["task_id"],
            status=t["status"],
            task_name=t.get("task_name", ""),
            result=t.get("result"),
            error=t.get("error"),
            created_at=t.get("created_at"),
            started_at=t.get("started_at"),
            completed_at=t.get("completed_at"),
            progress=t.get("progress"),
            metadata=t.get("metadata"),
        )
        for t in tasks
    ]


@router.delete("/scrape/{task_id}", response_model=TaskDeletionResponse)
async def delete_scraping_task(
    task_id: str,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> TaskDeletionResponse:
    """删除抓取任务。

    删除已完成的任务记录。正在运行的任务不能被删除。

    Args:
        task_id: 任务 ID

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 任务不存在，409 任务正在运行
    """
    registry = get_task_registry()
    task_data = registry.get_task_status(task_id)

    if task_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )

    if task_data["status"] == TaskStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="不能删除正在运行的任务",
        )

    deleted = registry.delete_task(task_id)

    if deleted:
        logger.info(f"删除任务: {task_id}")

        audit_log(
            "delete_scraping_task",
            "delete",
            params={"task_id": task_id},
            source="api",
            user=_admin.name,
        )

        return TaskDeletionResponse(message=f"任务 {task_id} 已删除")

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="删除任务失败",
    )


@router.post(
    "/articles/backfill",
    response_model=BackfillSingleUserResponse,
    responses={
        status.HTTP_202_ACCEPTED: {
            "model": ScrapeResponse,
            "description": "批量模式：异步任务已受理",
        }
    },
)
async def backfill_articles(
    request: BackfillRequest,
    _admin: UserDomain = Depends(get_current_admin_user),
) -> JSONResponse | BackfillSingleUserResponse:
    """回溯 X Articles。

    支持两种模式：
    1. 单用户模式：{"username": "xxx", "max_tweets": 200} → 同步返回 200
    2. 批量模式：{"all": true, "max_tweets": 200} → 异步后台任务，返回 202 + task_id
       通过 GET /api/admin/scrape/{task_id} 查询进度和结果。

    注意：每次 API 调用消耗 100 credits，请合理设置 max_tweets。
    """
    # ── 批量模式：后台任务 + 立即返回 task_id ──
    # (注意:此分支不再无条件构造 service——批量模式从未引用过它,
    #  是一处多余构造;_run_backfill_all_async 会自己独立构造自己的实例。
    #  CHG-032 目标 4 清理"多余抓手")
    if request.all:
        registry = get_task_registry()
        task_id = registry.create_task(
            task_name="Article 批量回溯",
            metadata={"mode": "backfill_all", "max_tweets": request.max_tweets},
        )

        asyncio.create_task(
            _run_backfill_all_async(task_id, request.max_tweets),
            name=f"backfill-all-{task_id}",
        )

        logger.info(f"创建 Article 批量回溯任务: {task_id}")

        audit_log(
            "backfill_articles",
            "backfill_all",
            params={"max_tweets": request.max_tweets},
            source="api",
            user=_admin.name,
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"task_id": task_id, "status": "pending"},
        )

    # ── 单用户模式 ──
    username = request.username or ""

    # service 仅单用户模式需要,构造收窄到这里,用完即关闭,CHG-032 目标 4
    service = get_article_fetch_service()
    try:
        result = await service.backfill_articles_for_user(
            username,
            max_tweets=request.max_tweets,
        )
    except Exception as e:
        logger.exception(f"Article 回溯异常: username={username}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ARTICLE_BACKFILL_FAILED,
        )
    finally:
        # 单用户模式无 task_id,context 传端点名+username 供运维定位,A5 加固 4
        await _close_article_fetch_service(service, f" (backfill_articles, username={username})")

    logger.info(f"Article 回溯完成: username={username}, result={result}")

    audit_log(
        "backfill_articles",
        "backfill",
        params={"username": username, "max_tweets": request.max_tweets},
        source="api",
        user=_admin.name,
    )

    return BackfillSingleUserResponse(username=username, result=result)
