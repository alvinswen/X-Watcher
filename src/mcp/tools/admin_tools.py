"""MCP Admin 管理工具。

提供 manage_follows、trigger_scrape、trigger_backfill、get_task_status、
get_follow_accounts_info 五个 Admin 级工具。
"""

import logging

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import require_admin
from src.mcp.helpers import (
    error_response,
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
            from src.data_layer.provider import get_follows_repo
            from src.database.async_session import get_async_session_maker
            from src.preference.services.scraper_config_service import (
                ScraperConfigService,
            )

            session_maker = get_async_session_maker()

            async with session_maker() as session:
                repo = get_follows_repo(session)
                service = ScraperConfigService(repo)

                if action == "list":
                    follows = await service.get_all_follows(include_inactive=include_inactive)
                    return success_response(
                        {
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
                        }
                    )

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
                    return success_response(
                        {
                            "action": "added",
                            "username": follow.username,
                        }
                    )

                elif action == "update":
                    if not username:
                        return error_response("更新时 username 必填", "validation")
                    # 记录变更前状态
                    old_follow = await repo.get_follow_by_username(username)
                    old_values = (
                        {
                            "reason": old_follow.reason,
                            "is_active": old_follow.is_active,
                            "manual_limit": old_follow.manual_limit,
                            "brief_intro": old_follow.brief_intro,
                        }
                        if old_follow
                        else None
                    )

                    follow = await service.update_follow(
                        username=username,
                        reason=reason,
                        is_active=is_active,
                        manual_limit=manual_limit,
                        brief_intro=brief_intro,
                    )
                    await session.commit()
                    audit_log(
                        "manage_follows",
                        "update",
                        params={
                            "username": username,
                            "old": old_values,
                            "new": {
                                "reason": reason,
                                "is_active": is_active,
                                "manual_limit": manual_limit,
                                "brief_intro": brief_intro,
                            },
                        },
                    )
                    return success_response(
                        {
                            "action": "updated",
                            "username": follow.username,
                        }
                    )

                elif action == "deactivate":
                    if not username:
                        return error_response("停用时 username 必填", "validation")
                    # 记录变更前状态
                    old_follow = await repo.get_follow_by_username(username)
                    old_active = old_follow.is_active if old_follow else None

                    await service.deactivate_follow(username=username)
                    await session.commit()
                    audit_log(
                        "manage_follows",
                        "deactivate",
                        params={
                            "username": username,
                            "old": {"is_active": old_active},
                        },
                    )
                    return success_response(
                        {
                            "action": "deactivated",
                            "username": username,
                        }
                    )

        except Exception as e:
            audit_log("manage_follows", action, result="failure", error=str(e))
            logger.error("manage_follows 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def trigger_scrape(
        usernames: str | None = None,
        limit: int = 100,
    ) -> str:
        """手动触发抓取任务。需要管理员权限。

        Args:
            usernames: 要抓取的 X 用户名，逗号分隔。留空则抓取所有活跃账号
            limit: 每个用户的抓取推文数量限制，默认 100
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        from src.mcp.security import audit_log, check_action_guard, check_scrape_guard

        guard_err = check_scrape_guard()
        if guard_err:
            return guard_err
        action_guard_err = check_action_guard("trigger_scrape", "scrape")
        if action_guard_err:
            return action_guard_err

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

            service = ScrapingService()

            user_list = await resolve_user_list(usernames)
            if not user_list:
                return error_response("没有可抓取的账号", "validation")

            # 启动异步抓取任务
            task_id = await service.scrape_users(
                usernames=user_list,
                limit=limit,
            )

            audit_log(
                "trigger_scrape",
                "scrape",
                params={
                    "usernames": user_list,
                    "limit": limit,
                },
            )
            return success_response(
                {
                    "task_id": task_id,
                    "usernames": user_list,
                    "limit": limit,
                    "message": "抓取任务已完成",
                }
            )
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

        from src.mcp.security import audit_log, check_action_guard, check_scrape_guard

        guard_err = check_scrape_guard()
        if guard_err:
            return guard_err
        action_guard_err = check_action_guard("trigger_backfill", "scrape")
        if action_guard_err:
            return action_guard_err

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
                "trigger_backfill",
                "scrape",
                params={"usernames": user_list, "max_pages": max_pages, "min_pages": min_pages},
            )
            return success_response(
                {
                    "usernames": user_list,
                    "count": len(user_list),
                    "max_pages": max_pages,
                    "total_fetched": total_fetched,
                    "total_new": total_new,
                    "results": results,
                    "message": f"回溯完成：{len(user_list)} 个账号，新增 {total_new} 条推文",
                }
            )
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
                return error_response(f"任务 {task_id} 不存在", "not_found")
            return success_response(status)
        except Exception as e:
            logger.error("get_task_status 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

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
            from src.data_layer.provider import (
                get_follows_repo,
                get_profile_repo,
                get_scraper_stats_repo,
            )
            from src.database.async_session import get_async_session_maker

            session_maker = get_async_session_maker()

            if info_type == "profiles":
                # 档案走 profile 门面(file 模式忽略 session)。领域模型携 fetched_at
                # (无 updated_at 列),沿用 router 既有约定以 fetched_at 充 updated_at 键;
                # 保 username 升序(逐档案排序,复刻原 order_by(username))。
                async with session_maker() as session:
                    repo = get_profile_repo(session)
                    domain_profiles = await repo.get_all_profiles()
                domain_profiles = sorted(domain_profiles, key=lambda p: p.username)
                profiles = [
                    {
                        "username": p.username,
                        "display_name": p.display_name,
                        "bio": p.description,
                        "followers_count": p.followers_count,
                        "following_count": p.following_count,
                        "tweet_count": p.statuses_count,
                        "updated_at": p.fetched_at,
                    }
                    for p in domain_profiles
                ]
                return success_response(
                    {
                        "profiles": profiles,
                        "count": len(profiles),
                    }
                )

            elif info_type == "stats":
                # 活跃账号走 follows 门面;每账号总推文走 tweet 聚合门面
                # tweet_time_range 的 count 槽(大小写不敏感 lower 键匹配)。
                async with session_maker() as session:
                    follows = await get_follows_repo(session).get_all_follows(
                        include_inactive=False
                    )
                    usernames = [f.username for f in follows]
                    ranges = (
                        await get_scraper_stats_repo(session).tweet_time_range(usernames)
                        if usernames
                        else {}
                    )

                stats = [
                    {
                        "username": f.username,
                        "manual_limit": f.manual_limit,
                        "total_tweets": (
                            ranges[f.username.lower()][2] if f.username.lower() in ranges else 0
                        ),
                    }
                    for f in follows
                ]
                return success_response({"stats": stats, "count": len(stats)})

            elif info_type == "tweet_time_range":
                # 活跃账号 min/max/count 走 tweet 聚合门面(lower 键匹配)。
                async with session_maker() as session:
                    follows = await get_follows_repo(session).get_all_follows(
                        include_inactive=False
                    )
                    usernames = [f.username for f in follows]
                    rows = (
                        await get_scraper_stats_repo(session).tweet_time_range(usernames)
                        if usernames
                        else {}
                    )

                ranges = [
                    {
                        "username": u,
                        "earliest_tweet_at": (rows[u.lower()][0] if u.lower() in rows else None),
                        "latest_tweet_at": (rows[u.lower()][1] if u.lower() in rows else None),
                        "tweet_count": (rows[u.lower()][2] if u.lower() in rows else 0),
                    }
                    for u in usernames
                ]
                return success_response(
                    {
                        "time_ranges": ranges,
                        "count": len(ranges),
                    }
                )

            elif info_type == "analysis":
                if not username:
                    return error_response("analysis 类型需要 username 参数", "validation")

                # 逐周期 count 走 tweet 聚合门面(12h × 14 周期)。门面正序(最早在前),
                # 此处 reverse 成最近在前,复刻原 i=0 最新逐周期追加的 DESC 输出。
                async with session_maker() as session:
                    windows = await get_scraper_stats_repo(session).period_analysis(
                        username, 12, 14
                    )

                periods_data = [
                    {
                        "period_start": period_start,
                        "period_end": period_end,
                        "new_tweets": count,
                    }
                    for (period_start, period_end, count) in reversed(windows)
                ]
                return success_response(
                    {
                        "username": username,
                        "interval_hours": 12,
                        "periods": periods_data,
                    }
                )

        except Exception as e:
            logger.error("get_follow_accounts_info 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")
