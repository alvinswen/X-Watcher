"""MCP 摘要管理工具。

提供 get_unsummarized_tweets 和 save_summaries 两个工具，
支持 Claude Code 作为 LLM 引擎接管推文翻译/摘要工作。
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from src.mcp.auth import require_admin
from src.mcp.helpers import (
    error_response,
    parse_datetime_optional,
    success_response,
)

logger = logging.getLogger(__name__)


def register(mcp: FastMCP) -> None:
    """注册摘要管理工具。"""

    @mcp.tool()
    async def get_unsummarized_tweets(
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        limit: int = 50,
    ) -> str:
        """获取缺少摘要的推文，供外部翻译引擎（如 Claude Code）处理。需要管理员权限。

        Args:
            since: 起始时间，ISO 8601 格式（可选）
            until: 截止时间，ISO 8601 格式（可选）
            author: 按作者用户名过滤（可选）
            limit: 最大返回数量，默认 50，上限 200
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        try:
            from sqlalchemy import select

            from src.database.async_session import get_async_session_maker
            from src.scraper.infrastructure.models import TweetOrm
            from src.summarization.infrastructure.models import SummaryOrm

            since_dt = parse_datetime_optional(since)
            until_dt = parse_datetime_optional(until)
            clamped_limit = min(max(limit, 1), 200)

            session_maker = get_async_session_maker()
            async with session_maker() as session:
                stmt = (
                    select(
                        TweetOrm.tweet_id,
                        TweetOrm.text,
                        TweetOrm.author_username,
                        TweetOrm.author_display_name,
                        TweetOrm.reference_type,
                        TweetOrm.referenced_tweet_text,
                        TweetOrm.referenced_tweet_author_username,
                        TweetOrm.created_at,
                    )
                    .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
                    .where(SummaryOrm.summary_id == None)  # noqa: E711
                )

                if since_dt:
                    stmt = stmt.where(TweetOrm.created_at >= since_dt)
                if until_dt:
                    stmt = stmt.where(TweetOrm.created_at < until_dt)
                if author:
                    stmt = stmt.where(TweetOrm.author_username == author)

                stmt = stmt.order_by(TweetOrm.created_at.desc()).limit(clamped_limit)

                result = await session.execute(stmt)
                rows = result.fetchall()

            tweets = []
            for row in rows:
                mapping = row._mapping
                tweets.append({
                    "tweet_id": mapping["tweet_id"],
                    "text": mapping["text"],
                    "author_username": mapping["author_username"],
                    "author_display_name": mapping["author_display_name"],
                    "reference_type": mapping["reference_type"],
                    "referenced_tweet_text": mapping["referenced_tweet_text"],
                    "referenced_tweet_author_username": mapping["referenced_tweet_author_username"],
                    "created_at": mapping["created_at"],
                })

            return success_response({
                "tweets": tweets,
                "count": len(tweets),
            })

        except Exception as e:
            logger.error("get_unsummarized_tweets 失败: %s", e, exc_info=True)
            return error_response(f"获取待翻译推文失败: {e}")

    @mcp.tool()
    async def save_summaries(
        summaries: list | str,
    ) -> str:
        """保存外部生成的摘要/翻译结果到数据库。需要管理员权限。

        Args:
            summaries: 数组，每项包含：
                       - tweet_id (必填): 推文 ID
                       - summary (必填): 中文摘要（≤500字符）
                       - translation (可选): 中文翻译
                       优先以原生数组形式传入；也兼容 JSON 字符串
                       （为兼容旧调用方保留，但不推荐——手工拼装 JSON 字符串
                       容易出现引号转义错位类错误）。
        """
        perm_err = require_admin()
        if perm_err:
            return perm_err

        # 支持两种形态:原生 list(推荐) 或 JSON 字符串(兼容旧调用方)。
        # 原生 list 由 MCP 层 / Pydantic 直接反序列化,杜绝引号转义错位类错误。
        if isinstance(summaries, str):
            try:
                items = json.loads(summaries)
            except json.JSONDecodeError as e:
                return error_response(f"JSON 解析失败: {e}", "validation")
        else:
            items = summaries

        if not isinstance(items, list):
            return error_response("summaries 必须是数组", "validation")

        try:
            from src.config import get_settings
            from src.database.async_session import get_async_session_maker
            from src.mcp.security import audit_log
            from src.summarization.domain.models import SummaryRecord
            from src.summarization.infrastructure.repository import SummarizationRepository

            model_name = get_settings().claude_code_model_name
            session_maker = get_async_session_maker()
            saved = 0
            failed = 0
            errors = []
            now = datetime.now(timezone.utc)

            async with session_maker() as session:
                repo = SummarizationRepository(session)

                for item in items:
                    if not isinstance(item, dict):
                        failed += 1
                        errors.append(f"条目不是对象: {type(item).__name__}")
                        continue
                    try:
                        tweet_id = item.get("tweet_id")
                        summary_text = item.get("summary")

                        if not tweet_id or not summary_text:
                            failed += 1
                            errors.append(f"缺少必填字段: tweet_id={tweet_id}")
                            continue

                        content_hash = hashlib.sha256(
                            f"{tweet_id}:claude_code".encode()
                        ).hexdigest()

                        record = SummaryRecord(
                            summary_id=str(uuid.uuid4()),
                            tweet_id=tweet_id,
                            summary_text=summary_text,
                            translation_text=item.get("translation"),
                            model_provider="claude_code",
                            model_name=model_name,
                            prompt_tokens=0,
                            completion_tokens=0,
                            total_tokens=0,
                            cost_usd=0.0,
                            cached=False,
                            is_generated_summary=True,
                            content_hash=content_hash,
                            created_at=now,
                            updated_at=now,
                        )

                        await repo.save_summary_record(record)
                        saved += 1

                    except Exception as e:
                        failed += 1
                        errors.append(
                            f"tweet_id={item.get('tweet_id')}: "
                            f"{type(e).__name__}: {e}"
                        )
                        logger.warning("保存摘要失败: %s", e)

                await session.commit()

            audit_log(
                "save_summaries", "save",
                params={"total": len(items), "saved": saved, "failed": failed},
            )

            return success_response({
                "saved": saved,
                "failed": failed,
                "total": len(items),
                "errors": errors[:10] if errors else [],
            })

        except Exception as e:
            logger.error("save_summaries 失败: %s", e, exc_info=True)
            return error_response(f"保存摘要失败: {e}")
