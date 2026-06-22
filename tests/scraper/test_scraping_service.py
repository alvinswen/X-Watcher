"""ScrapingService 单元测试。

测试抓取服务编排功能。
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from returns.result import Failure, Success

from src.scraper.domain.models import Article, ArticlePreview, SaveResult, Tweet
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
    async def test_scrape_single_user_skip_existing(
        self, service, mock_client, mock_parser, mock_validator, mock_repository
    ):
        """测试跳过已存在推文。"""
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
        """测试有推文时触发摘要（通过 SummarizationQueue.enqueue）。"""
        # 启用自动摘要
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        tweet_ids = ["tweet1", "tweet2"]

        # Mock SummarizationQueue
        import asyncio

        mock_queue = Mock()
        mock_queue.enqueue = AsyncMock(return_value="task-123")
        mock_queue._loop = asyncio.get_event_loop()

        with patch(
            "src.summarization.services.summarization_queue.SummarizationQueue.get_instance",
            return_value=mock_queue,
        ):
            # 触发摘要
            await service._trigger_summarization(tweet_ids)

        # 验证 enqueue 被调用
        mock_queue.enqueue.assert_called_once()
        call_args = mock_queue.enqueue.call_args
        assert call_args[0][0] == tweet_ids
        assert call_args[1]["source"] == "scraping"

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
            success_count=2, skipped_count=0, error_count=0,
            saved_tweet_ids=["tweet1", "tweet2"],
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

    @pytest.mark.asyncio
    async def test_save_tweets_skips_summarization_when_flag_set(
        self, mock_repository, monkeypatch
    ):
        """测试 skip_summarization=True 时不触发摘要。"""
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        # 创建 skip_summarization=True 的 service
        service = ScrapingService(
            repository=mock_repository,
            skip_summarization=True,
        )

        mock_repository.save_tweets.return_value = SaveResult(
            success_count=2, skipped_count=0, error_count=0,
            saved_tweet_ids=["tweet1", "tweet2"],
        )

        trigger_summarization_called = []

        async def mock_trigger_summarization(tweet_ids):
            trigger_summarization_called.append(tweet_ids)

        service._trigger_summarization = mock_trigger_summarization

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

        await service._save_tweets(tweets)

        # skip_summarization=True 时不应触发摘要
        assert len(trigger_summarization_called) == 0

    @pytest.mark.asyncio
    async def test_skip_summarization_default_false(
        self, service, mock_repository, monkeypatch
    ):
        """测试 skip_summarization 默认为 False，仍然触发摘要。"""
        monkeypatch.setenv("AUTO_SUMMARIZATION_ENABLED", "true")
        from src.config import clear_settings_cache
        clear_settings_cache()

        mock_repository.save_tweets.return_value = SaveResult(
            success_count=1, skipped_count=0, error_count=0,
            saved_tweet_ids=["tweet1"],
        )

        trigger_summarization_called = []

        async def mock_trigger_summarization(tweet_ids):
            trigger_summarization_called.append(tweet_ids)

        service._trigger_summarization = mock_trigger_summarization

        tweets = [
            Tweet(
                tweet_id="tweet1",
                text="Test 1",
                created_at=datetime.now(),
                author_username="user1",
            ),
        ]

        await service._save_tweets(tweets)

        # 默认 skip_summarization=False 应触发摘要
        assert len(trigger_summarization_called) == 1


class TestAdditionalPages:
    """满页翻页机制测试。"""

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
    def service(self, mock_client, mock_parser, mock_validator, mock_repository):
        """创建 ScrapingService 实例。"""
        return ScrapingService(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            repository=mock_repository,
        )

    @pytest.mark.asyncio
    async def test_additional_pages_triggered_when_full_page(
        self, service, mock_client, mock_parser, mock_validator, mock_repository,
        monkeypatch,
    ):
        """测试满页时触发翻页。"""
        monkeypatch.setenv("SCRAPER_MAX_EXTRA_PAGES", "2")
        from src.config import clear_settings_cache
        clear_settings_cache()

        # 第一页：返回 10 条全新推文 + next_cursor
        tweets_page1 = [
            Tweet(
                tweet_id=f"t{i}",
                text=f"Tweet {i}",
                created_at=datetime.now(),
                author_username="testuser",
            )
            for i in range(10)
        ]

        # 第一页 API 响应（全新推文 + next_cursor）
        mock_client.fetch_user_tweets.side_effect = [
            # 第一页
            Success({
                "data": [{"id": f"t{i}", "text": f"T{i}", "created_at": "2024-01-01T12:00:00Z", "author_id": "u1"} for i in range(10)],
                "includes": {"users": [{"id": "u1", "username": "testuser"}]},
                "next_cursor": "cursor_p2",
            }),
            # 第二页（翻页）- 返回大量已存在推文
            Success({
                "data": [{"id": f"old{i}", "text": f"Old{i}", "created_at": "2024-01-01T12:00:00Z", "author_id": "u1"} for i in range(5)],
                "includes": {"users": [{"id": "u1", "username": "testuser"}]},
            }),
        ]

        mock_parser.parse_tweet_response.side_effect = [
            tweets_page1,
            [Tweet(tweet_id=f"old{i}", text=f"Old{i}", created_at=datetime.now(), author_username="testuser") for i in range(5)],
        ]

        mock_validator.validate_and_clean_batch.side_effect = [
            [Success(t) for t in tweets_page1],
            [Success(Tweet(tweet_id=f"old{i}", text=f"Old{i}", created_at=datetime.now(), author_username="testuser")) for i in range(5)],
        ]

        mock_repository.save_tweets.side_effect = [
            SaveResult(success_count=10, skipped_count=0, error_count=0),  # 第一页全新
            SaveResult(success_count=0, skipped_count=5, error_count=0),   # 第二页全跳过
        ]

        with patch("src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock):
            result = await service.scrape_single_user("testuser")

        assert result["success"] is True
        assert result["new"] == 10
        assert result["skipped"] == 5
        assert result["fetched"] == 15

    @pytest.mark.asyncio
    async def test_additional_pages_not_triggered_when_many_skips(
        self, service, mock_client, mock_parser, mock_validator, mock_repository,
        monkeypatch,
    ):
        """测试第一页有大量跳过时不触发翻页。"""
        monkeypatch.setenv("SCRAPER_MAX_EXTRA_PAGES", "3")
        from src.config import clear_settings_cache
        clear_settings_cache()

        tweets = [
            Tweet(tweet_id=f"t{i}", text=f"T{i}", created_at=datetime.now(), author_username="u")
            for i in range(10)
        ]

        mock_client.fetch_user_tweets.return_value = Success({
            "data": [{"id": f"t{i}"} for i in range(10)],
            "next_cursor": "cursor_p2",
        })
        mock_parser.parse_tweet_response.return_value = tweets
        mock_validator.validate_and_clean_batch.return_value = [Success(t) for t in tweets]
        # 第一页只有 2 条新推文（低于 80%），不应翻页
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=2, skipped_count=8, error_count=0,
        )

        result = await service.scrape_single_user("u")

        assert result["success"] is True
        assert result["new"] == 2
        # fetch_user_tweets 只被调用了 1 次（没有翻页）
        assert mock_client.fetch_user_tweets.call_count == 1

    @pytest.mark.asyncio
    async def test_scrape_additional_pages_stops_on_high_skip_rate(
        self, service, mock_client, mock_parser, mock_validator, mock_repository,
    ):
        """测试 _scrape_additional_pages 在跳过率 >80% 时停止。"""
        tweets = [
            Tweet(tweet_id=f"old{i}", text=f"Old{i}", created_at=datetime.now(), author_username="u")
            for i in range(10)
        ]

        mock_client.fetch_user_tweets.return_value = Success({
            "data": [{"id": f"old{i}"} for i in range(10)],
        })
        mock_parser.parse_tweet_response.return_value = tweets
        mock_validator.validate_and_clean_batch.return_value = [Success(t) for t in tweets]
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=1, skipped_count=9, error_count=0,
        )

        with patch("src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock):
            result = await service._scrape_additional_pages(
                username="u",
                next_cursor="cursor_2",
                max_extra_pages=5,
            )

        assert result["new"] == 1
        assert result["skipped"] == 9
        # 只翻了 1 页就因为高跳过率停止
        assert mock_client.fetch_user_tweets.call_count == 1


class TestBackfillUser:
    """全量回溯测试。"""

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
    def service(self, mock_client, mock_parser, mock_validator, mock_repository):
        """创建 ScrapingService 实例。"""
        return ScrapingService(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            repository=mock_repository,
        )

    @pytest.mark.asyncio
    async def test_backfill_user_success(
        self, service, mock_client, mock_parser, mock_validator, mock_repository,
    ):
        """测试全量回溯成功场景。"""
        tweets_p1 = [
            Tweet(tweet_id=f"t{i}", text=f"T{i}", created_at=datetime.now(), author_username="u")
            for i in range(20)
        ]
        tweets_p2 = [
            Tweet(tweet_id=f"t{i}", text=f"T{i}", created_at=datetime.now(), author_username="u")
            for i in range(20, 35)
        ]

        # 模拟 2 页分页响应
        async def mock_paginated(username, *, max_pages=10, page_delay=1.0):
            yield {
                "data": [{"id": f"t{i}"} for i in range(20)],
                "next_cursor": "cursor_2",
            }
            yield {
                "data": [{"id": f"t{i}"} for i in range(20, 35)],
            }

        mock_client.fetch_user_tweets_paginated = mock_paginated

        mock_parser.parse_tweet_response.side_effect = [tweets_p1, tweets_p2]
        mock_validator.validate_and_clean_batch.side_effect = [
            [Success(t) for t in tweets_p1],
            [Success(t) for t in tweets_p2],
        ]
        mock_repository.save_tweets.side_effect = [
            SaveResult(success_count=20, skipped_count=0, error_count=0),
            SaveResult(success_count=15, skipped_count=0, error_count=0),
        ]

        # Mock _update_backfill_status
        status_updates = []
        async def mock_update_status(username, status, completed_at=None):
            status_updates.append((username, status))

        service._update_backfill_status = mock_update_status

        result = await service.backfill_user("u")

        assert result["success"] is True
        assert result["pages"] == 2
        assert result["fetched"] == 35
        assert result["new"] == 35
        assert result["skipped"] == 0
        # 验证状态流转: running → completed
        assert status_updates == [("u", "running"), ("u", "completed")]

    @pytest.mark.asyncio
    async def test_backfill_user_stops_on_high_skip_rate(
        self, service, mock_client, mock_parser, mock_validator, mock_repository,
    ):
        """测试回溯在跳过率 >80% 时提前停止。"""
        tweets = [
            Tweet(tweet_id=f"old{i}", text=f"Old{i}", created_at=datetime.now(), author_username="u")
            for i in range(10)
        ]

        # 模拟分页响应（3 页，但应在第 1 页就停止）
        async def mock_paginated(username, *, max_pages=10, page_delay=1.0):
            for page in range(3):
                yield {
                    "data": [{"id": f"old{page}_{i}"} for i in range(10)],
                    "next_cursor": f"cursor_{page + 1}" if page < 2 else None,
                }

        mock_client.fetch_user_tweets_paginated = mock_paginated

        mock_parser.parse_tweet_response.return_value = tweets
        mock_validator.validate_and_clean_batch.return_value = [Success(t) for t in tweets]
        # 第一页 90% 已存在
        mock_repository.save_tweets.return_value = SaveResult(
            success_count=1, skipped_count=9, error_count=0,
        )

        status_updates = []
        async def mock_update_status(username, status, completed_at=None):
            status_updates.append((username, status))

        service._update_backfill_status = mock_update_status

        result = await service.backfill_user("u")

        assert result["success"] is True
        assert result["pages"] == 1  # 第一页就停止了
        assert result["new"] == 1
        assert result["skipped"] == 9
        assert status_updates == [("u", "running"), ("u", "completed")]

    @pytest.mark.asyncio
    async def test_backfill_user_resets_on_error(
        self, service, mock_client,
    ):
        """测试回溯失败时重置状态为 pending。"""
        # 模拟分页迭代器抛出异常
        async def mock_paginated(username, *, max_pages=10, page_delay=1.0):
            raise RuntimeError("API connection lost")
            yield  # noqa: unreachable - 保持为异步生成器

        mock_client.fetch_user_tweets_paginated = mock_paginated

        status_updates = []
        async def mock_update_status(username, status, completed_at=None):
            status_updates.append((username, status))

        service._update_backfill_status = mock_update_status

        result = await service.backfill_user("u")

        assert result["success"] is False
        assert result["pages"] == 0
        # 验证状态流转: running → pending（失败回退）
        assert status_updates == [("u", "running"), ("u", "pending")]


class TestArticleFetching:
    """X Articles 获取测试。"""

    def setup_method(self):
        """每个测试方法前执行：重置单例。"""
        TaskRegistry._instance = None
        TaskRegistry._initialized = False

    @pytest.fixture(autouse=True)
    def _pin_sqlalchemy_layer(self, monkeypatch):
        """钉 sqlalchemy 模式:本组按 ArticleRepository + get_async_session_maker 的
        mock 编写,走真 session 路径,不受本地 .env 的 XWATCHER_DATA_LAYER=file 污染
        (否则 get_article_repo 经 provider 返回 FileArticleStore、绕过 patch →
        article_exists 落到真仓返回真值 → fetch_article 永不触发)。"""
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")

    @pytest.fixture
    def mock_client(self):
        """Mock TwitterClient。"""
        client = AsyncMock()
        client.fetch_user_tweets = AsyncMock()
        client.fetch_article = AsyncMock()
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
    def service(self, mock_client, mock_parser, mock_validator, mock_repository):
        """创建 ScrapingService 实例。"""
        return ScrapingService(
            client=mock_client,
            parser=mock_parser,
            validator=mock_validator,
            repository=mock_repository,
        )

    @pytest.mark.asyncio
    async def test_fetch_and_save_articles_success(
        self, service, mock_client,
    ):
        """测试通过 has_article 检测并成功保存 Article。"""
        tweets = [
            Tweet(
                tweet_id="t1",
                text="https://t.co/abc123",
                created_at=datetime.now(),
                author_username="user",
                article_preview=ArticlePreview(
                    title="My Great Article",
                    preview_text="Preview...",
                    cover_media_img_url="https://pbs.twimg.com/cover.jpg",
                ),
            ),
            Tweet(
                tweet_id="t2",
                text="Normal tweet without article",
                created_at=datetime.now(),
                author_username="user",
            ),
        ]

        mock_client.fetch_article.return_value = Success({
            "article": {
                "title": "My Great Article",
                "preview_text": "Preview...",
                "cover_media_img_url": "https://pbs.twimg.com/cover.jpg",
                "contents": [
                    {"text": "Paragraph 1"},
                    {"text": "Paragraph 2"},
                ],
            },
        })

        # Mock ArticleRepository
        mock_article_repo = AsyncMock()
        mock_article_repo.save_article = AsyncMock(return_value=True)
        mock_article_repo.article_exists = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        mock_session_maker = Mock(return_value=mock_session)

        with (
            patch("src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "src.scraper.infrastructure.article_repository.ArticleRepository",
                return_value=mock_article_repo,
            ),
        ):
            await service._fetch_and_save_articles(tweets)

        # 只有 t1 有 article_preview，所以 fetch_article 只调用 1 次
        mock_client.fetch_article.assert_called_once_with("t1")

    @pytest.mark.asyncio
    async def test_fetch_article_api_failure_fallback_to_preview(
        self, service, mock_client,
    ):
        """测试 Article API 失败时 fallback 到预览信息保存。"""
        from src.scraper.client import TwitterClientError

        tweets = [
            Tweet(
                tweet_id="t1",
                text="https://t.co/abc123",
                created_at=datetime.now(),
                author_username="testuser",
                article_preview=ArticlePreview(
                    title="Fallback Title",
                    preview_text="Fallback preview",
                    cover_media_img_url=None,
                ),
            ),
        ]

        mock_client.fetch_article.return_value = Failure(
            TwitterClientError("API error", status_code=500)
        )

        # Mock ArticleRepository
        mock_article_repo = AsyncMock()
        mock_article_repo.save_article = AsyncMock(return_value=True)
        mock_article_repo.article_exists = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        mock_session_maker = Mock(return_value=mock_session)

        with (
            patch("src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "src.scraper.infrastructure.article_repository.ArticleRepository",
                return_value=mock_article_repo,
            ),
        ):
            await service._fetch_and_save_articles(tweets)

        # 验证 save_article 被调用（使用预览信息 fallback）
        mock_article_repo.save_article.assert_called_once()
        saved_article = mock_article_repo.save_article.call_args[0][0]
        assert saved_article.title == "Fallback Title"
        assert saved_article.preview_text == "Fallback preview"
        assert saved_article.content is None  # API 失败，无全文

    @pytest.mark.asyncio
    async def test_no_articles_skips_fetch(self, service, mock_client):
        """测试无 has_article 时不调用 API。"""
        tweets = [
            Tweet(
                tweet_id="t1",
                text="Just a normal tweet",
                created_at=datetime.now(),
                author_username="u",
            ),
        ]

        await service._fetch_and_save_articles(tweets)

        # fetch_article 不应被调用
        mock_client.fetch_article.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_and_save_articles_skips_existing(
        self, service, mock_client,
    ):
        """测试已存在的 article 不重复保存。"""
        tweets = [
            Tweet(
                tweet_id="t_existing",
                text="https://t.co/existing",
                created_at=datetime.now(),
                author_username="user",
                article_preview=ArticlePreview(title="Existing"),
            ),
        ]

        # Mock ArticleRepository 报告已存在
        mock_article_repo = AsyncMock()
        mock_article_repo.article_exists = AsyncMock(return_value=True)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_maker = Mock(return_value=mock_session)

        with (
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "src.scraper.infrastructure.article_repository.ArticleRepository",
                return_value=mock_article_repo,
            ),
        ):
            await service._fetch_and_save_articles(tweets)

        # article 已存在，不应调用 fetch_article
        mock_client.fetch_article.assert_not_called()


class TestBackfillArticlesForUser:
    """backfill_articles_for_user 测试。"""

    def setup_method(self):
        """每个测试方法前执行：重置单例。"""
        TaskRegistry._instance = None
        TaskRegistry._initialized = False

    @pytest.fixture(autouse=True)
    def _pin_sqlalchemy_layer(self, monkeypatch):
        """钉 sqlalchemy 模式:本组按 ArticleRepository + get_async_session_maker 的
        mock 编写,走真 session 路径,不受本地 .env 的 XWATCHER_DATA_LAYER=file 污染
        (否则 get_article_repo 经 provider 返回 FileArticleStore、绕过 patch)。"""
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")

    @pytest.fixture
    def mock_client(self):
        """Mock TwitterClient。"""
        client = AsyncMock()
        client.fetch_article = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_client):
        """创建 ScrapingService 实例。"""
        return ScrapingService(
            client=mock_client,
            parser=Mock(),
            validator=Mock(),
            repository=AsyncMock(),
        )

    @pytest.mark.asyncio
    async def test_backfill_finds_articles(self, service, mock_client):
        """测试回溯发现并保存 Article。"""
        # Mock DB 查询返回推文 ID（不 mock TweetOrm/ArticleOrm，让 select() 正常构建）
        mock_rows = [("tweet_001",), ("tweet_002",)]

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=mock_rows)
        mock_session.commit = AsyncMock()

        mock_session_maker = Mock(return_value=mock_session)

        # Mock ArticleRepository
        mock_article_repo = AsyncMock()
        mock_article_repo.save_article = AsyncMock(return_value=True)

        # tweet_001 是 Article，tweet_002 不是（404）
        from src.scraper.client import TwitterClientError
        mock_client.fetch_article.side_effect = [
            Success({
                "article": {
                    "title": "Found Article",
                    "preview_text": "Preview...",
                    "contents": [{"text": "Paragraph 1"}],
                },
            }),
            Failure(TwitterClientError("资源未找到", status_code=404)),
        ]

        with (
            patch("src.scraper.scraping_service.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "src.database.async_session.get_async_session_maker",
                return_value=mock_session_maker,
            ),
            patch(
                "src.scraper.infrastructure.article_repository.ArticleRepository",
                return_value=mock_article_repo,
            ),
        ):
            result = await service.backfill_articles_for_user("testuser", max_tweets=10)

        assert result["checked"] == 2
        assert result["found"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_backfill_no_tweets(self, service, mock_client):
        """测试用户无推文时直接返回。"""
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock(return_value=[])  # 空结果

        mock_session_maker = Mock(return_value=mock_session)

        with patch(
            "src.database.async_session.get_async_session_maker",
            return_value=mock_session_maker,
        ):
            result = await service.backfill_articles_for_user("emptyuser")

        assert result["checked"] == 0
        assert result["found"] == 0
        mock_client.fetch_article.assert_not_called()
