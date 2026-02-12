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


def _extract_media_from_tweet_obj(tweet_obj: dict) -> list[dict]:
    """从 TwitterAPI.io 推文对象中提取媒体数据。

    支持多种 TwitterAPI.io 媒体字段格式：
    - tweet.media (直接媒体数组)
    - tweet.extendedEntities.media (扩展实体中的媒体)

    Args:
        tweet_obj: TwitterAPI.io 推文对象

    Returns:
        list[dict]: 标准化的媒体字典列表，每个包含 media_key, type, url 等字段
    """
    if not isinstance(tweet_obj, dict):
        return []

    # 尝试多种路径获取媒体数组
    media_list: list[dict] = []

    # 路径 1: tweet.media (TwitterAPI.io 常见格式)
    raw_media = tweet_obj.get("media")
    if isinstance(raw_media, dict):
        # 有时 media 是一个包含 photos/videos 等子键的字典
        for key in ("photos", "videos", "all"):
            items = raw_media.get(key)
            if isinstance(items, list):
                media_list.extend(items)
        # 如果子键都不存在，可能是 {media_key: ...} 格式，跳过
    elif isinstance(raw_media, list):
        media_list.extend(raw_media)

    # 路径 2: tweet.extendedEntities.media
    if not media_list:
        extended = tweet_obj.get("extendedEntities")
        if isinstance(extended, dict):
            ext_media = extended.get("media")
            if isinstance(ext_media, list):
                media_list.extend(ext_media)

    if not media_list:
        return []

    result = []
    for idx, m in enumerate(media_list):
        if not isinstance(m, dict):
            continue

        # 提取 media_key：优先使用 media_key，其次 id_str，最后用索引生成
        media_key = (
            m.get("media_key")
            or m.get("id_str")
            or str(m.get("id", f"media_{idx}"))
        )

        # 提取 URL：优先 media_url_https，其次 url
        url = m.get("media_url_https") or m.get("url")

        # 提取尺寸
        width = m.get("width")
        height = m.get("height")
        if width is None and isinstance(m.get("sizes"), dict):
            large = m["sizes"].get("large", {})
            width = large.get("w")
            height = large.get("h")

        result.append({
            "media_key": str(media_key),
            "type": m.get("type", "photo"),
            "url": url,
            "preview_image_url": m.get("preview_image_url"),
            "width": width,
            "height": height,
            "alt_text": m.get("alt_text"),
        })

    return result


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
                            all_media: list[dict] = []  # 收集所有媒体

                            for tweet in tweets_array:
                                # 从 tweet 中提取基本信息
                                tweet_id = tweet.get("id")
                                tweet_text = tweet.get("text", "")
                                created_at_raw = tweet.get("createdAt")

                                # 转换日期格式：TwitterAPI.io -> ISO 8601
                                created_at_iso = _convert_twitterapi_date_to_iso(created_at_raw)

                                # 从 TwitterAPI.io 字段构建 referenced_tweets（Twitter v2 格式）
                                # 优先级：retweeted > quoted > replied_to
                                referenced_tweets = []
                                retweeted_tweet_obj = tweet.get("retweeted_tweet")
                                quoted_tweet_obj = tweet.get("quoted_tweet")

                                # 被引用推文的完整文本、媒体和原作者
                                referenced_tweet_text = None
                                referenced_tweet_media = None
                                referenced_tweet_author_username = None

                                if isinstance(retweeted_tweet_obj, dict) and retweeted_tweet_obj.get("id"):
                                    referenced_tweets.append({
                                        "type": "retweeted",
                                        "id": str(retweeted_tweet_obj["id"]),
                                    })
                                    # 提取原推的完整文本
                                    referenced_tweet_text = retweeted_tweet_obj.get("text")
                                    # 提取原推的媒体
                                    referenced_tweet_media = _extract_media_from_tweet_obj(retweeted_tweet_obj)
                                    # 提取原推的作者用户名
                                    rt_author = retweeted_tweet_obj.get("author")
                                    if isinstance(rt_author, dict):
                                        referenced_tweet_author_username = rt_author.get("userName")
                                elif isinstance(quoted_tweet_obj, dict) and quoted_tweet_obj.get("id"):
                                    referenced_tweets.append({
                                        "type": "quoted",
                                        "id": str(quoted_tweet_obj["id"]),
                                    })
                                    # 提取被引用推文的完整文本
                                    referenced_tweet_text = quoted_tweet_obj.get("text")
                                    # 提取被引用推文的媒体
                                    referenced_tweet_media = _extract_media_from_tweet_obj(quoted_tweet_obj)
                                    # 提取被引用推文的作者用户名
                                    qt_author = quoted_tweet_obj.get("author")
                                    if isinstance(qt_author, dict):
                                        referenced_tweet_author_username = qt_author.get("userName")
                                elif tweet.get("isReply") and tweet.get("inReplyToId"):
                                    referenced_tweets.append({
                                        "type": "replied_to",
                                        "id": str(tweet["inReplyToId"]),
                                    })

                                standard_tweet: dict[str, Any] = {
                                    "id": tweet_id,
                                    "text": tweet_text,
                                    "created_at": created_at_iso,
                                }
                                if referenced_tweets:
                                    standard_tweet["referenced_tweets"] = referenced_tweets
                                if referenced_tweet_text:
                                    standard_tweet["referenced_tweet_text"] = referenced_tweet_text
                                if referenced_tweet_media:
                                    standard_tweet["referenced_tweet_media"] = referenced_tweet_media
                                if referenced_tweet_author_username:
                                    standard_tweet["referenced_tweet_author_username"] = referenced_tweet_author_username

                                # 提取主推文的媒体
                                main_media = _extract_media_from_tweet_obj(tweet)
                                if main_media:
                                    media_keys = [m["media_key"] for m in main_media]
                                    standard_tweet["attachments"] = {"media_keys": media_keys}
                                    all_media.extend(main_media)

                                # 提取 author 信息
                                author_obj = tweet.get("author")
                                if isinstance(author_obj, dict):
                                    author_id_val = str(author_obj.get("id") or author_obj.get("userName", ""))
                                    if author_id_val:
                                        standard_tweet["author_id"] = author_id_val
                                        users_map[author_id_val] = {
                                            "username": author_obj.get("userName"),
                                            "name": author_obj.get("name"),
                                        }

                                tweets_data.append(standard_tweet)

                            # 构造标准响应格式
                            standard_response: dict[str, Any] = {"data": tweets_data}
                            includes: dict[str, Any] = {}
                            if users_map:
                                includes["users"] = [
                                    {"id": uid, "username": info["username"], "name": info["name"]}
                                    for uid, info in users_map.items()
                                ]
                            if all_media:
                                includes["media"] = all_media
                            if includes:
                                standard_response["includes"] = includes

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
