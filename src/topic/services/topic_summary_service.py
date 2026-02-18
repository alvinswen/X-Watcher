"""主题摘要任务执行服务。"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from returns.result import Success
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.scraper.infrastructure.models import TweetOrm
from src.summarization.domain.models import LLMResponse
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.llm.base import LLMProvider
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.llm.minimax import MiniMaxProvider
from src.summarization.llm.openrouter import OpenRouterProvider
from src.summarization.services.summarization_service import _get_global_llm_semaphore
from src.topic.domain.models import TopicSummaryTaskDomain, TopicSummaryTaskStatus
from src.topic.infrastructure.models import TopicSummaryOrm, TopicSummaryTaskOrm
from src.topic.infrastructure.repository import TopicRepository, TopicSummaryTaskRepository

logger = logging.getLogger(__name__)

# 默认主题摘要提示词模板
DEFAULT_TOPIC_SUMMARY_PROMPT = """你是一位专业的信息分析师。请根据以下来自 {account_count} 个 Twitter 账号在过去 {time_span} 内发布的 {tweet_count} 条推文，生成一份综合摘要报告。

要求：
1. 按话题/事件组织内容，找出主要讨论议题
2. 提取每个话题的关键观点和重要信息
3. 标注信息来源（哪个账号提到了什么）
4. 综合多方观点，呈现全面的信息图景
5. 使用中文撰写报告

推文数据：
{tweets_content}

