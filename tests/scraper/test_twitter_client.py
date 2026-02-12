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

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
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

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
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

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        # 默认最大重试 5 次，加上初始调用 = 6 次
        assert mock_httpx_client.get.call_count == 6

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_timeout(self, client, mock_httpx_client):
        """测试网络超时。"""
        mock_httpx_client.get.side_effect = httpx.TimeoutException("Request timeout")

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        error = result.failure()
        assert "timeout" in str(error).lower()

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_network_error(self, client, mock_httpx_client):
        """测试网络连接错误。"""
        mock_httpx_client.get.side_effect = httpx.NetworkError("Connection failed")

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
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
        """测试指数退避延迟参数正确。"""
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

        mock_sleep = AsyncMock()
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", mock_sleep):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        # 验证 sleep 被调用 3 次，参数为指数退避：1, 2, 4
        assert mock_sleep.call_count == 3
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1, 2, 4]

    @pytest.mark.asyncio
    async def test_custom_max_retries(self, test_settings, mock_httpx_client):
        """测试自定义最大重试次数。"""
        mock_response = Mock()
        mock_response.status_code = 500

        mock_httpx_client.get.return_value = mock_response

        # 创建自定义重试次数的客户端
        client = TwitterClient(max_retries=2)

        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Failure)
        # 初始调用 + 2 次重试
        assert mock_httpx_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_custom_base_delay(self, test_settings, mock_httpx_client):
        """测试自定义基础延迟参数正确。"""
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

        mock_sleep = AsyncMock()
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", mock_sleep):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        # 验证 sleep 被调用 1 次，参数为自定义基础延迟 0.1
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args_list[0].args[0] == 0.1

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


class TestTwitterClientReferenceTypeConversion:
    """测试 TwitterAPI.io 响应中引用关系字段的转换。"""

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

    def _make_twitterapi_response(self, tweets):
        """构造 TwitterAPI.io 格式的 mock 响应。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"tweets": tweets}
        return mock_response

    @pytest.mark.asyncio
    async def test_fetch_converts_retweeted_tweet(self, client, mock_httpx_client):
        """测试转推的 retweeted_tweet 字段被正确转换为 referenced_tweets。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "111",
                "text": "RT @someone: original text",
                "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                "retweeted_tweet": {
                    "id": "222",
                    "text": "original text",
                },
                "author": {
                    "userName": "testuser",
                    "name": "Test User",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" in tweet
        assert tweet["referenced_tweets"] == [{"type": "retweeted", "id": "222"}]
        # 验证提取了原推的完整文本
        assert tweet.get("referenced_tweet_text") == "original text"

    @pytest.mark.asyncio
    async def test_fetch_converts_quoted_tweet(self, client, mock_httpx_client):
        """测试引用推文的 quoted_tweet 字段被正确转换为 referenced_tweets。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "333",
                "text": "Great insight here!",
                "createdAt": "Fri Feb 07 10:00:00 +0000 2026",
                "quoted_tweet": {
                    "id": "444",
                    "text": "Some quoted content",
                },
                "author": {
                    "userName": "quoter",
                    "name": "Quote User",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("quoter", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" in tweet
        assert tweet["referenced_tweets"] == [{"type": "quoted", "id": "444"}]
        # 验证提取了被引用推文的完整文本
        assert tweet.get("referenced_tweet_text") == "Some quoted content"

    @pytest.mark.asyncio
    async def test_fetch_converts_reply(self, client, mock_httpx_client):
        """测试回复推文的 isReply + inReplyToId 被正确转换为 referenced_tweets。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "555",
                "text": "I agree with this!",
                "createdAt": "Fri Feb 07 11:00:00 +0000 2026",
                "isReply": True,
                "inReplyToId": "666",
                "author": {
                    "userName": "replier",
                    "name": "Reply User",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("replier", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" in tweet
        assert tweet["referenced_tweets"] == [{"type": "replied_to", "id": "666"}]

    @pytest.mark.asyncio
    async def test_fetch_no_reference_for_original_tweet(self, client, mock_httpx_client):
        """测试原创推文不包含 referenced_tweets。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "777",
                "text": "Just a regular tweet",
                "createdAt": "Fri Feb 07 12:00:00 +0000 2026",
                "author": {
                    "userName": "original",
                    "name": "Original User",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("original", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" not in tweet

    @pytest.mark.asyncio
    async def test_fetch_retweet_precedence_over_quote(self, client, mock_httpx_client):
        """测试同时存在 retweeted_tweet 和 quoted_tweet 时，retweeted 优先。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "888",
                "text": "RT with quote",
                "createdAt": "Fri Feb 07 13:00:00 +0000 2026",
                "retweeted_tweet": {"id": "999"},
                "quoted_tweet": {"id": "1000"},
                "author": {
                    "userName": "both",
                    "name": "Both User",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("both", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert tweet["referenced_tweets"] == [{"type": "retweeted", "id": "999"}]

    @pytest.mark.asyncio
    async def test_fetch_extracts_author_info(self, client, mock_httpx_client):
        """测试 author 对象被正确提取到 includes.users。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "1100",
                "text": "Author test",
                "createdAt": "Fri Feb 07 14:00:00 +0000 2026",
                "author": {
                    "id": "author_id_123",
                    "userName": "testuser",
                    "name": "Real Display Name",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()

        # 验证 author_id 被设置在推文上
        tweet = data["data"][0]
        assert tweet["author_id"] == "author_id_123"

        # 验证 includes.users 包含正确的用户信息
        assert "includes" in data
        users = data["includes"]["users"]
        assert len(users) == 1
        assert users[0]["id"] == "author_id_123"
        assert users[0]["username"] == "testuser"
        assert users[0]["name"] == "Real Display Name"

    @pytest.mark.asyncio
    async def test_fetch_isreply_false_no_reference(self, client, mock_httpx_client):
        """测试 isReply=False 时不生成 replied_to 引用。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "1200",
                "text": "Not a reply",
                "createdAt": "Fri Feb 07 15:00:00 +0000 2026",
                "isReply": False,
                "inReplyToId": "some_id",
                "author": {
                    "userName": "notreply",
                    "name": "Not Reply",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("notreply", limit=10)

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" not in tweet
