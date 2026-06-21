"""主题摘要任务执行服务。"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from returns.result import Success
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.data_layer.provider import get_topic_store, get_topic_summary_task_store
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.domain.models import LLMResponse
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.llm.base import LLMProvider
from src.summarization.llm.config import LLMProviderConfig
from src.summarization.services.summarization_service import _get_global_llm_semaphore
from src.topic.domain.models import TopicSummaryTaskDomain, TopicSummaryTaskStatus

logger = logging.getLogger(__name__)

# 默认主题摘要提示词模板
DEFAULT_TOPIC_SUMMARY_PROMPT = """你是一位专业的信息分析师。请根据以下来自 {account_count} 个 Twitter 账号的 {tweet_count} 条推文，生成一份科技信息摘要报告。

报告开头必须包含以下元数据（每项单独一行，使用 Markdown 加粗格式）：
**数据范围：** {account_count}个账号 | {tweet_count}条推文
**覆盖时段：** {coverage_period}

要求：
1. 按话题/事件组织内容，找出主要讨论议题
2. 提取每个话题的关键观点和重要信息
3. 标注信息来源（哪个账号提到了什么）
4. 报告最后必须包含一个「## 综合观察」部分，综合分析本期内容的主要趋势和值得关注的信号（3-5 个要点）
5. 忽略与政治相关的讨论内容
6. 使用中文撰写报告
7. 不要在报告中添加"报告生成时间"或当前日期
8. 账号引用格式：
   - 对于下方"关注账号列表"中的账号：首次提及时使用「显示名（@用户名，极简介绍）」格式；后续提及直接使用显示名。显示名保持原文不翻译（例如写"Elon Musk"而非"伊隆·马斯克"）
   - 对于列表之外的其他 @账号：保持 @用户名 格式不变
{account_reference}

推文数据：
{tweets_content}

请生成摘要报告："""

# 主题综述提示词模板（带出处引用，供 /topic-review 使用）。
# 与日报模板相比，强调：
# - 时间窗口为任意区间而非固定 24h
# - 必须按"观点"组织，而非按事件流水
# - 每条观点必须挂至少 1 个 source_tweet_id，且必须出自下方推文清单
# - 末尾以 ```observations 代码块产出机器可读 JSON，供 save_topic_summary 入库
DEFAULT_TOPIC_REVIEW_PROMPT = """你是一位专业的信息综述写作者。请根据下方来自 {account_count} 个 Twitter 账号、共 {tweet_count} 条推文的内容，对该主题写一份带出处的"观点综述"（review），而不是新闻流水。

报告开头必须包含以下元数据（每项单独一行，使用 Markdown 加粗格式）：
**数据范围：** {account_count} 个账号 | {tweet_count} 条推文
**覆盖时段：** {coverage_period}

写作要求：
1. 围绕该主题抽取 5-12 个独立"观点"（observation），每个观点是一句可被独立验证的论断或趋势归纳。不要按时间或账号排版。
2. 每个观点写成一个二级标题 `## N. <观点一句话>` + 一段不超过 4 句话的展开。展开末尾用 Markdown 列表给出 1-N 条引用，每条形如 `- @author · YYYY-MM-DD · tweet_id=<id>`。
3. 引用中的 tweet_id 必须严格来自下方"推文数据"中标注的 `tweet_id=...`，禁止编造、禁止改写。如某观点没有任何推文支持，请删掉它，不要凭空补足。
4. 至少要让 60% 的观点拥有 ≥2 条出自不同账号的引用；少数观点可只有 1 条引用，但要明确标出"仅一处来源"。
5. **长推文（≥300 字符）必须优先纳入归纳作为主证据**。原因：长推文承载了完整的论点、数据、案例与上下文，承载的信息密度远高于短推文（一句话回复、转推一行评论）；若下方推文清单中存在与该主题相关的 ≥300 字符长推却未被任何观点引用，视为归纳失误，需要补回（要么扩充已有观点的引用，要么新增观点专门承接）。短推文（<100 字符的回复/简评）只在与某长推文形成强烈对照、补充或反方时才入选，不要把多条同口径的简短回复并列堆叠。
6. 报告最后必须包含 `## 综合观察` 部分，给出 3-5 个跨观点的趋势性判断；该段也要在每个判断末尾挂引用。
7. 忽略与政治相关的讨论。
8. 中文撰写。账号引用规则：
   - 对于下方"关注账号列表"中的账号：首次提及时使用「显示名（@用户名，极简介绍）」格式；后续提及直接使用显示名（保持原文，不音译）
   - 对于列表之外的其他 @账号：保持 @用户名 格式不变
