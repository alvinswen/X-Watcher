"""MCP Topic 管理工具。

提供 list_topics、get_topic、manage_topic、manage_topic_accounts、get_topic_summary
五个 MCP 工具，映射到 TopicService 和 TopicSummaryService。
"""

import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.helpers import error_response, success_response

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
                    return success_response({
                        "action": "created",
                        "topic": topic.model_dump(),
                    })

                elif action == "update":
                    if topic_id is None:
                        return error_response(
                            "更新主题时 topic_id 参数必填", "validation"
                        )
                    topic = await service.update_topic(
                        session, topic_id=topic_id, name=name, description=description
                    )
                    if not topic:
                        return error_response(
                            f"主题 ID {topic_id} 不存在", "not_found"
                        )
                    return success_response({
                        "action": "updated",
                        "topic": topic.model_dump(),
                    })

                elif action == "delete":
                    if topic_id is None:
                        return error_response(
                            "删除主题时 topic_id 参数必填", "validation"
                        )
                    deleted = await service.delete_topic(session, topic_id=topic_id)
                    if not deleted:
                        return error_response(
                            f"主题 ID {topic_id} 不存在", "not_found"
                        )
                    return success_response({
                        "action": "deleted",
                        "topic_id": topic_id,
                    })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
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
                    return success_response({
                        "action": "removed",
                        "removed": removed,
                        "not_found": not_found,
                    })

                elif action == "set":
                    accounts = await service.set_accounts(
                        session, topic_id, username_list
                    )
                    return success_response({
                        "action": "set",
                        "accounts": [a.model_dump() for a in accounts],
                        "count": len(accounts),
                    })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            logger.error("manage_topic_accounts 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")

    @mcp.tool()
    async def get_topic_summary(
        topic_id: int,
        action: str = "latest",
        time_span_hours: int = 24,
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
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
        """
        if action not in ("latest", "create", "list"):
            return error_response(
                f"无效的 action: {action}，可选值: latest, create, list",
                "validation",
            )

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
                    deadline = datetime.now(timezone.utc)
                    task = await summary_service.create_and_execute_task(
                        session=session,
                        session_factory=session_maker,
                        topic_id=topic_id,
                        time_span_hours=time_span_hours,
                        deadline=deadline,
                        tz_offset=tz_offset,
                    )
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
            logger.error("get_topic_summary 失败: %s", e, exc_info=True)
            return error_response(f"操作失败: {e}")
