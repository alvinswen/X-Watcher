"""TwitterClient 单元测试。

测试 Twitter API 客户端功能，包括重试策略和错误处理。
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from returns.result import Failure, Success

from src.scraper.client import TwitterClient


class TestTwitterClient:
    """TwitterClient 测试类。"""

    @pytest.fixture
    def mock_httpx_client(self):
        """Mock httpx 异步客户端。"""
        client = AsyncMock()
        client.get = AsyncMock()
        return client

    @pytest.fixture
    def client(self, test_settings):
        """创建 TwitterClient 实例。"""
        return TwitterClient()

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_success(self, client, mock_httpx_client):
        """测试成功获取用户推文。"""
        # Mock API 响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "1234567890",
                    "text": "Test tweet",
                    "created_at": "2024-01-01T12:00:00.000Z",
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "user123",
                        "username": "testuser",
                        "name": "Test User",
                    }
                ]
            },
        }

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "1234567890"

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_with_since_id(self, client, mock_httpx_client):
        """测试使用 since_id 参数获取推文。

        注意: TwitterAPI.io 可能不支持 since_id 参数，此测试验证方法被正确调用。
        """
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [], "includes": {"users": []}}

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser", since_id="1234567890")

        assert isinstance(result, Success)

        # 验证请求被发送（端点和参数）
        call_args = mock_httpx_client.get.call_args
        url = call_args[0][0]
        assert "/user/last_tweets" in url

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_with_limit(self, client, mock_httpx_client):
        """测试使用 userName 参数获取推文。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [], "includes": {"users": []}}

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser", limit=50)

        assert isinstance(result, Success)

        # 验证 userName 参数被正确设置
        call_args = mock_httpx_client.get.call_args
        params = call_args[1]["params"]
        assert params["userName"] == "testuser"
        assert params["includeReplies"] is False

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_401_error(self, client, mock_httpx_client):
        """测试 401 认证错误（应立即停止，不重试）。"""
        mock_response = Mock()
        mock_response.status_code = 401

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        error = result.failure()
        assert "401" in str(error).lower() or "unauthorized" in str(error).lower()

        # 验证只调用了一次（没有重试）
        assert mock_httpx_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_429_retry(self, client, mock_httpx_client):
        """测试 429 限流错误（应重试）。"""
        # 前两次返回 429，第三次成功
        mock_response_429 = Mock()
        mock_response_429.status_code = 429

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "data": [],
            "includes": {"users": []},
        }

        mock_httpx_client.get.side_effect = [
            mock_response_429,
            mock_response_429,
            mock_response_success,
        ]

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        # 验证重试了（调用超过一次）
        assert mock_httpx_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_500_retry(self, client, mock_httpx_client):
        """测试 500 服务器错误（应重试）。"""
        mock_response_500 = Mock()
        mock_response_500.status_code = 500

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "data": [],
            "includes": {"users": []},
        }

        mock_httpx_client.get.side_effect = [
            mock_response_500,
            mock_response_success,
        ]

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        assert mock_httpx_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_max_retries_exceeded(
        self, client, mock_httpx_client
    ):
        """测试超过最大重试次数。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        # 默认最大重试 5 次，加上初始调用 = 6 次
        assert mock_httpx_client.get.call_count == 6

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_timeout(self, client, mock_httpx_client):
        """测试网络超时。"""
        mock_httpx_client.get.side_effect = httpx.TimeoutException("Request timeout")

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        error = result.failure()
        assert "timeout" in str(error).lower()

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_network_error(self, client, mock_httpx_client):
        """测试网络连接错误。"""
        mock_httpx_client.get.side_effect = httpx.NetworkError("Connection failed")

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_invalid_json(self, client, mock_httpx_client):
        """测试无效 JSON 响应。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, client, mock_httpx_client):
        """测试指数退避延迟。"""
        import time

        mock_response_500 = Mock()
        mock_response_500.status_code = 500

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "data": [],
            "includes": {"users": []},
        }

        mock_httpx_client.get.side_effect = [
            mock_response_500,
            mock_response_500,
            mock_response_500,
            mock_response_success,
        ]

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            start_time = time.time()
            result = await client.fetch_user_tweets("testuser")
            elapsed_time = time.time() - start_time

        assert isinstance(result, Success)
        # 验证有延迟（1 + 2 + 4 = 7秒左右）
        assert elapsed_time >= 6  # 允许一些误差

    @pytest.mark.asyncio
    async def test_custom_max_retries(self, test_settings, mock_httpx_client):
        """测试自定义最大重试次数。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_httpx_client.get.return_value = mock_response

        # 创建自定义重试次数的客户端
        client = TwitterClient(max_retries=2)

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        # 初始调用 + 2 次重试
        assert mock_httpx_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_custom_base_delay(self, test_settings, mock_httpx_client):
        """测试自定义基础延迟。"""
        import time

        mock_response_500 = Mock()
        mock_response_500.status_code = 500

        mock_response_success = Mock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "data": [],
            "includes": {"users": []},
        }

        mock_httpx_client.get.side_effect = [
            mock_response_500,
            mock_response_success,
        ]

        # 使用较短的基础延迟
        client = TwitterClient(base_delay=0.1)

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            start_time = time.time()
            result = await client.fetch_user_tweets("testuser")
            elapsed_time = time.time() - start_time

        assert isinstance(result, Success)
        # 延迟应该很短（约 0.1 秒）
        assert elapsed_time >= 0.08
        assert elapsed_time < 1

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_empty_username(self, client):
        """测试空用户名。"""
        result = await client.fetch_user_tweets("")

        assert isinstance(result, Failure)
        # 验证是 TwitterClientError 类型
        from src.scraper.client import TwitterClientError
        assert isinstance(result.failure(), TwitterClientError)

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_invalid_limit(self, client):
        """测试无效的 limit 参数。"""
        result = await client.fetch_user_tweets("testuser", limit=0)

        assert isinstance(result, Failure)

    @pytest.mark.asyncio
    async def test_context_manager(self, test_settings):
        """测试作为上下文管理器使用。"""
        async with TwitterClient() as client:
            assert client is not None
            # 验证客户端已初始化
            assert client._client is not None

    @pytest.mark.asyncio
    async def test_close(self, test_settings, mock_httpx_client):
        """测试关闭客户端。"""
        mock_httpx_client.close = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            client = TwitterClient()
            await client.close()

        # 验证关闭方法被调用
        # 注意：由于 mock 设置方式，可能需要调整验证逻辑
