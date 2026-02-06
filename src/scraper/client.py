"""Twitter API 客户端。

封装 TwitterAPI.io 的 HTTP 调用，包含重试策略和错误处理。
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx
from returns.result import Failure, Result, Success

from src.config import get_settings

logger = logging.getLogger(__name__)


def _convert_twitterapi_date_to_iso(date_str: str | None) -> str | None:
    """转换 TwitterAPI.io 日期格式为 ISO 8601 格式。

    TwitterAPI.io 格式: "Fri Feb 06 09:31:48 +0000 2026"
    标准 ISO 8601 格式: "2026-02-06T09:31:48.000Z"

    Args:
        date_str: TwitterAPI.io 日期字符串

    Returns:
        str | None: ISO 8601 格式的日期字符串，输入为 None 时返回 None
    """
    if not date_str:
        return None

    try:
        # TwitterAPI.io 格式: "Fri Feb 06 09:31:48 +0000 2026"
        # 使用 datetime.strptime 解析
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        # 转换为 ISO 8601 格式
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError) as e:
        logger.warning(f"日期转换失败: {date_str} - {e}")
        return date_str  # 返回原始字符串


class TwitterClientError(Exception):
    """Twitter API 客户端错误。

    表示客户端操作失败的基本异常类。
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """初始化错误。

        Args:
            message: 错误消息
            status_code: HTTP 状态码（如果有）
        """
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class TwitterClient:
    """Twitter API 客户端。

    提供异步 HTTP 调用接口，支持指数退避重试策略。
    """

    # 默认配置
    DEFAULT_MAX_RETRIES = 5
    DEFAULT_BASE_DELAY = 1.0  # 秒
    DEFAULT_MAX_DELAY = 60.0  # 秒
    DEFAULT_TIMEOUT = 30.0  # 秒

    # 不应重试的状态码
    NON_RETRYABLE_STATUS_CODES = {401, 403, 404, 422}

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化客户端。

        Args:
            max_retries: 最大重试次数（不包括初始调用）
            base_delay: 基础延迟时间（秒），用于指数退避
            max_delay: 最大延迟时间（秒）
            timeout: 请求超时时间（秒）
        """
        self._settings = get_settings()
        self._base_url = self._settings.twitter_base_url
        self._api_key = self._settings.twitter_api_key
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TwitterClient":
        """进入上下文管理器。"""
        self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """退出上下文管理器。"""
        await self.close()

    def _ensure_client(self) -> None:
        """确保 HTTP 客户端已初始化。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-API-Key": self._api_key,
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_user_tweets(
        self,
        username: str,
        *,
        limit: int = 100,
        since_id: str | None = None,
    ) -> Result[dict[str, Any], TwitterClientError]:
        """获取指定用户的推文列表。

        Args:
            username: Twitter 用户名（不带 @ 符号）
            limit: 返回推文数量限制（1-1000）
            since_id: 只返回此 ID 之后的推文（TwitterAPI.io 暂不支持）

        Returns:
            Result[dict, TwitterClientError]:
                Success: 包含推文数据的字典
                Failure: TwitterClientError 错误信息
        """
        # 验证输入
        if not username or not username.strip():
            return Failure(
                TwitterClientError("用户名不能为空")
            )

        if limit < 1:
            return Failure(
                TwitterClientError("limit 必须大于 0")
            )

        # TwitterAPI.io 使用 /user/last_tweets 端点
        # 参数名为 userName（不是 username）
        params: dict[str, Any] = {
            "userName": username,
            "includeReplies": False,  # 不包含回复
        }

        if since_id:
            # TwitterAPI.io 可能不支持 since_id，记录警告
            logger.warning("since_id 参数在 TwitterAPI.io 中可能不被支持")

        # 确保客户端已初始化
        self._ensure_client()
        assert self._client is not None

        # 执行带重试的请求
        return await self._fetch_with_retry(
            "/user/last_tweets",
            params=params,
        )

    async def _fetch_with_retry(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> Result[dict[str, Any], TwitterClientError]:
        """执行带指数退避重试的 HTTP 请求。

        Args:
            endpoint: API 端点路径
            params: 请求参数

        Returns:
            Result[dict, TwitterClientError]: API 响应数据或错误
        """
        retry_count = 0
        current_delay = self._base_delay

        while True:
            try:
                response = await self._client.get(  # type: ignore
                    endpoint,
                    params=params,
                )
                status_code = response.status_code

                # 检查是否需要重试
                if status_code == 200:
                    # 成功响应
                    try:
                        response_data = response.json()

                        # 检查 response_data 是否为字典
                        if not isinstance(response_data, dict):
                            logger.error(f"响应数据不是字典类型，而是 {type(response_data)}")
                            logger.error(f"响应内容: {str(response_data)[:500]}")
                            return Failure(
                                TwitterClientError(f"响应格式错误: 期望 dict，实际 {type(response_data)}")
                            )

                        # TwitterAPI.io 格式转换
                        # TwitterAPI.io 响应格式: {"status": "success", "data": {"tweets": [...]}}
                        tweets_array = None

                        # 检查是否是 TwitterAPI.io 嵌套格式
                        if "data" in response_data and isinstance(response_data.get("data"), dict):
                            inner_data = response_data.get("data", {})
                            if "tweets" in inner_data:
                                tweets_array = inner_data.get("tweets", [])
                                logger.info("检测到 TwitterAPI.io 嵌套响应格式 (data.tweets)")
                        # 检查是否是 TwitterAPI.io 直接格式
                        elif "tweets" in response_data:
                            tweets_array = response_data.get("tweets", [])
                            logger.info("检测到 TwitterAPI.io 直接响应格式 (tweets)")

                        if tweets_array is not None:
                            # 转换 TwitterAPI.io 格式为标准 Twitter API v2 格式
                            tweets_data = []
                            users_map = {}

                            for tweet in tweets_array:
                                # 提取用户信息（注意：TwitterAPI.io 用户名在 userName 字段）
                                # TwitterAPI.io 返回的用户信息格式:
                                # - 有些推文有 author 字段（包含完整用户信息）
                                # - 有些推文直接包含在顶层（通过 username 参数查询）
                                # 我们需要从上下文中获取用户名，或者假设所有推文属于同一个用户

                                # 从 tweet 中提取基本信息
                                tweet_id = tweet.get("id")
                                tweet_text = tweet.get("text", "")
                                created_at_raw = tweet.get("createdAt")

                                # 转换日期格式：TwitterAPI.io -> ISO 8601
                                created_at_iso = _convert_twitterapi_date_to_iso(created_at_raw)

                                # TwitterAPI.io 的响应中没有 author_id，我们需要处理这个问题
                                # 暂时使用一个占位符，后续在服务层处理
                                standard_tweet = {
                                    "id": tweet_id,
                                    "text": tweet_text,
                                    "created_at": created_at_iso,
                                    # 注意：author_id 将在服务层从参数中获取
                                }

                                tweets_data.append(standard_tweet)

                            # 构造标准响应格式（不包含 users，因为我们没有用户信息）
                            standard_response = {
                                "data": tweets_data,
                                # 不添加 includes.users，因为 TwitterAPI.io 不返回用户详细信息
                            }

                            logger.info(f"转换完成：{len(tweets_data)} 条推文")
                            logger.debug(f"第一条推文: {str(tweets_data[0]) if tweets_data else 'N/A'}")
                            return Success(standard_response)
                        else:
                            # 可能已经是标准格式
                            logger.debug(f"响应格式（未检测到 tweets 字段）: {str(response_data)[:200]}")
                            return Success(response_data)

                    except Exception as e:
                        logger.error(f"响应处理失败: {e}")
                        return Failure(
                            TwitterClientError(f"响应处理失败: {e}")
                        )

                # 检查是否是不可重试的错误
                if status_code in self.NON_RETRYABLE_STATUS_CODES:
                    error_msg = self._get_error_message(status_code)
                    logger.error(f"Twitter API 不可重试错误: {status_code} - {error_msg}")
                    return Failure(
                        TwitterClientError(
                            f"API 错误 {status_code}: {error_msg}",
                            status_code=status_code,
                        )
                    )

                # 检查是否达到最大重试次数
                if retry_count >= self._max_retries:
                    logger.warning(
                        f"Twitter API 达到最大重试次数 {self._max_retries}"
                    )
                    return Failure(
                        TwitterClientError(
                            f"API 错误 {status_code}: 已达到最大重试次数",
                            status_code=status_code,
                        )
                    )

                # 需要重试
                logger.warning(
                    f"Twitter API 请求失败 (状态码: {status_code}), "
                    f"{current_delay:.1f}秒后重试 ({retry_count + 1}/{self._max_retries})"
                )

                await asyncio.sleep(current_delay)

                # 指数退避：延迟时间翻倍，但不超过最大值
                current_delay = min(current_delay * 2, self._max_delay)
                retry_count += 1

            except httpx.TimeoutException as e:
                # 超时错误
                if retry_count >= self._max_retries:
                    logger.error(f"Twitter API 请求超时: {e}")
                    return Failure(
                        TwitterClientError(f"请求超时: {e}")
                    )

                logger.warning(f"Twitter API 请求超时，{current_delay:.1f}秒后重试")
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 2, self._max_delay)
                retry_count += 1

            except httpx.NetworkError as e:
                # 网络错误
                if retry_count >= self._max_retries:
                    logger.error(f"Twitter API 网络错误: {e}")
                    return Failure(
                        TwitterClientError(f"网络错误: {e}")
                    )

                logger.warning(f"Twitter API 网络错误，{current_delay:.1f}秒后重试")
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 2, self._max_delay)
                retry_count += 1

            except ValueError as e:
                # JSON 解析错误
                logger.error(f"Twitter API 响应解析失败: {e}")
                return Failure(
                    TwitterClientError(f"响应解析失败: {e}")
                )

            except Exception as e:
                # 未预期的错误
                logger.exception(f"Twitter API 未预期的错误: {e}")
                return Failure(
                    TwitterClientError(f"未预期的错误: {e}")
                )

    def _get_error_message(self, status_code: int) -> str:
        """获取状态码对应的错误消息。

        Args:
            status_code: HTTP 状态码

        Returns:
            str: 错误消息描述
        """
        error_messages = {
            400: "错误的请求",
            401: "未授权 - 请检查 Bearer Token",
            403: "禁止访问",
            404: "资源未找到",
            422: "无法处理的实体",
            429: "请求过于频繁 - 请稍后重试",
            500: "服务器内部错误",
            502: "网关错误",
            503: "服务不可用",
            504: "网关超时",
        }
        return error_messages.get(status_code, f"未知错误 (状态码: {status_code})")
