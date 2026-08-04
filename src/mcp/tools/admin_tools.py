"""MCP Admin 管理工具。

提供 manage_follows、trigger_scrape、trigger_backfill、get_task_status、
get_follow_accounts_info 五个 Admin 级工具。
"""

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import require_admin
from src.mcp.helpers import (
    error_response,
    resolve_user_list,
    success_response,
)

logger = logging.getLogger(__name__)


async def _close_scraping_service(service: Any, context: str = "") -> None:
    """关闭抓取服务连接资源(CHG-032 目标 4)。

    关闭失败仅记录警告日志,不覆盖或掩盖调用方已经产生的抓取/回溯结果
    (与 ``admin.py`` 的同名 helper 语义一致)。

    ⚠️ 本函数与 ``src/api/routes/admin.py`` 里的同名 helper 是**两份独立实现**,
    不要合并成一个跨文件共享函数(CHG-032 A5 加固 3)。原因:本文件把 ``ScrapingService``
    等 scraper 符号一律做函数体内局部 import、该 helper 用 ``Any`` 标注;而 ``admin.py``
    在模块顶部固定 import ``ScrapingService`` 并用作精确类型。本文件**没有**
    ``from __future__ import annotations``,若为"统一成精确类型"而在模块顶部新增
    scraper import,该模块级函数标注会在模块加载期(MCP server 启动阶段)就地求值,
    一旦 import 缺失即抛 NameError。故这两份看似重复的 helper 类型标注不同是有意为之,
    不要合并、不要"顺手统一"(§ 五施工注意事项第 2 条讲"怎么做",本处 docstring 是把
    理由留在代码里给后人看)。

    Args:
        service: 待关闭的抓取服务实例(用 Any 标注,见上方说明)
        context: 可选的调用来源标签(如 " (tool=trigger_scrape)"),拼进关闭失败的告警
            文案,便于多任务并发时运维一眼看出这条告警由哪个工具触发(CHG-032 A5 加固 4)
    """
    try:
        await service.close()
    except Exception as e:
        logger.warning(f"关闭 ScrapingService 连接失败{context}: {e}")


def register(mcp: FastMCP) -> None:
    """注册 Admin 相关 MCP 工具。"""

    @mcp.tool()
    async def manage_follows(  # type: ignore[return]  # action 已校验为有限枚举，分支穷尽
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
            from src.preference.services.scraper_config_service import (
                ScraperConfigService,
            )

            repo = get_follows_repo()
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
                if manual_limit is not None and not (0 <= manual_limit <= 1000):
                    return error_response(
                        "manual_limit 必须在 0-1000 之间（0 表示清除手动设置恢复自动计算）",
                        "validation",
                    )
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

        若账号配置了手动抓取上限（manual_limit），该配置优先于 limit 参数生效。
        服务端启用增量搜索抓取时，本工具改走按组增量查询路径（由服务端配置决定，
        调用方式不变），此时 manual_limit 不再参与判停。

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
            from src.scraper.scheduled_job import resolve_manual_limits
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
            try:
                user_list = await resolve_user_list(usernames)
                if not user_list:
                    return error_response("没有可抓取的账号", "validation")

                # 解析本次实际生效的 manual_limit(服务层共享的同一份实现,CHG-031 目标 1):
                # 此处提前调用一次,既传给 scrape_users(避免其内部重复查询),也用于
                # 下方审计日志留痕(运维需要知道这次到底有没有生效)
                manual_limits = await resolve_manual_limits(user_list)

                # 启动异步抓取任务
                task_id = await service.scrape_users(
                    usernames=user_list,
                    limit=limit,
                    manual_limits=manual_limits,
                )

                audit_log(
                    "trigger_scrape",
                    "scrape",
                    params={
                        "usernames": user_list,
                        "limit": limit,
                        "manual_limits": manual_limits or None,
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
            finally:
                # 用完关闭连接(含"没有可抓取账号"提前返回的情形),CHG-032 目标 4
                # (context 传工具名,A5 加固 4)
                await _close_scraping_service(service, " (tool=trigger_scrape)")
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
            try:
                user_list = await resolve_user_list(usernames)
                if not user_list:
                    return error_response("没有可回溯的账号", "validation")

                results = []
                total_new = 0
                total_fetched = 0
                for username in user_list:
                    r = await service.backfill_user(
                        username, max_pages=max_pages, min_pages=min_pages
                    )
                    results.append(r)
                    total_new += r["new"]
                    total_fetched += r["fetched"]

                audit_log(
                    "trigger_backfill",
                    "scrape",
                    params={
                        "usernames": user_list,
                        "max_pages": max_pages,
                        "min_pages": min_pages,
                    },
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
            finally:
                # 整批账号处理完(无论中途是否有账号异常导致循环中断)才关闭一次,
                # Q2;本循环无逐账号 try/except(Loop-1 发现 2,本包不修复该差异),
                # 故必须用 try/finally 包裹"构造→守卫检查→循环"整体,不能只在
                # 循环代码块之后追加一行 close() 调用——那样循环中途抛异常时
                # close() 永远不会被执行到
                # (context 传工具名,A5 加固 4)
                await _close_scraping_service(service, " (tool=trigger_backfill)")
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
    async def get_follow_accounts_info(  # type: ignore[return]  # info_type 已校验为有限枚举，分支穷尽
        info_type: str = "profiles",
        username: str | None = None,
    ) -> str:
        """获取关注账号详细信息。需要管理员权限。

        Args:
            info_type: 信息类型：
                       "profiles" - 账号 X 平台档案信息
                       "stats" - 账号抓取统计（manual_limit 手动上限、total_tweets 系统内推文总数）
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
            from src.preference.services.scraper_config_service import (
                get_tweet_time_ranges,
            )

            if info_type == "profiles":
                # 档案走 profile 门面(file 模式忽略 session)。领域模型携 fetched_at
                # (无 updated_at 列),沿用 router 既有约定以 fetched_at 充 updated_at 键;
                # 保 username 升序(逐档案排序,复刻原 order_by(username))。
                repo = get_profile_repo()
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
                # 活跃账号走 follows 门面;每账号总推文走共享的 tweet_time_range
                # 实现(REST/MCP 两处共用,CHG-032 目标 2)。
                follows = await get_follows_repo().get_all_follows(
                    include_inactive=False
                )
                usernames = [f.username for f in follows]
                ranges_map = await get_tweet_time_ranges(usernames)

                stats = [
                    {
                        "username": f.username,
                        "manual_limit": f.manual_limit,
                        "total_tweets": ranges_map[f.username][2],
                    }
                    for f in follows
                ]
                return success_response({"stats": stats, "count": len(stats)})

            elif info_type == "tweet_time_range":
                # 活跃账号 min/max/count 走共享的 tweet_time_range 实现
                # (REST/MCP 两处共用,CHG-032 目标 2)。
                follows = await get_follows_repo().get_all_follows(
                    include_inactive=False
                )
                usernames = [f.username for f in follows]
                ranges_map = await get_tweet_time_ranges(usernames)

                ranges = [
                    {
                        "username": u,
                        "earliest_tweet_at": ranges_map[u][0],
                        "latest_tweet_at": ranges_map[u][1],
                        "tweet_count": ranges_map[u][2],
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
                windows = await get_scraper_stats_repo().period_analysis(
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
