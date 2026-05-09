"""MCP Topic 管理工具。

提供 list_topics、get_topic、manage_topic、manage_topic_accounts、get_topic_summary、
get_topic_tweets_for_summary、save_topic_summary 七个 MCP 工具，
映射到 TopicService 和 TopicSummaryService。
"""

import json
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
        since: str | None = None,
        until: str | None = None,
        review_mode: bool = False,
    ) -> str:
        """获取主题推文数据和默认 prompt，供 Claude Code 生成摘要或综述。需要管理员权限。

        返回格式化的推文内容、账号信息和构建好的默认提示词，
        Claude Code 可直接使用 default_prompt 生成报告。

        时间窗口规则：
        - 若 ``since`` 或 ``until`` 任一为非空，按 since/until 区间取数（任意区间，含主题综述场景）；
        - 否则沿用 ``deadline`` 与 ``time_span_hours`` 计算 [deadline - N 小时, deadline]。

        Args:
            topic_id: 主题 ID
            time_span_hours: 时间跨度（小时），默认 24（仅 since/until 都为空时生效）
            deadline: 覆盖时段截止时间，ISO 8601 格式。默认为当前时间
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
            since: 综述起始时间（含），ISO 8601 格式；与 until 配合任选其一即生效
            until: 综述截止时间（不含），ISO 8601 格式；省略则取当前时间
            review_mode: 启用主题综述模式——使用带出处引用的 prompt 模板，
                         且推文行会显式注入 tweet_id 供 LLM 引用。默认 False（日报式摘要）
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

            since_dt = parse_datetime_optional(since)
            until_dt = parse_datetime_optional(until)

            async with session_maker() as session:
                data = await summary_service.prepare_summary_data(
                    session=session,
                    topic_id=topic_id,
                    time_span_hours=time_span_hours,
                    deadline=deadline_dt,
                    tz_offset=tz_offset,
                    since=since_dt,
                    until=until_dt,
                    review_mode=review_mode,
                )

                if "default_prompt" in data:
                    if review_mode:
                        data["note"] = (
                            "综述模式：直接使用 default_prompt 生成观点综述，"
                            "并按 prompt 末尾要求附上 ```observations 代码块（机器读取）。"
                            "保存时把解析后的 observations 列表传给 save_topic_summary。"
                            "校验提示：observations 中每个 source_tweet_id 必须出现在 allowed_tweet_ids 中。"
                        )
                    else:
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
        observations: str | list | None = None,
        review_window_since: str | None = None,
        review_window_until: str | None = None,
        review_kind: str = "topic_summary",
    ) -> str:
        """保存 Claude Code 生成的主题摘要/综述到数据库。需要管理员权限。

        创建一条已完成的摘要任务记录，标记为 claude_code 生成。
        通常在调用 get_topic_tweets_for_summary 并生成摘要后使用。

        若提供 observations / review_window_* / review_kind 任一字段，会被打包写入
        ``topic_summaries.metadata_json``（JSON 列），供后续展示/校验使用；
        默认全为空，与既有 /topic-summary 行为完全一致。

        Args:
            topic_id: 主题 ID
            content: 摘要 Markdown 内容
            time_span_hours: 时间跨度（小时），默认 24
            deadline: 覆盖时段截止时间，ISO 8601 格式。默认为当前时间
            tz_offset: 时区偏移（分钟），UTC+8 为 -480。默认 -480
            tweet_count: 摘要覆盖的推文数量
            account_count: 摘要覆盖的账号数量
            observations: JSON 字符串，数组形式，每项形如
                ``{"idx": 1, "text": "...", "source_tweet_ids": ["..."]}``。
                用于 /topic-review 等综述场景，留下"观点 ↔ 出处"机器可读映射。
            review_window_since: 综述时间窗口起始（ISO 8601），仅当本次保存属于综述时填写
            review_window_until: 综述时间窗口截止（ISO 8601），仅当本次保存属于综述时填写
            review_kind: 标记本条记录类型，可选 ``"topic_summary"``（默认日报）或
                ``"topic_review"``（带出处的综述）。
        """
        from src.mcp.auth import require_admin
        from src.mcp.security import audit_log

        perm_err = require_admin()
        if perm_err:
            return perm_err

        if not content or not content.strip():
            return error_response("content 不能为空", "validation")

        # ---- 解析并校验 observations / review_window，组装 metadata ----
        metadata: dict = {}
        observation_errors: list[str] = []
        observation_count = 0

        # 支持两种形态:JSON 字符串(本意约定) 或 已被调用方/harness 解析过的 list。
        # 后者是为了兼容某些 MCP 客户端会把 "[…]" 形式自动二次解析为数组。
        parsed = None
        if isinstance(observations, list):
            parsed = observations
        elif isinstance(observations, str) and observations.strip():
            try:
                parsed = json.loads(observations)
            except json.JSONDecodeError as e:
                return error_response(
                    f"observations 不是合法 JSON: {e}", "validation"
                )

        if parsed is not None:
            if not isinstance(parsed, list):
                return error_response("observations 必须是 JSON 数组", "validation")

            cleaned: list[dict] = []
            for i, item in enumerate(parsed):
                if not isinstance(item, dict):
                    observation_errors.append(f"observations[{i}] 不是对象")
                    continue
                text = item.get("text")
                src_ids = item.get("source_tweet_ids") or []
                if not text or not isinstance(text, str):
                    observation_errors.append(f"observations[{i}] 缺少 text")
                    continue
                if not isinstance(src_ids, list):
                    observation_errors.append(
                        f"observations[{i}].source_tweet_ids 必须是数组"
                    )
                    continue
                # source_tweet_ids 为空不阻塞保存，但记入 errors 提示调用方补足
                src_ids = [str(s) for s in src_ids]
                if not src_ids:
                    observation_errors.append(
                        f"observations[{i}] 没有任何 source_tweet_ids（已保存但需检查）"
                    )
                cleaned.append({
                    "idx": item.get("idx", i + 1),
                    "text": text,
                    "source_tweet_ids": src_ids,
                })
            metadata["observations"] = cleaned
            observation_count = len(cleaned)

        if review_window_since or review_window_until:
            metadata["review_window"] = {
                "since": review_window_since,
                "until": review_window_until,
            }

        if review_kind and review_kind != "topic_summary":
            metadata["review_kind"] = review_kind

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
                    metadata_json=metadata if metadata else None,
                )

            audit_log(
                "save_topic_summary", "save",
                params={
                    "topic_id": topic_id,
                    "tweet_count": tweet_count,
                    "account_count": account_count,
                    "review_kind": review_kind,
                    "observation_count": observation_count,
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
                "review_kind": review_kind,
                "observation_count": observation_count,
                "observation_warnings": observation_errors,
            })

        except ValueError as e:
            return error_response(str(e), "validation")
        except Exception as e:
            audit_log("save_topic_summary", "save", result="failure", error=str(e))
            logger.error("save_topic_summary 失败: %s", e, exc_info=True)
            return error_response(f"保存摘要失败: {e}")
