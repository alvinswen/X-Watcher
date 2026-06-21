"""MCP Admin 管理工具。

提供 manage_follows、trigger_scrape、get_task_status、manage_scheduler、
batch_summarize、get_follow_accounts_info 六个 Admin 级工具。
"""

import asyncio
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import require_admin
from src.mcp.helpers import (
    error_response,
    parse_datetime,
    parse_datetime_optional,
    resolve_user_list,
    success_response,
)

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册 Admin 相关 MCP 工具。"""

    @mcp.tool()
    async def manage_follows(
        action: str,
        username: str | None = None,
        reason: str | None = None,
        is_active: bool | None = None,
        manual_limit: int | None = None,
        brief_intro: str | None = None,
        include_inactive: bool = False,
    ) -> str:
        """管理平台关注列表（list/add/update/deactivate）。需要管理员权限。

        Args:
            action: 操作类型，可选 "list"、"add"、"update"、"deactivate"
            username: X 用户名（add/update/deactivate 时必填）
            reason: 关注原因（add 时必填，update 时可选）
            is_active: 是否活跃（update 时可选）
            manual_limit: 手动抓取限制数（update 时可选）
            brief_intro: 极简介绍，10 汉字以内（update 时可选）
            include_inactive: list 时是否包含非活跃账号，默认 False
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        if action not in ("list", "add", "update", "deactivate"):
            return error_response(
                f"无效的 action: {action}，可选值: list, add, update, deactivate",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("manage_follows", action)
        if guard_err:
            return guard_err

        try:
            from src.database.async_session import get_async_session_maker
            from src.data_layer.provider import get_follows_repo
            from src.preference.services.scraper_config_service import (
                ScraperConfigService,
            )

            session_maker = get_async_session_maker()

            async with session_maker() as session:
                repo = get_follows_repo(session)
                service = ScraperConfigService(repo)

                if action == "list":
                    follows = await service.get_all_follows(
                        include_inactive=include_inactive
                    )
                    return success_response({
                        "follows": [
                            {
                                "username": f.username,
                                "reason": f.reason,
                                "is_active": f.is_active,
                                "added_at": f.added_at,
                                "added_by": f.added_by,
                                "manual_limit": f.manual_limit,
                                "brief_intro": f.brief_intro,
                                "backfill_status": f.backfill_status,
                            }
                            for f in follows
                        ],
                        "count": len(follows),
                    })

                elif action == "add":
                    if not username:
                        return error_response("添加时 username 必填", "validation")
                    if not reason:
                        return error_response("添加时 reason 必填", "validation")
                    follow = await service.add_scraper_follow(
                        username=username, reason=reason, added_by="mcp_admin"
                    )
                    await session.commit()
                    audit_log("manage_follows", "add", params={"username": username})
                    return success_response({
                        "action": "added",
                        "username": follow.username,
                    })

                elif action == "update":
                    if not username:
                        return error_response("更新时 username 必填", "validation")
                    # 记录变更前状态
                    old_follow = await repo.get_follow_by_username(username)
                    old_values = {
                        "reason": old_follow.reason,
                        "is_active": old_follow.is_active,
                        "manual_limit": old_follow.manual_limit,
                        "brief_intro": old_follow.brief_intro,
                    } if old_follow else None

                    follow = await service.update_follow(
                        username=username,
                        reason=reason,
                        is_active=is_active,
                        manual_limit=manual_limit,
                        brief_intro=brief_intro,
                    )
                    await session.commit()
                    audit_log("manage_follows", "update", params={
                        "username": username,
                        "old": old_values,
                        "new": {"reason": reason, "is_active": is_active, "manual_limit": manual_limit, "brief_intro": brief_intro},
                    })
                    return success_response({
                        "action": "updated",
                        "username": follow.username,
                    })

                elif action == "deactivate":
                    if not username:
                        return error_response("停用时 username 必填", "validation")
                    # 记录变更前状态
                    old_follow = await repo.get_follow_by_username(username)
                    old_active = old_follow.is_active if old_follow else None

                    await service.deactivate_follow(username=username)
                    await session.commit()
                    audit_log("manage_follows", "deactivate", params={
                        "username": username,
                        "old": {"is_active": old_active},
                    })
                    return success_response({
                        "action": "deactivated",
                        "username": username,
                    })

        except Exception as e:
            audit_log("manage_follows", action, result="failure", error=str(e))
            logger.error("manage_follows 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def trigger_scrape(
        usernames: str | None = None,
        limit: int = 100,
        skip_summarization: bool = False,
    ) -> str:
        """手动触发抓取任务。需要管理员权限。

        Args:
            usernames: 要抓取的 X 用户名，逗号分隔。留空则抓取所有活跃账号
            limit: 每个用户的抓取推文数量限制，默认 100
            skip_summarization: 跳过自动摘要生成。设为 true 时抓取后不自动翻译，
                               适用于 Claude Code 接管翻译的场景
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        from src.mcp.security import audit_log, check_scrape_guard

        guard_err = check_scrape_guard()
        if guard_err:
            return guard_err

        try:
            from src.scraper import ScrapingService, TaskRegistry
            from src.scraper.task_registry import TaskStatus

            # 检查是否有任务正在运行（防止重复触发浪费 API 额度）
            registry = TaskRegistry.get_instance()
            running_tasks = registry.get_tasks_by_status(TaskStatus.RUNNING)
            if running_tasks:
                return error_response(
                    f"已有抓取任务正在运行 (task_id={running_tasks[0]['task_id']})，请等待完成后再触发",
                    "rate_limit",
                )

            service = ScrapingService(skip_summarization=skip_summarization)

            user_list = await resolve_user_list(usernames)
            if not user_list:
                return error_response("没有可抓取的账号", "validation")

            # 启动异步抓取任务
            task_id = await service.scrape_users(
                usernames=user_list,
                limit=limit,
            )

            audit_log("trigger_scrape", "scrape", params={"usernames": user_list, "limit": limit, "skip_summarization": skip_summarization})
            msg = "抓取任务已完成（摘要生成已跳过，等待外部翻译）" if skip_summarization else "抓取任务已完成（含摘要生成）"
            return success_response({
                "task_id": task_id,
                "usernames": user_list,
                "limit": limit,
                "skip_summarization": skip_summarization,
                "message": msg,
            })
        except Exception as e:
            audit_log("trigger_scrape", "scrape", result="failure", error=str(e))
            logger.error("trigger_scrape 失败: %s", e, exc_info=True)
            return error_response(f"触发抓取失败: {e}")

    @mcp.tool()
    async def trigger_backfill(
        usernames: str | None = None,
        max_pages: int = 20,
        min_pages: int = 0,
    ) -> str:
        """回溯抓取历史推文，绕过早停机制填补时间线空缺。需要管理员权限。

        与 trigger_scrape 不同，backfill 使用分页迭代逐页抓取，
        仅在单页跳过率 >80% 时停止，适合补齐中间缺失的推文。

        Args:
            usernames: 要回溯的 X 用户名，逗号分隔。留空则回溯所有活跃账号
            max_pages: 每个用户最大抓取页数，默认 20
            min_pages: 最少抓取页数，在此之前不检查跳过率（用于穿透已有推文填补空缺）
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        from src.mcp.security import audit_log, check_scrape_guard

        guard_err = check_scrape_guard()
        if guard_err:
            return guard_err

        try:
            from src.scraper import ScrapingService

            service = ScrapingService()

            user_list = await resolve_user_list(usernames)
            if not user_list:
                return error_response("没有可回溯的账号", "validation")

            results = []
            total_new = 0
            total_fetched = 0
            for username in user_list:
                r = await service.backfill_user(username, max_pages=max_pages, min_pages=min_pages)
                results.append(r)
                total_new += r["new"]
                total_fetched += r["fetched"]

            audit_log(
                "trigger_backfill", "scrape",
                params={"usernames": user_list, "max_pages": max_pages, "min_pages": min_pages},
            )
            return success_response({
                "usernames": user_list,
                "count": len(user_list),
                "max_pages": max_pages,
                "total_fetched": total_fetched,
                "total_new": total_new,
                "results": results,
                "message": f"回溯完成：{len(user_list)} 个账号，新增 {total_new} 条推文",
            })
        except Exception as e:
            audit_log("trigger_backfill", "scrape", result="failure", error=str(e))
            logger.error("trigger_backfill 失败: %s", e, exc_info=True)
            return error_response(f"触发回溯失败: {e}")

    @mcp.tool()
    async def get_task_status(task_id: str) -> str:
        """查询后台任务进度（抓取/摘要等）。需要管理员权限。

        Args:
            task_id: 任务 ID（由 trigger_scrape 等返回）
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        try:
            from src.scraper import TaskRegistry

            registry = TaskRegistry.get_instance()
            status = registry.get_task_status(task_id)
            if status is None:
                return error_response(
                    f"任务 {task_id} 不存在", "not_found"
                )
            return success_response(status)
        except Exception as e:
            logger.error("get_task_status 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def manage_scheduler(
        action: str,
        interval_seconds: int | None = None,
    ) -> str:
        """调度器控制（status/update_interval/enable/disable）。需要管理员权限。

        注意：MCP 进程不运行调度器，此工具仅修改数据库中的调度配置。
        实际调度器在 FastAPI 服务进程中运行，配置更改会在下次调度循环时生效。

        Args:
            action: 操作类型，可选 "status"、"update_interval"、"enable"、"disable"
            interval_seconds: 新的调度间隔（秒），仅 update_interval 时需要
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        if action not in ("status", "update_interval", "enable", "disable"):
            return error_response(
                f"无效的 action: {action}，可选值: status, update_interval, enable, disable",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("manage_scheduler", action)
        if guard_err:
            return guard_err

        try:
            from src.preference.services.schedule_service import (
                ScraperScheduleService,
            )

            service = ScraperScheduleService()

            if action == "status":
                config = await service.get_schedule_config()

                # 查询最近执行记录
                last_execution = None
                try:
                    from src.database.async_session import get_async_session_maker
                    from src.data_layer.provider import get_scheduler_log_repo

                    session_maker = get_async_session_maker()
                    async with session_maker() as session:
                        repo = get_scheduler_log_repo(session)
                        logs = await repo.get_recent_logs(limit=1)
                        if logs:
                            log = logs[0]
                            last_execution = {
                                "executed_at": log.executed_at,
                                "event_type": log.event_type.value,
                                "duration_seconds": log.duration_seconds,
                            }
                except Exception:
                    pass

                return success_response({
                    "action": "status",
                    "config": {
                        "interval_seconds": config.interval_seconds,
                        "is_enabled": config.is_enabled,
                        "next_run_time": config.next_run_time,
                        "updated_at": config.updated_at,
                        "updated_by": config.updated_by,
                    },
                    "last_execution": last_execution,
                    "note": "调度器在 FastAPI 服务中运行，MCP 仅显示/修改配置",
                })

            elif action == "update_interval":
                if interval_seconds is None or interval_seconds < 60:
                    return error_response(
                        "interval_seconds 必填且不能小于 60 秒", "validation"
                    )
                config = await service.update_interval(
                    interval_seconds=interval_seconds, updated_by="mcp_admin"
                )
                audit_log("manage_scheduler", "update_interval", params={"interval_seconds": interval_seconds})
                return success_response({
                    "action": "interval_updated",
                    "interval_seconds": config.interval_seconds,
                })

            elif action == "enable":
                config = await service.enable_schedule(updated_by="mcp_admin")
                audit_log("manage_scheduler", "enable")
                return success_response({
                    "action": "enabled",
                    "is_enabled": config.is_enabled,
                })

            elif action == "disable":
                config = await service.disable_schedule(updated_by="mcp_admin")
                audit_log("manage_scheduler", "disable")
                return success_response({
                    "action": "disabled",
                    "is_enabled": config.is_enabled,
                })

        except Exception as e:
            if action != "status":
                audit_log("manage_scheduler", action, result="failure", error=str(e))
            logger.error("manage_scheduler 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def batch_summarize(
        action: str = "preview",
        since: str | None = None,
        until: str | None = None,
        batch_size: int = 50,
    ) -> str:
        """批量摘要生成（backfill/重置/预览）。需要管理员权限。

        Args:
            action: 操作类型：
                    "preview" - 预览待摘要推文数量（默认）
                    "backfill" - 为缺少摘要的推文批量生成
                    "reset" - 重置指定时间范围的摘要并重新生成
            since: 起始时间，ISO 8601 格式（reset 时必填）
            until: 截止时间，ISO 8601 格式（reset 时必填）
            batch_size: 每批处理数量，默认 50
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        if action not in ("preview", "backfill", "reset"):
            return error_response(
                f"无效的 action: {action}，可选值: preview, backfill, reset",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("batch_summarize", action)
        if guard_err:
            return guard_err

        try:
            from sqlalchemy import func, select

            from src.database.async_session import get_async_session_maker
            from src.scraper.infrastructure.models import TweetOrm
            from src.summarization.infrastructure.models import SummaryOrm

            since_dt = parse_datetime_optional(since)
            until_dt = parse_datetime_optional(until)
            session_maker = get_async_session_maker()

            def _time_conditions():
                """构建时间范围过滤条件。"""
                conds = [SummaryOrm.summary_id == None]  # noqa: E711
                if since_dt:
                    conds.append(TweetOrm.created_at >= since_dt)
                if until_dt:
                    conds.append(TweetOrm.created_at < until_dt)
                return conds

            if action == "preview":
                async with session_maker() as session:
                    result = await session.execute(
                        select(func.count())
                        .select_from(TweetOrm)
                        .outerjoin(
                            SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id
                        )
                        .where(*_time_conditions())
                    )
                    count = result.scalar() or 0
                return success_response({
                    "action": "preview",
                    "pending_count": count,
                })

            elif action == "backfill":
                # 启动后台 backfill 任务
                from src.summarization.services.summarization_queue import (
                    SummarizationPriority,
                    SummarizationQueue,
                )

                queue = SummarizationQueue.get_instance()
                await queue.start()  # 幂等：已启动则立即返回

                # 查询待摘要推文 ID
                async with session_maker() as session:
                    result = await session.execute(
                        select(TweetOrm.tweet_id)
                        .outerjoin(
                            SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id
                        )
                        .where(*_time_conditions())
                        .order_by(TweetOrm.created_at.desc())
                        .limit(batch_size)
                    )
                    tweet_ids = [row[0] for row in result.fetchall()]

                if not tweet_ids:
                    return success_response({
                        "action": "backfill",
                        "message": "没有待摘要的推文",
                        "count": 0,
                    })

                # 入队（队列在 FastAPI 进程中运行，MCP 需要自行启动）
                task_id = await queue.enqueue(
                    tweet_ids,
                    source="mcp_backfill",
                    priority=SummarizationPriority.HIGH,
                )

                audit_log("batch_summarize", "backfill", params={"tweet_count": len(tweet_ids)})
                return success_response({
                    "action": "backfill",
                    "task_id": task_id,
                    "tweet_count": len(tweet_ids),
                    "note": "摘要任务已入队，worker 正在处理",
                })

            elif action == "reset":
                if not since_dt or not until_dt:
                    return error_response(
                        "reset 操作需要 since 和 until 参数", "validation"
                    )

                # 查询范围内推文数
                async with session_maker() as session:
                    result = await session.execute(
                        select(func.count())
                        .select_from(TweetOrm)
                        .where(
                            TweetOrm.created_at >= since_dt,
                            TweetOrm.created_at < until_dt,
                        )
                    )
                    tweet_count = result.scalar() or 0

                audit_log("batch_summarize", "reset", params={"since": since, "until": until, "tweet_count": tweet_count})
                return success_response({
                    "action": "reset_preview",
                    "since": since,
                    "until": until,
                    "tweet_count": tweet_count,
                    "note": "请通过 FastAPI API 执行实际的 reset 操作",
                })

        except (ValueError, TypeError) as e:
            return error_response(f"参数解析失败: {e}", "validation")
        except Exception as e:
            audit_log("batch_summarize", action, result="failure", error=str(e))
            logger.error("batch_summarize 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def get_follow_accounts_info(
        info_type: str = "profiles",
        username: str | None = None,
    ) -> str:
        """获取关注账号详细信息。需要管理员权限。

        Args:
            info_type: 信息类型：
                       "profiles" - 账号 X 平台档案信息
                       "stats" - 账号抓取运行时统计（effective_limit、近期新推文数）
                       "tweet_time_range" - 各账号的推文时间范围
                       "analysis" - 指定账号的抓取结果分析（需要 username 参数）
            username: X 用户名（analysis 类型时必填）
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        if info_type not in ("profiles", "stats", "tweet_time_range", "analysis"):
            return error_response(
                f"无效的 info_type: {info_type}，可选值: profiles, stats, tweet_time_range, analysis",
                "validation",
            )

        try:
            from sqlalchemy import func, select

            from src.database.async_session import get_async_session_maker
            from src.database.models import ScraperFollow
            from src.scraper.infrastructure.models import TweetOrm

            session_maker = get_async_session_maker()

            if info_type == "profiles":
                async with session_maker() as session:
                    from src.database.x_user_profile_model import XUserProfileOrm

                    result = await session.execute(
                        select(
                            XUserProfileOrm.username,
                            XUserProfileOrm.display_name,
                            XUserProfileOrm.description,
                            XUserProfileOrm.followers_count,
                            XUserProfileOrm.following_count,
                            XUserProfileOrm.statuses_count,
                            XUserProfileOrm.updated_at,
                        ).order_by(XUserProfileOrm.username)
                    )
                    rows = result.fetchall()
                    profiles = [
                        {
                            "username": r.username,
                            "display_name": r.display_name,
                            "bio": r.description,
                            "followers_count": r.followers_count,
                            "following_count": r.following_count,
                            "tweet_count": r.statuses_count,
                            "updated_at": r.updated_at,
                        }
                        for r in rows
                    ]
                return success_response({
                    "profiles": profiles,
                    "count": len(profiles),
                })

            elif info_type == "stats":
                async with session_maker() as session:
                    # 获取活跃账号
                    follows_result = await session.execute(
                        select(
                            ScraperFollow.username,
                            ScraperFollow.manual_limit,
                        ).where(ScraperFollow.is_active == True)  # noqa: E712
                    )
                    follows = follows_result.fetchall()

                    stats = []
                    for f in follows:
                        # 最近推文统计
                        count_result = await session.execute(
                            select(func.count())
                            .select_from(TweetOrm)
                            .where(
                                func.lower(TweetOrm.author_username)
                                == f.username.lower()
                            )
                        )
                        total = count_result.scalar() or 0
                        stats.append({
                            "username": f.username,
                            "manual_limit": f.manual_limit,
                            "total_tweets": total,
                        })

                return success_response({"stats": stats, "count": len(stats)})

            elif info_type == "tweet_time_range":
                async with session_maker() as session:
                    follows_result = await session.execute(
                        select(ScraperFollow.username).where(
                            ScraperFollow.is_active == True  # noqa: E712
                        )
                    )
                    usernames = [r.username for r in follows_result.fetchall()]

                    ranges = []
                    for uname in usernames:
                        result = await session.execute(
                            select(
                                func.min(TweetOrm.created_at).label("earliest"),
                                func.max(TweetOrm.created_at).label("latest"),
                                func.count().label("count"),
                            ).where(
                                func.lower(TweetOrm.author_username)
                                == uname.lower()
                            )
                        )
                        row = result.first()
                        ranges.append({
                            "username": uname,
                            "earliest_tweet_at": row.earliest if row else None,
                            "latest_tweet_at": row.latest if row else None,
                            "tweet_count": row.count if row else 0,
                        })

                return success_response({
                    "time_ranges": ranges,
                    "count": len(ranges),
                })

            elif info_type == "analysis":
                if not username:
                    return error_response(
                        "analysis 类型需要 username 参数", "validation"
                    )

                from datetime import timedelta

                async with session_maker() as session:
                    # 按 12 小时周期统计最近 14 个周期
                    now = datetime.now(timezone.utc)
                    periods_data = []
                    for i in range(14):
                        end = now - timedelta(hours=12 * i)
                        start = end - timedelta(hours=12)
                        result = await session.execute(
                            select(func.count())
                            .select_from(TweetOrm)
                            .where(
                                func.lower(TweetOrm.author_username)
                                == username.lower(),
                                TweetOrm.created_at >= start,
                                TweetOrm.created_at < end,
                            )
                        )
                        count = result.scalar() or 0
                        periods_data.append({
                            "period_start": start,
                            "period_end": end,
                            "new_tweets": count,
                        })

                return success_response({
                    "username": username,
                    "interval_hours": 12,
                    "periods": periods_data,
                })

        except Exception as e:
            logger.error("get_follow_accounts_info 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")