请生成摘要报告："""

# Token 上限（安全阈值）
MAX_CONTEXT_TOKENS = 80000


def build_llm_providers() -> list[LLMProvider]:
    """从环境配置构建 LLM provider 列表（按优先级排序）。"""
    config = LLMProviderConfig.from_env()
    providers: list[LLMProvider] = []

    if config.openrouter:
        providers.append(OpenRouterProvider(
            api_key=config.openrouter.api_key,
            base_url=config.openrouter.base_url,
            model=config.openrouter.model,
            timeout_seconds=config.openrouter.timeout_seconds,
            max_retries=config.openrouter.max_retries,
        ))

    if config.minimax:
        providers.append(MiniMaxProvider(
            api_key=config.minimax.api_key,
            base_url=config.minimax.base_url,
            model=config.minimax.model,
            group_id=config.minimax.group_id,
            timeout_seconds=config.minimax.timeout_seconds,
            max_retries=config.minimax.max_retries,
        ))

    return providers


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。中文字 ≈ 1 token，英文 ≈ 1.3 token/word。"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    # 移除中文字符后统计英文词数
    remaining_chars = []
    for c in text:
        if '\u4e00' <= c <= '\u9fff':
            remaining_chars.append(' ')
        else:
            remaining_chars.append(c)
    remaining = ''.join(remaining_chars)
    english_words = len(remaining.split())
    return chinese_chars + int(english_words * 1.3)


class TopicSummaryService:
    """主题摘要任务执行服务。"""

    _instance: "TopicSummaryService | None" = None

    def __init__(self, providers: list[LLMProvider] | None = None) -> None:
        self._providers = providers if providers is not None else build_llm_providers()
        self._topic_repo = TopicRepository()
        self._task_repo = TopicSummaryTaskRepository()

    @classmethod
    def get_instance(cls) -> "TopicSummaryService":
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）。"""
        cls._instance = None

    async def create_and_execute_task(
        self,
        session: AsyncSession,
        session_factory: async_sessionmaker,
        topic_id: int,
        time_span_hours: int,
        deadline: datetime,
        custom_prompt: str | None = None,
    ) -> TopicSummaryTaskDomain:
        """创建摘要任务并异步启动执行。返回 pending 状态的任务。"""
        # 验证主题存在
        topic = await self._topic_repo.get_by_id(session, topic_id)
        if not topic:
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 验证主题有关联账号
        accounts = await self._topic_repo.get_accounts(session, topic_id)
        if not accounts:
            raise ValueError("该主题没有关联任何账号，无法创建摘要任务")

        # 创建任务记录
        task_orm = TopicSummaryTaskOrm(
            topic_id=topic_id,
            time_span_hours=time_span_hours,
            deadline=deadline,
            custom_prompt=custom_prompt,
            status=TopicSummaryTaskStatus.pending.value,
        )
        await self._task_repo.create_task(session, task_orm)
        await session.commit()

        # 刷新以获取完整的关联（topic + summary）
        await session.refresh(task_orm, ["topic", "summary"])

        task_domain = task_orm.to_domain()

        # 异步启动后台执行
        asyncio.create_task(self._execute_task(task_orm.id, session_factory))

        return task_domain

    async def _execute_task(
        self, task_id: int, session_factory: async_sessionmaker
    ) -> None:
        """后台执行摘要任务。"""
        try:
            async with session_factory() as session:
                # 获取任务
                task = await self._task_repo.get_task(session, task_id)
                if not task:
                    logger.error(f"摘要任务 {task_id} 不存在")
                    return

                # 更新状态为 running
                task.status = TopicSummaryTaskStatus.running.value
                task.started_at = datetime.now(timezone.utc)
                await self._task_repo.update_task(session, task)
                await session.commit()

                # 查询关联账号
                accounts = await self._topic_repo.get_accounts(session, task.topic_id)
                usernames = [a.username for a in accounts]

                # 计算时间范围
                end_time = task.deadline
                start_time = end_time - timedelta(hours=task.time_span_hours)

                # 查询推文（LEFT JOIN 已有翻译）
                tweets_data = await self._query_tweets(session, usernames, start_time, end_time)

                if not tweets_data:
                    # 无推文数据
                    summary_orm = TopicSummaryOrm(
                        task_id=task_id,
                        content="该时间范围内没有找到推文数据",
                        llm_provider="none",
                        llm_model="none",
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        cost_usd=0.0,
                        tweet_count=0,
                        account_count=len(usernames),
                    )
                    await self._task_repo.create_summary(session, summary_orm)
                    task.status = TopicSummaryTaskStatus.completed.value
                    task.completed_at = datetime.now(timezone.utc)
                    await self._task_repo.update_task(session, task)
                    await session.commit()
                    return

                # 构建聚合 prompt
                prompt, tweet_count = self._build_prompt(
                    tweets_data, usernames, task.time_span_hours, task.custom_prompt
                )

                # 调用 LLM
                llm_result = await self._call_llm_with_failover(prompt)

                if llm_result is None:
                    # 全部 provider 失败
                    task.status = TopicSummaryTaskStatus.failed.value
                    task.error_message = "所有 LLM 提供商均不可用"
                    task.completed_at = datetime.now(timezone.utc)
                    await self._task_repo.update_task(session, task)
                    await session.commit()
                    return

                # 保存摘要结果
                summary_orm = TopicSummaryOrm(
                    task_id=task_id,
                    content=llm_result.content,
                    llm_provider=llm_result.provider,
                    llm_model=llm_result.model,
                    prompt_tokens=llm_result.prompt_tokens,
                    completion_tokens=llm_result.completion_tokens,
                    total_tokens=llm_result.total_tokens,
                    cost_usd=llm_result.cost_usd,
                    tweet_count=tweet_count,
                    account_count=len(usernames),
                )
                await self._task_repo.create_summary(session, summary_orm)
                task.status = TopicSummaryTaskStatus.completed.value
                task.completed_at = datetime.now(timezone.utc)
                await self._task_repo.update_task(session, task)
                await session.commit()

                logger.info(f"摘要任务 {task_id} 完成: {tweet_count} 条推文, provider={llm_result.provider}")

        except Exception as e:
            logger.exception(f"摘要任务 {task_id} 执行异常: {e}")
            try:
                async with session_factory() as err_session:
                    task = await self._task_repo.get_task(err_session, task_id)
                    if task:
                        task.status = TopicSummaryTaskStatus.failed.value
                        task.error_message = str(e)
                        task.completed_at = datetime.now(timezone.utc)
                        await self._task_repo.update_task(err_session, task)
                        await err_session.commit()
            except Exception as inner_e:
                logger.error(f"更新任务 {task_id} 失败状态时出错: {inner_e}")

    async def _query_tweets(
        self, session: AsyncSession, usernames: list[str],
        start_time: datetime, end_time: datetime
    ) -> list[dict]:
        """查询指定账号在时间范围内的推文，优先使用已有翻译。"""
        stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.text,
                TweetOrm.author_username,
                TweetOrm.created_at,
                SummaryOrm.translation_text,
            )
            .outerjoin(SummaryOrm, TweetOrm.tweet_id == SummaryOrm.tweet_id)
            .where(
                func.lower(TweetOrm.author_username).in_([u.lower() for u in usernames]),
                TweetOrm.created_at >= start_time,
                TweetOrm.created_at <= end_time,
            )
            .order_by(TweetOrm.created_at.asc())
        )
        result = await session.execute(stmt)
        rows = result.all()

        return [
            {
                "tweet_id": row[0],
                "text": row[1],
                "author": row[2],
                "created_at": row[3],
                "translation": row[4],
            }
            for row in rows
        ]

    def _build_prompt(
        self,
        tweets_data: list[dict],
        usernames: list[str],
        time_span_hours: int,
        custom_prompt: str | None = None,
    ) -> tuple[str, int]:
        """构建聚合提示词。返回 (prompt, tweet_count)。"""
        # 按作者分组
        by_author: dict[str, list[dict]] = {}
        for tweet in tweets_data:
            author = tweet["author"]
            if author not in by_author:
                by_author[author] = []
            by_author[author].append(tweet)

        # 构建推文内容（优先使用翻译）
        content_parts: list[str] = []
        total_tokens = 0
        included_count = 0

        for author, author_tweets in by_author.items():
            author_section = f"\n--- @{author} ---\n"
            author_tokens = estimate_tokens(author_section)

            for tweet in author_tweets:
                # 优先使用已有翻译
                text = tweet["translation"] or tweet["text"]
                tweet_line = f"[{tweet['created_at']}] {text}\n"
                line_tokens = estimate_tokens(tweet_line)

                # 检查是否超出上下文限制
                if total_tokens + author_tokens + line_tokens > MAX_CONTEXT_TOKENS:
                    break  # 截断最旧推文（已按时间正序）

                if not content_parts or content_parts[-1] != author_section:
                    content_parts.append(author_section)
                    total_tokens += author_tokens

                content_parts.append(tweet_line)
                total_tokens += line_tokens
                included_count += 1

        tweets_content = "".join(content_parts)
        tweet_count = included_count

        # 时间跨度描述
        if time_span_hours < 24:
            time_span = f"{time_span_hours} 小时"
        else:
            days = time_span_hours // 24
            remaining_hours = time_span_hours % 24
            time_span = f"{days} 天"
            if remaining_hours:
                time_span += f" {remaining_hours} 小时"

        # 选择提示词模板
        if custom_prompt:
            prompt = custom_prompt.format(
                account_count=len(usernames),
                time_span=time_span,
                tweet_count=tweet_count,
                tweets_content=tweets_content,
            )
        else:
            prompt = DEFAULT_TOPIC_SUMMARY_PROMPT.format(
                account_count=len(usernames),
                time_span=time_span,
                tweet_count=tweet_count,
                tweets_content=tweets_content,
            )

        return prompt, tweet_count

    async def _call_llm_with_failover(self, prompt: str) -> LLMResponse | None:
        """调用 LLM（failover 模式），获取全局信号量控制并发。"""
        if not self._providers:
            logger.error("没有可用的 LLM 提供商")
            return None

        semaphore = _get_global_llm_semaphore()

        async with semaphore:
            for i, provider in enumerate(self._providers):
                try:
                    logger.info(f"尝试 LLM provider {provider.get_provider_name()} (#{i+1}/{len(self._providers)})")
                    result = await provider.complete(
                        prompt=prompt,
                        max_tokens=4096,  # 摘要可能较长
                        temperature=0.3,  # 偏向确定性输出
                    )
                    if isinstance(result, Success):
                        return result.unwrap()
                    else:
                        logger.warning(f"Provider {provider.get_provider_name()} 返回失败: {result.failure()}")
                except Exception as e:
                    logger.warning(f"Provider {provider.get_provider_name()} 调用异常: {e}")

        logger.error("所有 LLM 提供商均失败")
        return None

    # ── 查询接口（供 API 层调用）──

    async def get_task(self, session: AsyncSession, task_id: int) -> TopicSummaryTaskDomain | None:
        """查询任务详情（含摘要结果）。"""
        task = await self._task_repo.get_task(session, task_id)
        return task.to_domain() if task else None

    async def list_tasks(
        self, session: AsyncSession, topic_id: int | None = None
    ) -> list[TopicSummaryTaskDomain]:
        """列出任务（按创建时间倒序），可按 topic_id 筛选。"""
        tasks = await self._task_repo.list_tasks(session, topic_id)
        return [t.to_domain() for t in tasks]

    async def delete_task(self, session: AsyncSession, task_id: int) -> bool:
        """删除任务（级联删除摘要结果）。"""
        result = await self._task_repo.delete_task(session, task_id)
        if result:
            await session.commit()
        return result
