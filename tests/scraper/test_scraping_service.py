"""ScrapingService 单元测试。

测试抓取服务编排功能。
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from returns.result import Failure, Success

from src.scraper.domain.models import SaveResult, Tweet
from src.scraper.scraping_service import ScrapingService
from src.scraper.task_registry import TaskRegistry, TaskStatus


class TestScrapingService:
    """ScrapingService 测试类。"""

    def setup_method(self):
        """每个测试方法前执行：重置单例。"""
        TaskRegistry._instance = None
        TaskRegistry._initialized = False

    @pytest.fixture
    def mock_client(self):
        """Mock TwitterClient。"""
        client = AsyncMock()
        client.fetch_user_tweets = AsyncMock()
        return client

    @pytest.fixture
    def mock_parser(self):
        """Mock TweetParser。"""
        parser = Mock()
        parser.parse_tweet_response = Mock()
        return parser

    @pytest.fixture
    def mock_validator(self):
        """Mock TweetValidator。"""
        validator = Mock()
        validator.validate_and_clean_batch = Mock()
        return validator

    @pytest.fixture
    def mock_repository(self):
        """Mock TweetRepository。"""
        repo = AsyncMock()
        repo.save_tweets = AsyncMock()
        return repo

    @pytest.fixture
    def mock_session(self):
        """Mock 数据库会话。"""
        session = AsyncMock()
        return session

    @pytest.fixture
    def service(
        self, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """创建 ScrapingService 实例。"""
        return ScrapingService(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            repository=mock_repository,
        )

    @pytest.mark.asyncio
    async def test_scrape_single_user_success(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试成功抓取单个用户。"""
        # Mock API 响应
        mock_client.fetch_user_tweets.return_value = Success(
            {
                "data": [
                    {
                        "id": "123",
                        "text": "Test tweet",
                        "created_at": "2024-01-01T12:00:00.000Z",
                        "author_id": "user1",
                    }
                ],
                "includes": {"users": [{"id": "user1", "username": "testuser"}]},
            }
        )

        # Mock 解析器
        tweet = Tweet(
            tweet_id="123",
            text="Test tweet",
            created_at=datetime.now(),
            author_username="testuser",
        )
        mock_parser.parse_tweet_response.return_value = [tweet]

        # Mock 验证器 - 返回 Result 列表
        mock_validator.validate_and_clean_batch.return_value = [Success(tweet)]

        # Mock 仓库
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=1, skipped_count=0, error_count=0
        )

        result = await service.scrape_single_user("testuser", limit=10)

        assert result["username"] == "testuser"
        assert result["fetched"] == 1
        assert result["new"] == 1
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_scrape_single_user_api_error(
        self, service, mock_client, mock_parser
    ):
        """测试 API 错误处理。"""
        from src.scraper.client import TwitterClientError

        mock_client.fetch_user_tweets.return_value = Failure(
            TwitterClientError("API 认证失败", 401)
        )

        result = await service.scrape_single_user("testuser")

        assert result["username"] == "testuser"
        assert result["success"] is False
        assert result["errors"] == 1
        assert "API 认证失败" in result["error_message"]

    @pytest.mark.asyncio
    async def test_scrape_single_user_parse_error(
        self, service, mock_client, mock_parser
    ):
        """测试解析错误处理。"""
        mock_client.fetch_user_tweets.return_value = Success({})

        # 解析器返回空列表
        mock_parser.parse_tweet_response.return_value = []

        result = await service.scrape_single_user("testuser")

        assert result["username"] == "testuser"
        assert result["fetched"] == 0
        assert result["success"] is True  # 空结果不算失败

    @pytest.mark.asyncio
    async def test_scrape_users_multiple(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试抓取多个用户。"""
        # Mock API 响应
        mock_client.fetch_user_tweets.return_value = Success(
            {
                "data": [
                    {
                        "id": "123",
                        "text": "Test tweet",
                        "created_at": "2024-01-01T12:00:00.000Z",
                        "author_id": "user1",
                    }
                ],
                "includes": {"users": [{"id": "user1", "username": "testuser"}]},
            }
        )

        tweet = Tweet(
            tweet_id="123",
            text="Test tweet",
            created_at=datetime.now(),
            author_username="testuser",
        )
        mock_parser.parse_tweet_response.return_value = [tweet]
        mock_validator.validate_and_clean_batch.return_value = [Success(tweet)]
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=1, skipped_count=0, error_count=0
        )

        task_id = await service.scrape_users(["user1", "user2"], limit=10)

        assert task_id is not None

        # 验证任务状态
        registry = TaskRegistry.get_instance()
        status = registry.get_task_status(task_id)
        assert status is not None
        assert status["status"] == TaskStatus.COMPLETED
        assert status["result"]["total_users"] == 2
        assert status["result"]["total_tweets"] == 2
        assert status["result"]["new_tweets"] == 2

    @pytest.mark.asyncio
    async def test_scrape_users_concurrent_limit(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试并发控制。"""
        # 创建带并发限制的服务
        service = ScrapingService(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            repository=mock_repository,
            max_concurrent=2,
        )

        mock_client.fetch_user_tweets.return_value = Success(
            {"data": [], "includes": {"users": []}}
        )
        mock_parser.parse_tweet_response.return_value = []
        mock_validator.validate_and_clean_batch.return_value = []

        # 抓取 5 个用户
        task_id = await service.scrape_users(
            ["user1", "user2", "user3", "user4", "user5"]
        )

        assert task_id is not None

        status = TaskRegistry.get_instance().get_task_status(task_id)
        assert status["status"] == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_scrape_users_partial_failure(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试部分用户失败不影响其他用户。"""
        call_count = 0

        async def mock_fetch(username, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # 第二个用户失败
                from src.scraper.client import TwitterClientError

                return Failure(TwitterClientError("用户不存在", 404))
            return Success({"data": [], "includes": {"users": []}})

        mock_client.fetch_user_tweets = mock_fetch
        mock_parser.parse_tweet_response.return_value = []
        mock_validator.validate_and_clean_batch.return_value = []

        task_id = await service.scrape_users(["user1", "user2", "user3"])

        assert task_id is not None

        status = TaskRegistry.get_instance().get_task_status(task_id)
        assert status["status"] == TaskStatus.COMPLETED
        assert status["result"]["total_users"] == 3
        assert status["result"]["failed_users"] == 1

    @pytest.mark.asyncio
    async def test_scrape_users_with_task_id(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试使用指定 task_id。"""
        mock_client.fetch_user_tweets.return_value = Success(
            {"data": [], "includes": {"users": []}}
        )
        mock_parser.parse_tweet_response.return_value = []
        mock_validator.validate_and_clean_batch.return_value = []

        custom_task_id = "custom-task-123"
        task_id = await service.scrape_users(["user1"], task_id=custom_task_id)

        assert task_id == custom_task_id

    @pytest.mark.asyncio
    async def test_scrape_users_empty_list(self, service):
        """测试空用户列表。"""
        task_id = await service.scrape_users([])

        assert task_id is not None

        status = TaskRegistry.get_instance().get_task_status(task_id)
        assert status["status"] == TaskStatus.COMPLETED
        assert status["result"]["total_users"] == 0

    @pytest.mark.asyncio
    async def test_scrape_single_user_with_since_id(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试使用 since_id 参数。"""
        mock_client.fetch_user_tweets.return_value = Success(
            {"data": [], "includes": {"users": []}}
        )
        mock_parser.parse_tweet_response.return_value = []
        mock_validator.validate_and_clean_batch.return_value = []

        await service.scrape_single_user("testuser", since_id="123456")

        # 验证 since_id 被传递
        mock_client.fetch_user_tweets.assert_called_once()
        call_kwargs = mock_client.fetch_user_tweets.call_args[1]
        assert call_kwargs["since_id"] == "123456"

    @pytest.mark.asyncio
    async def test_scrape_single_user_deduplication(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试去重逻辑。"""
        mock_client.fetch_user_tweets.return_value = Success(
            {
                "data": [
                    {
                        "id": "123",
                        "text": "Test tweet",
                        "created_at": "2024-01-01T12:00:00.000Z",
                        "author_id": "user1",
                    }
                ],
                "includes": {"users": [{"id": "user1", "username": "testuser"}]},
            }
        )

        tweet = Tweet(
            tweet_id="123",
            text="Test tweet",
            created_at=datetime.now(),
            author_username="testuser",
        )
        mock_parser.parse_tweet_response.return_value = [tweet]
        mock_validator.validate_and_clean_batch.return_value = [Success(tweet)]

        # 模拟推文已存在
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=0, skipped_count=1, error_count=0
        )

        result = await service.scrape_single_user("testuser")

        assert result["fetched"] == 1
        assert result["new"] == 0
        assert result["skipped"] == 1


class TestAutoSummarization:
    """测试自动摘要功能。"""

    def setup_method(self):
        """每个测试方法前执行：重置单例。"""
        TaskRegistry._instance = None
        TaskRegistry._initialized = False

    @pytest.fixture
    def mock_repository(self):
        """Mock TweetRepository。"""
        repo = AsyncMock()
        repo.save_tweets = AsyncMock()
        return repo

    @pytest.fixture
    def service(self, mock_repository):
        """创建 ScrapingService 实例。"""
        return ScrapingService(repository=mock_repository)

    @pytest.mark.asyncio
    async def test_auto_summarization_disabled_skips_trigger(self, service, monkeypatch):
        """测试禁用自动摘要时不触发。"""
        # 禁用自动摘要
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "false")
        from src.config import clear_settings_cache
        clear_settings_cache()

        tweet_ids = ["tweet1", "tweet2"]

        # Mock asyncio.create_task 以验证是否被调用
        import asyncio
        original_create_task = asyncio.create_task
        create_task_called = []

        def mock_create_task(coroutine):
            create_task_called.append(True)
            # 返回一个模拟的 Task
            task = original_create_task(
                asyncio.sleep(0)  # 空协程
            )
            return task

        monkeypatch.setattr("asyncio.create_task", mock_create_task)

        # 触发摘要
        await service._trigger_summarization(tweet_ids)

        # 验证 create_task 没有被调用（因为配置禁用）
        assert len(create_task_called) == 0

    @pytest.mark.asyncio
    async def test_empty_tweet_list_skips_summarization(self, service, monkeypatch):
        """测试空推文列表跳过摘要。"""
        # 启用自动摘要
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        # Mock asyncio.create_task
        import asyncio
        original_create_task = asyncio.create_task
        create_task_called = []

        def mock_create_task(coroutine):
            create_task_called.append(True)
            task = original_create_task(asyncio.sleep(0))
            return task

        monkeypatch.setattr("asyncio.create_task", mock_create_task)

        # 触发摘要（空列表）
        await service._trigger_summarization([])

        # 验证 create_task 没有被调用
        assert len(create_task_called) == 0

    @pytest.mark.asyncio
    async def test_auto_summarization_triggered_with_tweets(self, service, monkeypatch):
        """测试有推文时触发摘要。"""
        # 启用自动摘要
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        tweet_ids = ["tweet1", "tweet2"]

        # Mock asyncio.create_task
        import asyncio
        original_create_task = asyncio.create_task
        create_task_called_with = []

        def mock_create_task(coroutine):
            create_task_called_with.append(True)
            task = original_create_task(asyncio.sleep(0))
            return task

        monkeypatch.setattr("asyncio.create_task", mock_create_task)

        # 触发摘要
        await service._trigger_summarization(tweet_ids)

        # 验证 create_task 被调用
        assert len(create_task_called_with) == 1

    @pytest.mark.asyncio
    async def test_save_tweets_triggers_summarization(
        self, service, mock_repository, monkeypatch
    ):
        """测试保存推文后触发摘要。"""
        # 启用自动摘要
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        # Mock 保存结果
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=2, skipped_count=0, error_count=0
        )

        # Mock _trigger_summarization
        trigger_summarization_called = []

        async def mock_trigger_summarization(tweet_ids):
            trigger_summarization_called.append(tweet_ids)

        service._trigger_summarization = mock_trigger_summarization

        # 创建测试推文
        tweets = [
            Tweet(
                tweet_id="tweet1",
                text="Test 1",
                created_at=datetime.now(),
                author_username="user1",
            ),
            Tweet(
                tweet_id="tweet2",
                text="Test 2",
                created_at=datetime.now(),
                author_username="user2",
            ),
        ]

        # 保存推文
        await service._save_tweets(tweets)

        # 验证摘要被触发
        assert len(trigger_summarization_called) == 1
        assert set(trigger_summarization_called[0]) == {"tweet1", "tweet2"}