9. **自检步骤**（产出综述前在心里跑一遍）：扫一遍下方推文清单里所有 ≥300 字符的推文，逐条判断是否与主题相关；若相关则确认它已经被某个观点的 source_tweet_ids 包含；若你判断"相关但故意不入选"，必须能说出明确理由（例如：与某条已入选长推完全同义而被合并）。
{account_reference}

正文写完之后，**必须**再追加一段以下格式的代码块（机器读取，用于落库）：

```observations
{{
  "observations": [
    {{"idx": 1, "text": "<同正文中第 1 条观点的标题>", "source_tweet_ids": ["<id1>", "<id2>"]}},
    {{"idx": 2, "text": "<同正文中第 2 条观点的标题>", "source_tweet_ids": ["<id3>"]}}
  ]
}}
```

要求：
- observations 数组的每条 idx 与正文 `## N.` 的编号一一对应（包含「综合观察」部分则 idx 接续编号）
- source_tweet_ids 必须是字符串数组，元素严格取自下方推文清单
- JSON 必须能被 `json.loads` 解析，不要写注释、不要尾随逗号

推文数据（每行格式：`tweet_id=<id> | <作者> | [创建时间] <正文>`）：
{tweets_content}

请直接输出综述报告："""

# 配图提示词模板
IMAGE_PROMPT_TEMPLATE = """你是一位专业的视觉设计提示词工程师。请根据以下摘要内容，生成一段适用于 AI 图片生成工具（如 DALL-E、Midjourney）的英文提示词。

要求：
1. 提取摘要中最核心的 1-2 个事件或主题作为画面主体
2. 提示词应描述一个具体的视觉场景，适合作为微信公众号文章的封面配图
3. 风格：现代、简洁、科技感，适合信息类文章
4. 直接输出提示词，不要包含任何解释或前缀

摘要内容：
{summary_content}

