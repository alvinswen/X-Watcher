"""TwitterClient 单元测试。

测试 Twitter API 客户端功能，包括重试策略和错误处理。
"""

import inspect
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
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        data = result.unwrap()
        assert "data" in data
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "1234567890"

    def test_fetch_user_tweets_signature_without_limit(self):
        """单页客户端签名只保留 username 与 cursor。"""
        assert set(inspect.signature(TwitterClient.fetch_user_tweets).parameters) == {
            "self",
            "username",
            "cursor",
        }

    @pytest.mark.asyncio
    async def test_fetch_user_tweets_params_exclude_limit(
        self, client, mock_httpx_client
    ):
        """请求参数保持 userName，且不向上游发送 limit。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [], "includes": {"users": []}}

        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)

        call_args = mock_httpx_client.get.call_args
        params = call_args[1]["params"]
        assert params["userName"] == "testuser"
        assert params["includeReplies"] is True
        assert "limit" not in params

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
            result = await client.fetch_user_tweets("testuser")

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
            result = await client.fetch_user_tweets("quoter")

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
            result = await client.fetch_user_tweets("replier")

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
            result = await client.fetch_user_tweets("original")

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
            result = await client.fetch_user_tweets("both")

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
            result = await client.fetch_user_tweets("testuser")

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
            result = await client.fetch_user_tweets("notreply")

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "referenced_tweets" not in tweet


class TestExtractFullText:
    """_extract_full_text 辅助函数测试。"""

    def test_prefers_note_tweet(self):
        """note_tweet.text 存在时应优先使用（最长）。"""
        from src.scraper.client import _extract_full_text

        tweet_obj = {
            "text": "Short truncated...",
            "full_text": "Medium length text here",
            "note_tweet": {"text": "This is the longest note_tweet text with full content"},
        }
        result = _extract_full_text(tweet_obj)
        assert result == "This is the longest note_tweet text with full content"

    def test_prefers_full_text_over_text(self):
        """full_text 存在且更长时应优先于 text。"""
        from src.scraper.client import _extract_full_text

        tweet_obj = {
            "text": "Truncated at 140...",
            "full_text": "This is the full_text field which is longer and complete",
        }
        result = _extract_full_text(tweet_obj)
        assert result == "This is the full_text field which is longer and complete"

    def test_falls_back_to_text(self):
        """只有 text 字段时应正常回退。"""
        from src.scraper.client import _extract_full_text

        tweet_obj = {"text": "Just a regular tweet"}
        result = _extract_full_text(tweet_obj)
        assert result == "Just a regular tweet"

    def test_returns_longest_candidate(self):
        """多个候选文本时应返回最长的。"""
        from src.scraper.client import _extract_full_text

        tweet_obj = {
            "text": "short",
            "full_text": "a bit longer text",
            "note_tweet": {"text": "medium"},
        }
        result = _extract_full_text(tweet_obj)
        assert result == "a bit longer text"

    def test_returns_none_for_empty(self):
        """无文本字段时返回 None。"""
        from src.scraper.client import _extract_full_text

        assert _extract_full_text({}) is None
        assert _extract_full_text({"text": ""}) is None
        assert _extract_full_text({"text": None}) is None

    def test_returns_none_for_non_dict(self):
        """非字典输入返回 None。"""
        from src.scraper.client import _extract_full_text

        assert _extract_full_text(None) is None
        assert _extract_full_text("string") is None
        assert _extract_full_text(42) is None

    def test_ignores_invalid_note_tweet(self):
        """note_tweet 不是字典时应忽略。"""
        from src.scraper.client import _extract_full_text

        tweet_obj = {
            "text": "Regular text",
            "note_tweet": "not a dict",
        }
        result = _extract_full_text(tweet_obj)
        assert result == "Regular text"

    @pytest.mark.asyncio
    async def test_rt_uses_full_text_from_nested_tweet(self, test_settings):
        """集成测试：RT 的嵌套推文使用 full_text 替代截断的 text。"""
        client = TwitterClient()

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "tweets": [
                    {
                        "id": "rt_001",
                        "text": "RT @original: This is truncated\u2026",
                        "createdAt": "Thu Feb 13 10:00:00 +0000 2026",
                        "retweeted_tweet": {
                            "id": "orig_001",
                            "text": "This is truncated\u2026",
                            "full_text": "This is truncated but full_text has the complete version of the original tweet",
                            "author": {"userName": "original", "name": "Original Author"},
                        },
                        "author": {"userName": "retweeter", "name": "Retweeter"},
                    }
                ]
            }
        }

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("retweeter")

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        # referenced_tweet_text 应使用 full_text（更长的版本）
        assert tweet["referenced_tweet_text"] == (
            "This is truncated but full_text has the complete version of the original tweet"
        )


class TestCursorPagination:
    """cursor 分页功能测试。"""

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

    def _make_twitterapi_response(self, tweets, next_cursor=None):
        """构造带 next_cursor 的 TwitterAPI.io 格式 mock 响应。"""
        mock_response = Mock()
        mock_response.status_code = 200
        response_data = {"tweets": tweets}
        if next_cursor:
            response_data["next_cursor"] = next_cursor
        mock_response.json.return_value = response_data
        return mock_response

    @pytest.mark.asyncio
    async def test_cursor_param_passed_to_api(self, client, mock_httpx_client):
        """测试 cursor 参数被正确传递到 API 请求。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "100",
                "text": "Page 2 tweet",
                "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                "author": {"userName": "testuser", "name": "Test"},
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets(
                "testuser", cursor="abc123cursor",
            )

        assert isinstance(result, Success)
        # 验证 cursor 参数被传递
        call_args = mock_httpx_client.get.call_args
        params = call_args[1]["params"]
        assert params["cursor"] == "abc123cursor"

    @pytest.mark.asyncio
    async def test_next_cursor_preserved_in_response(self, client, mock_httpx_client):
        """测试 API 响应中的 next_cursor 被保留在返回结果中。"""
        mock_response = self._make_twitterapi_response(
            tweets=[
                {
                    "id": "100",
                    "text": "A tweet",
                    "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                    "author": {"userName": "testuser", "name": "Test"},
                }
            ],
            next_cursor="next_page_cursor_xyz",
        )
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        data = result.unwrap()
        assert data.get("next_cursor") == "next_page_cursor_xyz"

    @pytest.mark.asyncio
    async def test_no_next_cursor_when_absent(self, client, mock_httpx_client):
        """测试无 next_cursor 时返回结果不含该字段。"""
        mock_response = self._make_twitterapi_response(
            tweets=[
                {
                    "id": "100",
                    "text": "Last page tweet",
                    "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                    "author": {"userName": "testuser", "name": "Test"},
                }
            ],
        )
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("testuser")

        assert isinstance(result, Success)
        data = result.unwrap()
        assert "next_cursor" not in data

    @pytest.mark.asyncio
    async def test_paginated_iterates_pages(self, client, mock_httpx_client):
        """测试 fetch_user_tweets_paginated 逐页迭代。"""
        page1 = self._make_twitterapi_response(
            tweets=[{"id": "1", "text": "P1", "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                     "author": {"userName": "u", "name": "U"}}],
            next_cursor="cursor_2",
        )
        page2 = self._make_twitterapi_response(
            tweets=[{"id": "2", "text": "P2", "createdAt": "Fri Feb 07 08:00:00 +0000 2026",
                     "author": {"userName": "u", "name": "U"}}],
        )
        mock_httpx_client.get.side_effect = [page1, page2]

        pages = []
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            async for page_data in client.fetch_user_tweets_paginated(
                "u", max_pages=5, page_delay=0,
            ):
                pages.append(page_data)

        assert len(pages) == 2
        assert pages[0]["data"][0]["id"] == "1"
        assert pages[1]["data"][0]["id"] == "2"

    @pytest.mark.asyncio
    async def test_paginated_stops_at_max_pages(self, client, mock_httpx_client):
        """测试 fetch_user_tweets_paginated 达到 max_pages 时停止。"""
        # 每页都返回 next_cursor（无限页）
        call_count = [0]

        def make_page():
            call_count[0] += 1
            return self._make_twitterapi_response(
                tweets=[{"id": str(call_count[0]), "text": f"T{call_count[0]}",
                         "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                         "author": {"userName": "u", "name": "U"}}],
                next_cursor=f"cursor_{call_count[0] + 1}",
            )

        mock_httpx_client.get.side_effect = [make_page() for _ in range(5)]

        pages = []
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            async for page_data in client.fetch_user_tweets_paginated(
                "u", max_pages=3, page_delay=0,
            ):
                pages.append(page_data)

        assert len(pages) == 3

    @pytest.mark.asyncio
    async def test_paginated_stops_on_api_error(self, client, mock_httpx_client):
        """测试 fetch_user_tweets_paginated 在 API 错误时停止。"""
        page1 = self._make_twitterapi_response(
            tweets=[{"id": "1", "text": "P1", "createdAt": "Fri Feb 07 09:00:00 +0000 2026",
                     "author": {"userName": "u", "name": "U"}}],
            next_cursor="cursor_2",
        )
        error_response = Mock()
        error_response.status_code = 500
        mock_httpx_client.get.side_effect = [page1, error_response]

        pages = []
        with patch("httpx.AsyncClient", return_value=mock_httpx_client), \
             patch("src.scraper.client.asyncio.sleep", new_callable=AsyncMock):
            async for page_data in client.fetch_user_tweets_paginated(
                "u", max_pages=5, page_delay=0,
            ):
                pages.append(page_data)

        # 只有第一页成功
        assert len(pages) == 1


class TestFetchArticle:
    """fetch_article 测试。"""

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
    async def test_fetch_article_success(self, client, mock_httpx_client):
        """测试成功获取 Article。"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "title": "My Article",
                "content": "Full article content...",
                "previewText": "Preview...",
                "coverImageUrl": "https://example.com/cover.jpg",
            }
        }
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_article("12345")

        assert isinstance(result, Success)
        data = result.unwrap()
        assert data["data"]["title"] == "My Article"

        # 验证 API 调用参数（修正后的端点和参数名）
        call_kwargs = mock_httpx_client.get.call_args
        assert call_kwargs[0][0] == "/article"
        assert call_kwargs[1]["params"]["tweet_id"] == "12345"

    @pytest.mark.asyncio
    async def test_fetch_article_empty_tweet_id(self, client):
        """测试空 tweet_id 返回 Failure。"""
        result = await client.fetch_article("")

        assert isinstance(result, Failure)
        assert "不能为空" in result.failure().message

    @pytest.mark.asyncio
    async def test_fetch_article_404(self, client, mock_httpx_client):
        """测试 404 返回 Failure（不可重试）。"""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_article("99999")

        assert isinstance(result, Failure)
        assert "404" in result.failure().message


class TestArticleFieldNormalization:
    """测试 TwitterAPI.io 响应中 article 字段的标准化传递。"""

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
    async def test_normalize_preserves_article_field(self, client, mock_httpx_client):
        """测试标准化后保留推文的 article 字段。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "art_001",
                "text": "https://t.co/abc123",
                "createdAt": "Thu Feb 20 04:00:00 +0000 2026",
                "author": {"userName": "author1", "name": "Author One"},
                "article": {
                    "title": "My Great Article",
                    "preview_text": "This is a preview...",
                    "cover_media_img_url": "https://pbs.twimg.com/cover.jpg",
                },
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("author1")

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "article" in tweet
        assert tweet["article"]["title"] == "My Great Article"
        assert tweet["article"]["preview_text"] == "This is a preview..."
        assert tweet["article"]["cover_media_img_url"] == "https://pbs.twimg.com/cover.jpg"

    @pytest.mark.asyncio
    async def test_normalize_null_article_not_included(self, client, mock_httpx_client):
        """测试 article 为 null 时不包含在标准化结果中。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "normal_001",
                "text": "Just a regular tweet",
                "createdAt": "Thu Feb 20 05:00:00 +0000 2026",
                "author": {"userName": "user1", "name": "User One"},
                "article": None,
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("user1")

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "article" not in tweet

    @pytest.mark.asyncio
    async def test_normalize_missing_article_field(self, client, mock_httpx_client):
        """测试推文对象中完全没有 article 字段时不报错。"""
        mock_response = self._make_twitterapi_response([
            {
                "id": "old_001",
                "text": "Old tweet without article field",
                "createdAt": "Thu Feb 20 06:00:00 +0000 2026",
                "author": {"userName": "user2", "name": "User Two"},
            }
        ])
        mock_httpx_client.get.return_value = mock_response

        with patch("httpx.AsyncClient", return_value=mock_httpx_client):
            result = await client.fetch_user_tweets("user2")

        assert isinstance(result, Success)
        data = result.unwrap()
        tweet = data["data"][0]
        assert "article" not in tweet
