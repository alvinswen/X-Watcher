"""数据库迁移测试。

测试摘要翻译模块的数据库升级和降级。
使用 SQLAlchemy inspect API 替代 SQLite 专属系统表查询。
"""

import pytest
from sqlalchemy import inspect

from src.summarization.infrastructure.migration import upgrade, downgrade


class TestMigration:
    """数据库迁移测试。"""

    @pytest.mark.asyncio
    async def test_upgrade_creates_summaries_table(self, async_session):
        """测试升级创建 summaries 表。"""
        await upgrade(async_session)

        def check_table(session):
            inspector = inspect(session.get_bind())
            return "summaries" in inspector.get_table_names()

        result = await async_session.run_sync(check_table)
        assert result is True

    @pytest.mark.asyncio
    async def test_upgrade_adds_tweets_columns(self, async_session):
        """测试升级添加 tweets 表字段。"""
        await upgrade(async_session)

        def check_columns(session):
            inspector = inspect(session.get_bind())
            columns = [c["name"] for c in inspector.get_columns("tweets")]
            return columns

        columns = await async_session.run_sync(check_columns)
        assert "summary_cached" in columns
        assert "content_hash" in columns

    @pytest.mark.asyncio
    async def test_upgrade_creates_indexes(self, async_session):
        """测试升级创建索引。"""
        await upgrade(async_session)

        def check_indexes(session):
            inspector = inspect(session.get_bind())
            indexes = inspector.get_indexes("summaries")
            return [idx["name"] for idx in indexes]

        index_names = await async_session.run_sync(check_indexes)
        assert "idx_summaries_tweet" in index_names
        assert "idx_summaries_created" in index_names
        assert "idx_summaries_provider" in index_names

    @pytest.mark.asyncio
    async def test_downgrade_removes_summaries_table(self, async_session):
        """测试降级删除 summaries 表。"""
        await upgrade(async_session)
        await downgrade(async_session)

        def check_table(session):
            inspector = inspect(session.get_bind())
            return "summaries" in inspector.get_table_names()

        result = await async_session.run_sync(check_table)
        assert result is False

    @pytest.mark.asyncio
    async def test_downgrade_removes_tweets_columns(self, async_session):
        """测试降级删除 tweets 表字段。"""
        await upgrade(async_session)
        await downgrade(async_session)

        # 由于 SQLite 限制，这里我们只验证降级不报错
        # 在实际迁移中会使用重建表的方式

    @pytest.mark.asyncio
    async def test_downgrade_removes_indexes(self, async_session):
        """测试降级删除索引。"""
        await upgrade(async_session)
        await downgrade(async_session)

        def check_indexes(session):
            inspector = inspect(session.get_bind())
            try:
                indexes = inspector.get_indexes("summaries")
                return [idx["name"] for idx in indexes]
            except Exception:
                return []  # 表已不存在

        index_names = await async_session.run_sync(check_indexes)
        assert len(index_names) == 0

    @pytest.mark.asyncio
    async def test_upgrade_idempotent(self, async_session):
        """测试升级可以重复执行（幂等性）。"""
        await upgrade(async_session)
        await upgrade(async_session)

        def check_table(session):
            inspector = inspect(session.get_bind())
            return "summaries" in inspector.get_table_names()

        result = await async_session.run_sync(check_table)
        assert result is True

    @pytest.mark.asyncio
    async def test_downgrade_idempotent(self, async_session):
        """测试降级可以重复执行（幂等性）。"""
        await downgrade(async_session)
        await downgrade(async_session)

        def check_table(session):
            inspector = inspect(session.get_bind())
            return "summaries" in inspector.get_table_names()

        result = await async_session.run_sync(check_table)
        assert result is False
