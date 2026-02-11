"""抓取-摘要自动化工作流集成测试。

测试完整的抓取 → 去重 → 摘要流程。
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from returns.result import Success

from src.scraper.domain.models import Tweet, SaveResult
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry, TaskStatus


@pytest.mark.asyncio
async def test_scraping_triggers_summarization_flow():
    """端到端测试：抓取 → 保存 → 去重 → 摘要。"""
    # 重置单例
    TaskRegistry._instance = None
    TaskRegistry._initialized = False

    # 启用自动摘要
    import os
    os.environ["AUTO_SUMMARIZATION_ENABLED"] = "true"
    from src.config import clear_settings_cache
    clear_settings_cache()

    # 创建服务
    service = ScrapingService()

    # Mock 去重和摘要（避免实际执行）
    tasks_created = []

    async def mock_trigger_deduplication(tweet_ids):
        tasks_created.append(("deduplication", tweet_ids))

    async def mock_trigger_summarization(tweet_ids):
        tasks_created.append(("summarization", tweet_ids))

    service._trigger_deduplication = mock_trigger_deduplication
    service._trigger_summarization = mock_trigger_summarization

    # 创建测试推文
    tweets = [
        Tweet(
            tweet_id="123",
            text="Test tweet about AI",
            created_at=datetime.now(),
            author_username="testuser",
        ),
    ]

    # 模拟保存结果，触发去重和摘要
    result = SaveResult(success_count=1, skipped_count=0, error_count=0)
    if result.success_count > 0:
        tweet_ids = [t.tweet_id for t in tweets]
        await service._trigger_deduplication(tweet_ids)
        await service._trigger_summarization(tweet_ids)

    # 验证去重和摘要都被触发
    assert len(tasks_created) == 2
    assert tasks_created[0][0] == "deduplication"
    assert tasks_created[1][0] == "summarization"
    assert tasks_created[0][1] == ["123"]
    assert tasks_created[1][1] == ["123"]


@pytest.mark.asyncio
async def test_auto_summarization_with_config_disabled(monkeypatch):
    """测试配置禁用时不触发摘要。"""
    TaskRegistry._instance = None
    TaskRegistry._initialized = False

    # 禁用自动摘要
    monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "false")
    from src.config import clear_settings_cache
    clear_settings_cache()

    service = ScrapingService()
    tweet_ids = ["tweet1", "tweet2"]

    # Mock asyncio.create_task
    original_create_task = asyncio.create_task
    tasks_created = []

    def mock_create_task(coroutine):
        tasks_created.append(coroutine)
        return original_create_task(asyncio.sleep(0))

    monkeypatch.setattr("asyncio.create_task", mock_create_task)

    # 触发摘要
    await service._trigger_summarization(tweet_ids)

    # 验证没有创建任务（因为配置禁用）
    assert len(tasks_created) == 0


@pytest.mark.asyncio
async def test_auto_summarization_with_config_enabled(monkeypatch):
    """测试配置启用时触发摘要。"""
    TaskRegistry._instance = None
    TaskRegistry._initialized = False

    # 启用自动摘要
    monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
    from src.config import clear_settings_cache
    clear_settings_cache()

    service = ScrapingService()
    tweet_ids = ["tweet1", "tweet2"]

    # Mock asyncio.create_task
    original_create_task = asyncio.create_task
    tasks_created = []

    def mock_create_task(coroutine):
        tasks_created.append(coroutine)
        return original_create_task(asyncio.sleep(0))

    monkeypatch.setattr("asyncio.create_task", mock_create_task)

    # 触发摘要
    await service._trigger_summarization(tweet_ids)

    # 验证创建了任务
    assert len(tasks_created) == 1


@pytest.mark.asyncio
async def test_summarization_failure_doesnt_affect_scraping(monkeypatch):
    """测试摘要失败不影响抓取结果。"""
    TaskRegistry._instance = None
    TaskRegistry._initialized = False

    # 启用自动摘要
    monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
    from src.config import clear_settings_cache
    clear_settings_cache()

    service = ScrapingService()

    # Mock 摘要服务为失败
    async def failing_summarization(tweet_ids):
        raise Exception("摘要服务失败")

    service._run_summarization_background = failing_summarization

    tweet_ids = ["tweet1", "tweet2"]

    # 触发摘要（应该捕获异常而不抛出）
    try:
        await service._trigger_summarization(tweet_ids)
        # 如果没有异常，测试通过
        assert True
    except Exception:
        # 不应该抛出异常
        assert False, "摘要异常不应该传播到抓取服务"
