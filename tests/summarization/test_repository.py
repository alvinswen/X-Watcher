"""摘要仓储单元测试。

测试 SummarizationRepository 的 CRUD 操作和事务处理。
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database.models import Base
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.models import SummaryOrm
from src.summarization.infrastructure.repository import (
    SummarizationRepository,
    RepositoryError,
    NotFoundError,
)


@pytest.fixture
async def async_session_maker():
    """创建测试用的异步会话工厂。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def session(async_session_maker):
    """创建测试用的数据库会话。"""
    async with async_session_maker() as session:
        yield session


@pytest.fixture
def sample_summary_record() -> SummaryRecord:
    """创建示例摘要记录。"""
    now = datetime.now(timezone.utc)
    # 使用至少 50 字符的中文文本
    summary_text = "这是一条测试摘要，包含了足够长的内容以满足最小长度要求。" * 2  # 约 42 字 * 2 = 84 字
    return SummaryRecord(
        summary_id=str(uuid4()),
        tweet_id="tweet_123",
        summary_text=summary_text,
        translation_text="This is a test translation with enough content to pass validation.",
        model_provider="openrouter",
        model_name="claude-sonnet-4.5",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        cached=False,
        content_hash="abc123",
        created_at=now,
        updated_at=now,
    )


class TestSummarizationRepository:
    """测试 SummarizationRepository。"""

    @pytest.mark.asyncio
    async def test_save_summary_record_create_new(
        self, session, sample_summary_record
    ):
        """测试创建新的摘要记录。"""
        repository = SummarizationRepository(session)

        # 保存新记录
        result = await repository.save_summary_record(sample_summary_record)

        # 验证返回值
        assert result.summary_id == sample_summary_record.summary_id
        assert result.summary_text == sample_summary_record.summary_text

        # 验证数据库中的记录（使用异步查询）
        from sqlalchemy import select
        stmt = select(SummaryOrm).filter_by(summary_id=sample_summary_record.summary_id)
        db_result = await session.execute(stmt)
        orm_record = db_result.scalar_one()
        assert orm_record is not None
        assert orm_record.tweet_id == "tweet_123"
        assert orm_record.summary_text == sample_summary_record.summary_text

    @pytest.mark.asyncio
    async def test_save_summary_record_update_existing(
        self, session, sample_summary_record
    ):
        """测试更新已存在的摘要记录。"""
        repository = SummarizationRepository(session)

        # 先创建记录
        await repository.save_summary_record(sample_summary_record)

        # 修改记录
        summary_text = "更新后的摘要内容，包含足够长的描述来满足验证要求。" * 2
        updated_record = SummaryRecord(
            summary_id=sample_summary_record.summary_id,
            tweet_id=sample_summary_record.tweet_id,
            summary_text=summary_text,
            translation_text="Updated translation with enough content for validation.",
            model_provider="minimax",
            model_name="abab6.5s-chat",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            cost_usd=0.002,
            cached=True,
            content_hash="xyz789",
            created_at=sample_summary_record.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        # 更新记录
        result = await repository.save_summary_record(updated_record)

        # 验证更新
        assert result.summary_text == summary_text
        assert result.model_provider == "minimax"
        assert result.cached is True

        # 验证数据库中的记录已更新
        from sqlalchemy import select
        stmt = select(SummaryOrm).filter_by(summary_id=sample_summary_record.summary_id)
        db_result = await session.execute(stmt)
        orm_record = db_result.scalar_one()
        assert orm_record.summary_text == summary_text
        assert orm_record.model_provider == "minimax"

    @pytest.mark.asyncio
    async def test_get_summary_by_tweet_exists(
        self, session, sample_summary_record
    ):
        """测试查询存在的推文摘要。"""
        repository = SummarizationRepository(session)

        # 先保存记录
        await repository.save_summary_record(sample_summary_record)

        # 查询记录
        result = await repository.get_summary_by_tweet("tweet_123")

        # 验证结果
        assert result is not None
        assert result.summary_id == sample_summary_record.summary_id
        assert result.tweet_id == "tweet_123"
        assert result.summary_text == sample_summary_record.summary_text

    @pytest.mark.asyncio
    async def test_get_summary_by_tweet_not_exists(self, session):
        """测试查询不存在的推文摘要。"""
        repository = SummarizationRepository(session)

        # 查询不存在的记录
        result = await repository.get_summary_by_tweet("nonexistent_tweet")

        # 验证结果
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cost_stats_no_filters(
        self, session, sample_summary_record
    ):
        """测试获取成本统计（无日期过滤）。"""
        repository = SummarizationRepository(session)

        # 创建多条记录
        await repository.save_summary_record(sample_summary_record)

        summary_text_2 = "这是第二条摘要记录，内容足够长以满足最小长度要求。" * 2
        record2 = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_456",
            summary_text=summary_text_2,
            translation_text=None,
            model_provider="minimax",
            model_name="abab6.5s-chat",
            prompt_tokens=150,
            completion_tokens=75,
            total_tokens=225,
            cost_usd=0.003,
            cached=False,
            content_hash="def456",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await repository.save_summary_record(record2)

        # 获取统计
        stats = await repository.get_cost_stats()

        # 验证统计数据
        assert stats.total_cost_usd == 0.001 + 0.003
        assert stats.total_tokens == 150 + 225
        assert stats.prompt_tokens == 100 + 150
        assert stats.completion_tokens == 50 + 75

        # 验证提供商分解
        assert "openrouter" in stats.provider_breakdown
        assert "minimax" in stats.provider_breakdown
        assert stats.provider_breakdown["openrouter"]["cost_usd"] == 0.001
        assert stats.provider_breakdown["minimax"]["cost_usd"] == 0.003

    @pytest.mark.asyncio
    async def test_get_cost_stats_with_date_filter(self, session):
        """测试获取成本统计（带日期过滤）。"""
        repository = SummarizationRepository(session)

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        # 创建不同日期的记录
        record_old = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_old",
            summary_text="这是一条旧摘要记录，内容足够长以满足最小长度验证要求。" * 2,
            translation_text=None,
            model_provider="openrouter",
            model_name="claude-sonnet-4.5",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.005,
            cached=False,
            content_hash="old123",
            created_at=two_days_ago,
            updated_at=two_days_ago,
        )
        await repository.save_summary_record(record_old)

        record_new = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_new",
            summary_text="这是一条新摘要记录，内容足够长以满足最小长度验证要求。" * 2,
            translation_text=None,
            model_provider="openrouter",
            model_name="claude-sonnet-4.5",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            cost_usd=0.01,
            cached=False,
            content_hash="new123",
            created_at=now,
            updated_at=now,
        )
        await repository.save_summary_record(record_new)

        # 获取最近一天的统计
        start_date = yesterday
        stats = await repository.get_cost_stats(start_date=start_date)

        # 验证只包含新记录
        assert stats.total_cost_usd == 0.01
        assert stats.total_tokens == 300

        # 获取所有时间的统计
        stats_all = await repository.get_cost_stats()
        assert stats_all.total_cost_usd == 0.015
        assert stats_all.total_tokens == 450

    @pytest.mark.asyncio
    async def test_delete_summary_success(
        self, session, sample_summary_record
    ):
        """测试删除摘要记录。"""
        repository = SummarizationRepository(session)

        # 先保存记录
        await repository.save_summary_record(sample_summary_record)

        # 删除记录
        result = await repository.delete_summary(sample_summary_record.summary_id)

        # 验证删除成功
        assert result is True

        # 验证记录已从数据库中删除
        deleted_record = await repository.get_summary_by_tweet("tweet_123")
        assert deleted_record is None

    @pytest.mark.asyncio
    async def test_delete_summary_not_found(self, session):
        """测试删除不存在的摘要记录。"""
        repository = SummarizationRepository(session)

        # 尝试删除不存在的记录
        with pytest.raises(NotFoundError):
            await repository.delete_summary("nonexistent_id")

    @pytest.mark.asyncio
    async def test_find_by_content_hash_cached(
        self, session, sample_summary_record
    ):
        """测试根据内容哈希查询缓存的摘要。"""
        repository = SummarizationRepository(session)

        # 保存缓存记录
        summary_text = "这是一条缓存的摘要记录，内容足够长以满足最小长度验证要求。" * 2
        cached_record = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_cached",
            summary_text=summary_text,
            translation_text=None,
            model_provider="openrouter",
            model_name="claude-sonnet-4.5",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=True,
            content_hash="hash123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await repository.save_summary_record(cached_record)

        # 根据内容哈希查询
        result = await repository.find_by_content_hash("hash123")

        # 验证结果
        assert result is not None
        assert result.content_hash == "hash123"
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_find_by_content_hash_not_cached(self, session):
        """测试根据内容哈希查询非缓存摘要应返回 None。"""
        repository = SummarizationRepository(session)

        # 保存非缓存记录
        summary_text = "这是一条非缓存的摘要记录，内容足够长以满足最小长度验证要求。" * 2
        record = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_not_cached",
            summary_text=summary_text,
            translation_text=None,
            model_provider="openrouter",
            model_name="claude-sonnet-4.5",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            content_hash="hash456",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await repository.save_summary_record(record)

        # 根据内容哈希查询（非缓存应返回 None）
        result = await repository.find_by_content_hash("hash456")

        # 验证结果
        assert result is None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, session):
        """测试事务回滚：异常时数据不污染。"""
        repository = SummarizationRepository(session)

        # 创建一条正常记录
        summary_text = "这是一条正常的摘要记录，内容足够长以满足最小长度验证要求。" * 2
        normal_record = SummaryRecord(
            summary_id=str(uuid4()),
            tweet_id="tweet_normal",
            summary_text=summary_text,
            translation_text=None,
            model_provider="openrouter",
            model_name="claude-sonnet-4.5",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.001,
            cached=False,
            content_hash="normal123",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await repository.save_summary_record(normal_record)

        # 验证正常记录已保存
        result = await repository.get_summary_by_tweet("tweet_normal")
        assert result is not None

        # 模拟删除不存在的记录会触发 NotFoundError
        # 但正常记录应该仍然存在
        try:
            await repository.delete_summary("nonexistent")
        except NotFoundError:
            pass

        # 验证正常记录仍然存在（事务回滚不影响其他操作）
        result = await repository.get_summary_by_tweet("tweet_normal")
        assert result is not None
        assert result.summary_text == summary_text

    @pytest.mark.asyncio
    async def test_save_summary_record_multiple_tweets(
        self, session
    ):
        """测试保存多条推文的摘要。"""
        repository = SummarizationRepository(session)

        # 创建多条记录
        records = []
        for i in range(5):
            summary_text = f"这是第{i}条摘要记录，内容足够长以满足最小长度验证要求。" * 2
            record = SummaryRecord(
                summary_id=str(uuid4()),
                tweet_id=f"tweet_{i}",
                summary_text=summary_text,
                translation_text=None,
                model_provider="openrouter",
                model_name="claude-sonnet-4.5",
                prompt_tokens=100 + i * 10,
                completion_tokens=50 + i * 5,
                total_tokens=150 + i * 15,
                cost_usd=0.001 + i * 0.0001,
                cached=False,
                content_hash=f"hash_{i}",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            records.append(record)
            await repository.save_summary_record(record)

        # 验证所有记录都已保存
        stats = await repository.get_cost_stats()
        assert stats.total_tokens == sum(r.total_tokens for r in records)
        assert stats.total_cost_usd == sum(r.cost_usd for r in records)
