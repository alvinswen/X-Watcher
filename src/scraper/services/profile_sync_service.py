"""User profile synchronization and rename repair services."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from returns.result import Failure

from src.scraper.client import TwitterClient

logger = logging.getLogger(__name__)


class ProfileSyncService:
    """Synchronize X profiles and repair username changes."""

    def __init__(self, client: TwitterClient | None = None) -> None:
        self._client = client or TwitterClient()

    async def detect_and_fix_rename(self, old_username: str) -> str | None:
        """检测用户改名并自动修复数据库记录。

        当抓取某个 username 返回 404 时调用此方法。
        如果数据库中有该用户的 platform_user_id，则通过
        batch_info_by_ids API 查询最新 username。

        Returns:
            str | None: 新的 username，或 None（无法检测/修复）
        """
        try:
            from src.data_layer.provider import get_follows_repo

            repo = get_follows_repo()
            follow = await repo.get_follow_by_username(old_username)

            if not follow or not follow.platform_user_id:
                logger.warning(
                    "用户 %s 不存在或无 platform_user_id，无法检测改名",
                    old_username,
                )
                return None

            # 调用 batch_info_by_ids 查询最新用户信息
            user_info_result = await self._client.fetch_user_info_by_ids(
                [follow.platform_user_id]
            )

            if isinstance(user_info_result, Failure):
                logger.error(
                    "查询用户信息失败: %s",
                    user_info_result.failure().message,
                )
                return None

            users = user_info_result.unwrap()
            if not users:
                logger.warning(
                    "platform_user_id %s 查询无结果（账号可能已被删除）",
                    follow.platform_user_id,
                )
                return None

            new_username = users[0].get("userName") or users[0].get("username")
            if not new_username:
                return None

            new_username = cast(str, new_username).lower()

            if new_username == old_username.lower():
                logger.info(
                    "用户名未变化，404 非改名导致: %s", old_username
                )
                return None

            # 更新 username
            await repo.update_username(old_username, new_username)

            logger.info(
                "用户改名已修复: %s -> %s (user_id=%s)",
                old_username, new_username, follow.platform_user_id,
            )
            return new_username

        except Exception as e:
            logger.error("改名检测失败: %s", e)
            return None

    async def sync_user_profiles(self, usernames: list[str]) -> None:
        """同步用户档案信息。

        从数据库查询指定用户名对应的 platform_user_id，
        然后批量调用 TwitterAPI.io 获取完整档案信息并持久化。

        Args:
            usernames: 刚完成抓取的用户名列表
        """
        try:
            from src.data_layer.provider import get_follows_repo, get_profile_repo
            from src.preference.domain.models import XUserProfile

            config_repo = get_follows_repo()

            # 查询这些用户名对应的 platform_user_id
            user_ids: list[str] = []
            for username in usernames:
                follow = await config_repo.get_follow_by_username(username)
                if follow and follow.platform_user_id:
                    user_ids.append(follow.platform_user_id)

            if not user_ids:
                logger.debug("档案同步: 无可用 platform_user_id，跳过")
                return

            # 批量获取用户信息
            result = await self._client.fetch_user_info_by_ids(user_ids)

            if isinstance(result, Failure):
                logger.warning(
                    "档案同步: API 调用失败: %s",
                    result.failure().message,
                )
                return

            users_data = result.unwrap()
            if not users_data:
                logger.debug("档案同步: API 返回空结果")
                return

            # 转换为领域模型
            now = datetime.now(UTC).replace(tzinfo=None)
            profiles = []
            raw_data_map: dict[str, dict[str, Any]] = {}
            for u in users_data:
                profile = XUserProfile.from_api_response(u, fetched_at=now)
                if profile.platform_user_id:
                    profiles.append(profile)
                    raw_data_map[profile.platform_user_id] = u

            # 持久化
            profile_repo = get_profile_repo()
            count = await profile_repo.upsert_profiles(
                profiles, raw_data_map=raw_data_map
            )
            logger.info("档案同步完成: %d 个用户档案已更新", count)

        except Exception as e:
            logger.warning("档案同步失败（不影响抓取结果）: %s", e)

    async def close(self) -> None:
        """Close the underlying client for standalone use."""
        await self._client.close()
