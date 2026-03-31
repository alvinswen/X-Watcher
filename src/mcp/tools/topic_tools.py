"""MCP Topic 管理工具。

提供 list_topics、get_topic、manage_topic、manage_topic_accounts、get_topic_summary、
get_topic_tweets_for_summary、save_topic_summary 七个 MCP 工具，
映射到 TopicService 和 TopicSummaryService。
"""

import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, parse_datetime_optional, success_response

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册 Topic 相关 MCP 工具。"""

    @mcp.tool()
    async def list_topics() -> str:
        """列出所有监控主题及账号数量。

        返回主题列表，每个主题包含 id、名称、描述、关联账号数量等信息。
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_service import TopicService

            session_maker = get_async_session_maker()
            service = TopicService()

            async with session_maker() as session:
                topics = await service.list_topics(session)
                return success_response({
                    "topics": [t.model_dump() for t in topics],
                    "count": len(topics),
                })
        except Exception as e:
            logger.error("list_topics 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def get_topic(topic_id: int) -> str:
        """获取主题详情及关联账号列表。

        Args:
            topic_id: 主题 ID
        """
        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_service import TopicService

            session_maker = get_async_session_maker()
            service = TopicService()

            async with session_maker() as session:
                detail = await service.get_topic(session, topic_id)
                if not detail:
                    return error_response(
                        f"主题 ID {topic_id} 不存在", "not_found"
                    )
                return success_response(detail.model_dump())
        except Exception as e:
            logger.error("get_topic 失败: %s", e, exc_info=True)
            return error_response(f"查询失败: {e}")

    @mcp.tool()
    async def manage_topic(
        action: str,
        name: str | None = None,
        description: str | None = None,
        topic_id: int | None = None,
    ) -> str:
        """创建/更新/删除监控主题。

        Args:
            action: 操作类型，可选 "create"、"update"、"delete"
            name: 主题名称（create 时必填，update 时可选）
            description: 主题描述（create/update 时可选）
            topic_id: 主题 ID（update/delete 时必填）
        """
        if action not in ("create", "update", "delete"):
            return error_response(
                f"无效的 action: {action}，可选值: create, update, delete",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("manage_topic", action)
        if guard_err:
            return guard_err

        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_service import TopicService

            session_maker = get_async_session_maker()
            service = TopicService()

            async with session_maker() as session:
                if action == "create":
                    if not name:
                        return error_response(
                            "创建主题时 name 参数必填", "validation"
                        )
                    topic = await service.create_topic(
                        session, name=name, description=description
                    )
                    audit_log("manage_topic", "create", params={"name": name})
                    return success_response({
                        "action": "created",
                        "topic": topic.model_dump(),
                    })

                elif action == "update":
                    if topic_id is None:
                        return error_response(
                            "更新主题时 topic_id 参数必填", "validation"
                        )
                    # 记录变更前状态
                    old_topic = await service.get_topic(session, topic_id)
                    old_values = {
                        "name": old_topic.name,
                        "description": old_topic.description,
                    } if old_topic else None

                    topic = await service.update_topic(
                        session, topic_id=topic_id, name=name, description=description
                    )
                    if not topic:
                        return error_response(
                            f"主题 ID {topic_id} 不存在", "not_found"
                        )
                    audit_log("manage_topic", "update", params={
                        "topic_id": topic_id,
                        "old": old_values,
                        "new": {"name": name, "description": description},
                    })
                    return success_response({
                        "action": "updated",
                        "topic": topic.model_dump(),
                    })

                elif action == "delete":
                    if topic_id is None:
                        return error_response(
                            "删除主题时 topic_id 参数必填", "validation"
                        )
                    # 记录删除前状题信息
                    old_topic = await service.get_topic(session, topic_id)
                    old_values = {
                        "name": old_topic.name,
                        "description": old_topic.description,
                    } if old_topic else None

                    deleted = await service.delete_topic(session, topic_id=topic_id)
                    if not deleted:
                        return error_response(
                            f"主题 ID {topic_id} 不存在", "not_found"
                        )
                    audit_log("manage_topic", "delete", params={
                        "topic_id": topic_id,
                        "deleted_topic": old_values,
                    })
                    return success_response({
                        "action": "deleted",
                        "topic_id": topic_id,
                    })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            audit_log("manage_topic", action, result="failure", error=str(e))
            logger.error("manage_topic 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def manage_topic_accounts(
        topic_id: int,
        action: str,
        usernames: str,
    ) -> str:
        """管理主题关联的 X 账号（添加/移除/批量设置）。

        Args:
            topic_id: 主题 ID
            action: 操作类型，可选 "add"、"remove"、"set"（set 为替换模式）
            usernames: X 账号用户名，多个用逗号分隔，如 "elonmusk,vitalikbuterin"
        """
        if action not in ("add", "remove", "set"):
            return error_response(
                f"无效的 action: {action}，可选值: add, remove, set",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("manage_topic_accounts", action)
        if guard_err:
            return guard_err

        username_list = [u.strip() for u in usernames.split(",") if u.strip()]
        if not username_list:
            return error_response("usernames 不能为空", "validation")

        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_service import TopicService

            session_maker = get_async_session_maker()
            service = TopicService()

            async with session_maker() as session:
                if action == "add":
                    results = []
                    errors = []
                    for username in username_list:
                        try:
                            account = await service.add_account(
                                session, topic_id, username
                            )
                            results.append(account.model_dump())
                        except ValueError as e:
                            errors.append({"username": username, "error": str(e)})
                    audit_log("manage_topic_accounts", "add", params={"topic_id": topic_id, "usernames": username_list})
                    return success_response({
                        "action": "added",
                        "added": results,
                        "errors": errors,
                    })

                elif action == "remove":
                    removed = []
                    not_found = []
                    for username in username_list:
                        ok = await service.remove_account(
                            session, topic_id, username
                        )
                        if ok:
                            removed.append(username)
                        else:
                            not_found.append(username)
                    audit_log("manage_topic_accounts", "remove", params={"topic_id": topic_id, "usernames": username_list})
                    return success_response({
                        "action": "removed",
                        "removed": removed,
                        "not_found": not_found,
                    })

                elif action == "set":
                    accounts = await service.set_accounts(
                        session, topic_id, username_list
                    )
                    audit_log("manage_topic_accounts", "set", params={"topic_id": topic_id, "usernames": username_list})
                    return success_response({
                        "action": "set",
                        "accounts": [a.model_dump() for a in accounts],
                        "count": len(accounts),
                    })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            audit_log("manage_topic_accounts", action, result="failure", error=str(e))
            logger.error("manage_topic_accounts 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def get_topic_summary(
        topic_id: int,
        action: str = "latest",
        time_span_hours: int = 24,
        deadline: str | None = None,
        tz_offset: int = -480,
    ) -> str:
        """获取或创建主题的 AI 聚合摘要。

        Args:
            topic_id: 主题 ID
            action: 操作类型。
                    "latest" - 获取最新已完成的摘要（默认）
                    "create" - 创建新的摘要任务
                    "list" - 列出该主题的所有摘要任务
            time_span_hours: 创建摘要时的时间跨度（小时），默认 24
            deadline: 摘要覆盖时段的截止时间，ISO 8601 格式。
                      默认为当前时间。配合 time_span_hours 确定覆盖区间
                      [deadline - time_span_hours, deadline]
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
        """
        if action not in ("latest", "create", "list"):
            return error_response(
                f"无效的 action: {action}，可选值: latest, create, list",
                "validation",
            )

        from src.mcp.security import audit_log, check_action_guard

        guard_err = check_action_guard("get_topic_summary", action)
        if guard_err:
            return guard_err

        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_summary_service import TopicSummaryService

            session_maker = get_async_session_maker()
            summary_service = TopicSummaryService.get_instance()

            async with session_maker() as session:
                if action == "latest":
                    task = await summary_service.get_latest_summary(
                        session, topic_id
                    )
                    if not task:
                        return success_response({
                            "message": "该主题尚无已完成的摘要",
                            "topic_id": topic_id,
                        })
                    return success_response(task.model_dump())

                elif action == "create":
                    deadline_dt = parse_datetime_optional(deadline)
                    if deadline_dt is None:
                        deadline_dt = datetime.now(timezone.utc)
                    task = await summary_service.create_and_execute_task(
                        session=session,
                        session_factory=session_maker,
                        topic_id=topic_id,
                        time_span_hours=time_span_hours,
                        deadline=deadline_dt,
                        tz_offset=tz_offset,
                    )
                    audit_log("get_topic_summary", "create", params={"topic_id": topic_id, "time_span_hours": time_span_hours})
                    return success_response({
                        "message": "摘要任务已创建并开始执行",
                        "task": task.model_dump(),
                    })

                elif action == "list":
                    tasks = await summary_service.list_tasks(
                        session, topic_id=topic_id
                    )
                    return success_response({
                        "tasks": [t.model_dump() for t in tasks],
                        "count": len(tasks),
                    })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            if action == "create":
                audit_log("get_topic_summary", action, result="failure", error=str(e))
            logger.error("get_topic_summary 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def get_topic_tweets_for_summary(
        topic_id: int,
        time_span_hours: int = 24,
        deadline: str | None = None,
        tz_offset: int = -480,
    ) -> str:
        """获取主题推文数据和默认 prompt，供 Claude Code 生成摘要。需要管理员权限。

        返回格式化的推文内容、账号信息和构建好的默认提示词，
        Claude Code 可直接使用 default_prompt 生成摘要报告。

        Args:
            topic_id: 主题 ID
            time_span_hours: 时间跨度（小时），默认 24
            deadline: 覆盖时段截止时间，ISO 8601 格式。默认为当前时间
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
        """
        from src.mcp.auth import require_admin

        perm_err = require_admin()
        if perm_err:
            return perm_err

        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_summary_service import TopicSummaryService

            session_maker = get_async_session_maker()
            summary_service = TopicSummaryService.get_instance()

            deadline_dt = parse_datetime_optional(deadline)
            if deadline_dt is None:
                deadline_dt = datetime.now(timezone.utc)

            async with session_maker() as session:
                data = await summary_service.prepare_summary_data(
                    session=session,
                    topic_id=topic_id,
                    time_span_hours=time_span_hours,
                    deadline=deadline_dt,
                    tz_offset=tz_offset,
                )

                if "default_prompt" in data:
                    data["note"] = "直接使用 default_prompt 生成摘要，或基于其中的推文数据用自己的判断力撰写报告"

                return success_response(data)

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            logger.error("get_topic_tweets_for_summary 失败: %s", e, exc_info=True)
            return error_response(f"获取主题推文失败: {e}")

    @mcp.tool()
    async def save_topic_summary(
        topic_id: int,
        content: str,
        time_span_hours: int = 24,
        deadline: str | None = None,
        tz_offset: int = -480,
        tweet_count: int = 0,
        account_count: int = 0,
    ) -> str:
        """保存 Claude Code 生成的主题摘要到数据库。需要管理员权限。

        创建一条已完成的摘要任务记录，标记为 claude_code 生成。
        通常在调用 get_topic_tweets_for_summary 并生成摘要后使用。

        Args:
            topic_id: 主题 ID
            content: 摘要 Markdown 内容
            time_span_hours: 时间跨度（小时），默认 24
            deadline: 覆盖时段截止时间，ISO 8601 格式。默认为当前时间
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
            tweet_count: 摘要覆盖的推文数量
            account_count: 摘要覆盖的账号数量
        """
        from src.mcp.auth import require_admin
        from src.mcp.security import audit_log

        perm_err = require_admin()
        if perm_err:
            return perm_err

        if not content or not content.strip():
            return error_response("content 不能为空", "validation")

        try:
            from src.database.async_session import get_async_session_maker
            from src.topic.services.topic_summary_service import TopicSummaryService

            session_maker = get_async_session_maker()
            summary_service = TopicSummaryService.get_instance()

            deadline_dt = parse_datetime_optional(deadline)
            if deadline_dt is None:
                deadline_dt = datetime.now(timezone.utc)

            async with session_maker() as session:
                task_domain = await summary_service.save_external_summary(
                    session=session,
                    topic_id=topic_id,
                    content=content.strip(),
                    time_span_hours=time_span_hours,
                    deadline=deadline_dt,
                    tz_offset=tz_offset,
                    tweet_count=tweet_count,
                    account_count=account_count,
                )

            audit_log(
                "save_topic_summary", "save",
                params={
                    "topic_id": topic_id,
                    "tweet_count": tweet_count,
                    "account_count": account_count,
                },
            )

            return success_response({
                "action": "saved",
                "task_id": task_domain.id,
                "topic_id": topic_id,
                "topic_name": task_domain.topic_name,
                "tweet_count": tweet_count,
                "account_count": account_count,
                "llm_provider": "claude_code",
            })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            audit_log("save_topic_summary", "save", result="failure", error=str(e))
            logger.error("save_topic_summary 失败: %s", e, exc_info=True)
            return error_response(f"保存摘要失败: {e}")