请生成图片提示词："""

# Token 上限（安全阈值）
MAX_CONTEXT_TOKENS = 80000


def build_llm_providers() -> list[LLMProvider]:
    """从环境配置构建 LLM provider 列表（按优先级排序）。

    复用 summarization_service 中的统一构建逻辑。
    """
    from src.summarization.services.summarization_service import _build_providers_from_config

    config = LLMProviderConfig.from_env()
    return _build_providers_from_config(config)


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
        tz_offset: int = 0,
    ) -> TopicSummaryTaskDomain:
        """创建摘要任务并异步启动执行。返回 pending 状态的任务。"""
        topic_store = get_topic_store(session)
        # 验证主题存在
        if not await topic_store.get_by_id(topic_id):
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 验证主题有关联账号
        if not await topic_store.get_accounts(topic_id):
            raise ValueError("该主题没有关联任何账号，无法创建摘要任务")

        # 规范化 deadline 为 naive UTC（asyncpg + Python 3.14 不接受 aware datetime 给 TIMESTAMP WITHOUT TIME ZONE 列）
        if deadline.tzinfo is not None:
            deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

        # 创建任务记录
        task_store = get_topic_summary_task_store(session)
        created = await task_store.create_task(
            topic_id=topic_id,
            time_span_hours=time_span_hours,
            deadline=deadline,
            custom_prompt=custom_prompt,
            tz_offset=tz_offset,
            status=TopicSummaryTaskStatus.pending.value,
        )
        await session.commit()

        # 异步启动后台执行
        asyncio.create_task(self._execute_task(created.id, session_factory))

        return created

    async def get_account_profiles(
        self, session: AsyncSession, usernames: list[str]
    ) -> dict[str, dict]:
        """查询账号档案和简介（降级容错）。

        Returns:
            {lowercase_username: {"display_name": ..., "brief_intro": ...}}
        """
        account_profiles: dict[str, dict] = {}
        try:
            from src.data_layer.provider import get_follows_repo, get_profile_repo

            profile_repo = get_profile_repo(session)
            profiles = await profile_repo.get_profiles_by_usernames(usernames)
            profiles_map = {p.username.lower(): p for p in profiles}

            config_repo = get_follows_repo(session)
            follows = await config_repo.get_active_follows()
            follows_map = {f.username.lower(): f for f in follows}

            for uname in usernames:
                key = uname.lower()
                profile = profiles_map.get(key)
                follow = follows_map.get(key)
                account_profiles[key] = {
                    "display_name": (profile.display_name if profile else None) or uname,
                    "brief_intro": follow.brief_intro if follow else None,
                }
        except Exception:
            logger.warning("查询账号档案/简介失败，使用默认格式", exc_info=True)
            account_profiles = {}
        return account_profiles

    async def save_external_summary(
        self,
        session: AsyncSession,
        topic_id: int,
        content: str,
        time_span_hours: int,
        deadline: datetime,
        tz_offset: int,
        tweet_count: int,
        account_count: int,
        metadata_json: dict | None = None,
    ) -> TopicSummaryTaskDomain:
        """保存外部（Claude Code）生成的摘要，创建已完成的 task + summary 记录。

        ``metadata_json`` 用于 /topic-review 等场景写入 observations、review_window
        等结构化字段；为 None 时落库为 ``{}``，与既有 /topic-summary 行为一致。
        """
        # 验证主题存在
        topic_store = get_topic_store(session)
        if not await topic_store.get_by_id(topic_id):
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 规范化 deadline
        if deadline.tzinfo is not None:
            deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 创建已完成的 task + summary（2 操作 1 次 commit 原子）
        from src.config import get_settings

        task_store = get_topic_summary_task_store(session)
        created = await task_store.create_task(
            topic_id=topic_id,
            time_span_hours=time_span_hours,
            deadline=deadline,
            tz_offset=tz_offset,
            status=TopicSummaryTaskStatus.completed.value,
            started_at=now,
            completed_at=now,
        )
        await task_store.create_summary(
            task_id=created.id,
            content=content,
            llm_provider="claude_code",
            llm_model=get_settings().claude_code_model_name,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=0.0,
            tweet_count=tweet_count,
            account_count=account_count,
            metadata_json=metadata_json or {},
        )
        await session.commit()

        # 回读含 summary 的完整 domain
        return await task_store.get_task(created.id)

    async def prepare_summary_data(
        self,
        session: AsyncSession,
        topic_id: int,
        time_span_hours: int,
        deadline: datetime,
        tz_offset: int = -480,
        since: datetime | None = None,
        until: datetime | None = None,
        review_mode: bool = False,
    ) -> dict:
        """获取主题推文数据和默认 prompt，供外部（Claude Code）生成摘要。

        Returns:
            包含 topic_name, coverage_period, tweet_count, account_count,
            default_prompt 等字段的字典。若无推文则 tweet_count=0 且无 default_prompt。
        """
        # 验证主题
        topic = await get_topic_store(session).get_by_id(topic_id)
        if not topic:
            raise ValueError(f"主题 ID {topic_id} 不存在")

        # 使用 eager-loaded accounts（get_by_id 已 selectinload）
        if not topic.accounts:
            raise ValueError("该主题没有关联任何账号")

        usernames = [a.username for a in topic.accounts]

        # 规范化 deadline
        if deadline.tzinfo is not None:
            deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)

        # 任意时间区间(since/until)优先于 deadline+time_span_hours：
        # 任一为非 None 时，按区间型语义计算 start/end；否则保持旧的"截至 deadline 回看 N 小时"。
        if since is not None or until is not None:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if until is not None:
                end_time = until.astimezone(timezone.utc).replace(tzinfo=None) if until.tzinfo else until
            else:
                end_time = now_utc
            if since is not None:
                start_time = since.astimezone(timezone.utc).replace(tzinfo=None) if since.tzinfo else since
            else:
                # 仅传 until 时，回退使用 time_span_hours 作窗口大小
                start_time = end_time - timedelta(hours=time_span_hours)
            if start_time >= end_time:
                raise ValueError("since 必须早于 until")
        else:
            end_time = deadline
            start_time = end_time - timedelta(hours=time_span_hours)

        # 获取账号档案
        account_profiles = await self.get_account_profiles(session, usernames)

        # 查询推文
        tweets_data = await self._query_tweets(session, usernames, start_time, end_time)

        coverage_period = self._format_coverage_period(start_time, end_time, tz_offset)

        result: dict = {
            "topic_id": topic_id,
            "topic_name": topic.name,
            "time_span_hours": time_span_hours,
            "deadline": str(end_time),
            "coverage_period": coverage_period,
            "account_count": len(usernames),
            "review_mode": review_mode,
            "window": {
                "since": start_time.isoformat() + "Z",
                "until": end_time.isoformat() + "Z",
            },
        }

        if not tweets_data:
            result["tweet_count"] = 0
            result["message"] = "该时间范围内没有找到推文数据"
            return result

        # 构建 prompt
        prompt, tweet_count, tweet_id_pool = self._build_prompt(
            tweets_data, usernames, time_span_hours,
            start_time, end_time, tz_offset,
            account_profiles=account_profiles or None,
            review_mode=review_mode,
        )

        result["tweet_count"] = tweet_count
        result["default_prompt"] = prompt
        # 列出本次纳入 prompt 的 tweet_id 集合，便于调用方在保存前自检
        # observations 中的 source_tweet_ids 是否真的来自这批数据
        result["allowed_tweet_ids"] = tweet_id_pool
        return result

    async def _execute_task(
        self, task_id: int, session_factory: async_sessionmaker
    ) -> None:
        """后台执行摘要任务。"""
        try:
            async with session_factory() as session:
                task_store = get_topic_summary_task_store(session)
                topic_store = get_topic_store(session)

                # 获取任务
                task = await task_store.get_task(task_id)
                if not task:
                    logger.error(f"摘要任务 {task_id} 不存在")
                    return

                # 更新状态为 running（域 status 用枚举，store update_task 内部取 .value）
                task.status = TopicSummaryTaskStatus.running
                task.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await task_store.update_task(task)
                await session.commit()

                # 查询关联账号
                accounts = await topic_store.get_accounts(task.topic_id)
                usernames = [a.username for a in accounts]

                # 查询档案和简介（降级容错）
                account_profiles = await self.get_account_profiles(session, usernames)

                # 计算时间范围
                end_time = task.deadline
                start_time = end_time - timedelta(hours=task.time_span_hours)

                # 查询推文（LEFT JOIN 已有翻译，跨域读保持走 session）
                tweets_data = await self._query_tweets(session, usernames, start_time, end_time)

                if not tweets_data:
                    # 无推文数据
                    await task_store.create_summary(
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
                    task.status = TopicSummaryTaskStatus.completed
                    task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await task_store.update_task(task)
                    await session.commit()
                    return

                # 构建聚合 prompt（backend 路径不启用 review_mode，第三个返回值忽略）
                # tz_offset 不在 TopicSummaryTaskDomain 域投影内（se 数据层契约:tz_offset
                # 存盘但不出域、to_domain 不投影、永不入 parity），故走域模型默认值 0，
                # 与 store 两侧 to_domain 的投影一致（原 ORM 路径默认 tz_offset=0 时字节等价）。
                tz_offset = getattr(task, "tz_offset", 0)
                prompt, tweet_count, _ = self._build_prompt(
                    tweets_data, usernames, task.time_span_hours,
                    start_time, end_time, tz_offset, task.custom_prompt,
                    account_profiles=account_profiles or None,
                )

                # 调用 LLM
                llm_result = await self._call_llm_with_failover(prompt)

                if llm_result is None:
                    # 全部 provider 失败
                    task.status = TopicSummaryTaskStatus.failed
                    task.error_message = "所有 LLM 提供商均不可用"
                    task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await task_store.update_task(task)
                    await session.commit()
                    return

                # 保存摘要结果
                await task_store.create_summary(
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
                task.status = TopicSummaryTaskStatus.completed
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await task_store.update_task(task)
                await session.commit()

                logger.info(f"摘要任务 {task_id} 完成: {tweet_count} 条推文, provider={llm_result.provider}")

        except Exception as e:
            logger.exception(f"摘要任务 {task_id} 执行异常: {e}")
            try:
                async with session_factory() as err_session:
                    task_store = get_topic_summary_task_store(err_session)
                    task = await task_store.get_task(task_id)
                    if task:
                        task.status = TopicSummaryTaskStatus.failed
                        task.error_message = str(e)
                        task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        await task_store.update_task(task)
                        await err_session.commit()
            except Exception as inner_e:
                logger.error(f"更新任务 {task_id} 失败状态时出错: {inner_e}")

    async def _query_tweets(
        self, session: AsyncSession, usernames: list[str],
        start_time: datetime, end_time: datetime
    ) -> list[dict]:
        """查询指定账号在时间范围内的推文，优先使用已有翻译。

        同时取出 referenced_tweet_text/referenced_tweet_author_username，
        便于 RT/quote 类推文（外壳 ~140 字符、本体常达 2000+ 字符）把
        真正的信息体投放进 prompt，避免 LLM 只能看到"RT @x: ..."外壳。
        """
        stmt = (
            select(
                TweetOrm.tweet_id,
                TweetOrm.text,
                TweetOrm.author_username,
                TweetOrm.created_at,
                SummaryOrm.translation_text,
                TweetOrm.referenced_tweet_text,
                TweetOrm.referenced_tweet_author_username,
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
                "referenced_tweet_text": row[5],
                "referenced_tweet_author_username": row[6],
            }
            for row in rows
        ]

    @staticmethod
    def _format_coverage_period(
        start_time: datetime, end_time: datetime, tz_offset: int
    ) -> str:
        """根据 UTC 起止时间和 tz_offset 生成用户本地时区的覆盖时段字符串。

        Args:
            start_time: UTC 起始时间
            end_time: UTC 截止时间
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），UTC+8 为 -480

        Returns:
            如 ``2026/02/18 00:00 ~ 2026/02/19 00:00 (UTC+8)``
        """
        # getTimezoneOffset() 返回 UTC - local，所以 local = UTC + (-tz_offset)
        offset_td = timedelta(minutes=-tz_offset)
        user_tz = timezone(offset_td)
        # 从 SQLite 取出的 naive datetime 实际是 UTC，需要显式标记
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        start_local = start_time.astimezone(user_tz)
        end_local = end_time.astimezone(user_tz)

        # 时区标签
        if offset_td >= timedelta():
            sign = "+"
        else:
            sign = "-"
        abs_seconds = int(abs(offset_td).total_seconds())
        tz_hours = abs_seconds // 3600
        tz_mins = (abs_seconds % 3600) // 60
        if tz_mins:
            tz_label = f"UTC{sign}{tz_hours}:{tz_mins:02d}"
        else:
            tz_label = f"UTC{sign}{tz_hours}"

        return (
            f"{start_local.strftime('%Y/%m/%d %H:%M')} ~ "
            f"{end_local.strftime('%Y/%m/%d %H:%M')} ({tz_label})"
        )

    def _build_prompt(
        self,
        tweets_data: list[dict],
        usernames: list[str],
        time_span_hours: int,
        start_time: datetime,
        end_time: datetime,
        tz_offset: int = 0,
        custom_prompt: str | None = None,
        account_profiles: dict[str, dict] | None = None,
        review_mode: bool = False,
    ) -> tuple[str, int, list[str]]:
        """构建聚合提示词。

        Returns:
            (prompt, tweet_count, tweet_id_pool)
            tweet_id_pool 列出本次实际写进 prompt 的所有 tweet_id，
            供调用方在保存前比对 observations 引用的合法性。

        选片策略（修复 dict-order 截断 bug）：
            1. 全局按"信息密度"打分（text + referenced_tweet_text 估 token），
               长推文获得高分；
            2. 维护单作者软配额 ``SOFT_CAP_PER_AUTHOR=30``，防止一个 author
                的长推文风暴占满整个预算；
            3. 第一阶段按打分倒序填预算（超预算 ``continue`` 而非 ``break``，
               让更短的推文有机会塞进剩余空间）；
            4. 第二阶段公平兜底：第一阶段一条都没入选的 author，从其推文里
               找最短能塞下的一条强行加入，确保每个有数据的 author 都有声音；
            5. 输出仍按 ``by_author`` dict 的 key 顺序（各 author 第一条推文
               时间），作者内部按时间正序，叙事感与原行为一致。
        """
        # 按作者分组（dict 插入序就是各 author 第一条推文的时间序）
        by_author: dict[str, list[dict]] = {}
        for tweet in tweets_data:
            author = tweet["author"]
            if author not in by_author:
                by_author[author] = []
            by_author[author].append(tweet)

        # 预渲染每条推文为 prompt 行，并打分（含 ref_text 长度）
        def _render_tweet_line(tweet: dict, author: str) -> str:
            text = tweet["translation"] or tweet["text"]
            if review_mode:
                line = (
                    f"tweet_id={tweet['tweet_id']} | @{author} | "
                    f"[{tweet['created_at']}] {text}\n"
                )
            else:
                line = f"[{tweet['created_at']}] {text}\n"
            ref_text = tweet.get("referenced_tweet_text") or ""
            if ref_text:
                ref_author = tweet.get("referenced_tweet_author_username") or ""
                ref_prefix = f"@{ref_author}" if ref_author else "via"
                line += f"  ↪ via {ref_prefix}: {ref_text}\n"
            return line

        def _make_section(author: str) -> str:
            if account_profiles and author.lower() in account_profiles:
                dn = account_profiles[author.lower()]["display_name"]
                return f"\n--- {dn}（@{author}）---\n"
            return f"\n--- @{author} ---\n"

        rendered: list[dict] = []
        for author, author_tweets in by_author.items():
            for tweet in author_tweets:
                line = _render_tweet_line(tweet, author)
                tokens = estimate_tokens(line)
                rendered.append({
                    "tweet": tweet,
                    "author": author,
                    "line": line,
                    "tokens": tokens,
                })

        # 长推优先：按 token 数倒序（供 stage 2 全局填空）
        rendered.sort(key=lambda r: r["tokens"], reverse=True)

        section_tokens_by_author: dict[str, int] = {}
        per_author_count: dict[str, int] = {}
        selected: dict[str, dict] = {}  # tweet_id -> rendered item
        used_tokens = 0

        # Stage 1：公平基线——每个 active author 至少 1 条（最长能塞下的）
        # 综述场景的核心是"听到所有声音"，覆盖率优先于"长推全堆给大户"。
        # 实测 65 账号 × 7 天窗口，43 个 active author × 平均 ~200 token/作者 ≈ 8.6k，
        # 80k 预算下保底基线只占 1/9，剩下绝大部分留给 stage 2 长推填空。
        for author, author_tweets in by_author.items():
            section_tok = estimate_tokens(_make_section(author))
            longest_first = sorted(
                (r for r in rendered if r["author"] == author),
                key=lambda r: r["tokens"],
                reverse=True,
            )
            for r in longest_first:
                delta = r["tokens"] + section_tok
                if used_tokens + delta > MAX_CONTEXT_TOKENS:
                    continue  # 该条太长塞不下，降一档试更短的
                selected[r["tweet"]["tweet_id"]] = r
                used_tokens += delta
                section_tokens_by_author[author] = section_tok
                per_author_count[author] = 1
                break
            # 若该 author 所有推文都比剩余预算大（极端情况），放弃

        # Stage 2：长推优先填空 + 软配额（防单作者长推风暴吃掉所有预算）
        # 配额 15 = 一周窗口下单 author 上限。先前实测 30 时，4 个长推大户
        # （levelsio/garymarcus/elonmusk/hwchase17）满配 30 条占 ~70% 预算，
        # 14 个小作者直接被挤掉；改 15 后 4 大户每个 15 条仍能保住主要观点，
        # 剩余 35k+ token 让长尾 author 也能补到 2-3 条。
        SOFT_CAP_PER_AUTHOR = 15
        for r in rendered:
            tid = r["tweet"]["tweet_id"]
            if tid in selected:
                continue
            author = r["author"]
            if per_author_count.get(author, 0) >= SOFT_CAP_PER_AUTHOR:
                continue
            section_first_use = author not in section_tokens_by_author
            delta = r["tokens"]
            if section_first_use:
                section_tok = estimate_tokens(_make_section(author))
                delta += section_tok
            if used_tokens + delta > MAX_CONTEXT_TOKENS:
                continue  # 跳过，留给更短的推文
            selected[tid] = r
            used_tokens += delta
            if section_first_use:
                section_tokens_by_author[author] = section_tok
            per_author_count[author] = per_author_count.get(author, 0) + 1

        # 输出顺序：沿用 by_author dict 的 key 顺序（各 author 第一条推文时间），
        # 作者内部按时间正序，保留原叙事感
        content_parts: list[str] = []
        tweet_id_pool: list[str] = []
        for author in by_author.keys():
            chosen = [
                selected[t["tweet_id"]]
                for t in by_author[author]
                if t["tweet_id"] in selected
            ]
            if not chosen:
                continue
            chosen.sort(key=lambda r: r["tweet"]["created_at"])
            content_parts.append(_make_section(author))
            for r in chosen:
                content_parts.append(r["line"])
                tweet_id_pool.append(str(r["tweet"]["tweet_id"]))

        tweets_content = "".join(content_parts)
        tweet_count = len(tweet_id_pool)

        # 时间跨度描述（保留用于 custom_prompt 向后兼容）
        if time_span_hours < 24:
            time_span = f"{time_span_hours} 小时"
        else:
            days = time_span_hours // 24
            remaining_hours = time_span_hours % 24
            time_span = f"{days} 天"
            if remaining_hours:
                time_span += f" {remaining_hours} 小时"

        # 覆盖时段描述
        coverage_period = self._format_coverage_period(start_time, end_time, tz_offset)

        # 构建关注账号列表引用
        account_reference = ""
        if account_profiles:
            ref_lines = []
            for uname in usernames:
                key = uname.lower()
                if key in account_profiles:
                    ap = account_profiles[key]
                    dn = ap["display_name"]
                    intro = ap.get("brief_intro")
                    if intro:
                        ref_lines.append(f"- {dn}（@{uname}）：{intro}")
                    else:
                        ref_lines.append(f"- {dn}（@{uname}）")
            if ref_lines:
                account_reference = "\n关注账号列表：\n" + "\n".join(ref_lines)

        # 选择提示词模板
        format_kwargs = {
            "account_count": len(usernames),
            "time_span": time_span,
            "tweet_count": tweet_count,
            "tweets_content": tweets_content,
            "coverage_period": coverage_period,
            "account_reference": account_reference,
        }
        if custom_prompt:
            prompt = custom_prompt.format(**format_kwargs)
        elif review_mode:
            prompt = DEFAULT_TOPIC_REVIEW_PROMPT.format(**format_kwargs)
        else:
            prompt = DEFAULT_TOPIC_SUMMARY_PROMPT.format(**format_kwargs)

        return prompt, tweet_count, tweet_id_pool

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
                        max_tokens=8192,  # 摘要可能较长
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
        return await get_topic_summary_task_store(session).get_task(task_id)

    async def list_tasks(
        self, session: AsyncSession, topic_id: int | None = None, user_id: int | None = None
    ) -> list[TopicSummaryTaskDomain]:
        """列出任务（按创建时间倒序），可按 topic_id 和 user_id 筛选。"""
        return await get_topic_summary_task_store(session).list_tasks(topic_id, user_id=user_id)

    async def generate_image_prompt(self, session: AsyncSession, task_id: int) -> dict:
        """基于摘要内容生成配图提示词（实时调用 LLM）。"""
        task = await get_topic_summary_task_store(session).get_task(task_id)
        if not task or not task.summary:
            raise ValueError("摘要任务不存在或尚未生成摘要")

        prompt = IMAGE_PROMPT_TEMPLATE.format(summary_content=task.summary.content)
        result = await self._call_llm_with_failover(prompt)
        if not result:
            raise ValueError("所有 LLM 提供商均失败")

        return {
            "image_prompt": result.content.strip(),
            "llm_provider": result.provider,
            "llm_model": result.model,
        }

    async def get_latest_summary(
        self, session: AsyncSession, topic_id: int
    ) -> TopicSummaryTaskDomain | None:
        """获取主题的最新已完成摘要任务（含摘要内容）。"""
        if not await get_topic_store(session).get_by_id(topic_id):
            raise ValueError("主题不存在")
        return await get_topic_summary_task_store(session).get_latest_completed_task(topic_id)

    async def delete_task(self, session: AsyncSession, task_id: int) -> bool:
        """删除任务（级联删除摘要结果）。"""
        result = await get_topic_summary_task_store(session).delete_task(task_id)
        if result:
            await session.commit()
        return result
