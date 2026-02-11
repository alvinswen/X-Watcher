"""动态 Limit 计算服务。

根据用户历史抓取统计，动态计算下次 API 调用的 limit 参数。
"""

import logging
from datetime import datetime, timezone

from src.scraper.domain.fetch_stats import FetchStats

logger = logging.getLogger(__name__)


class LimitCalculator:
    """动态 Limit 计算器。

    基于 EMA（指数移动平均）平滑的新推文率预测下次需要的 limit 值。
    """

    def __init__(
        self,
        default_limit: int = 100,
        min_limit: int = 10,
        max_limit: int = 300,
        ema_alpha: float = 0.3,
        safety_margin: float = 1.2,
    ) -> None:
        """初始化计算器。

        Args:
            default_limit: 新用户或无历史数据时的默认 limit
            min_limit: 最小 limit（退避下限）
            max_limit: 最大 limit（上限保护）
            ema_alpha: EMA 平滑系数 (0-1)，越大越重视近期数据
            safety_margin: 安全边际倍数（默认 1.2 即 20%）
        """
        self._default_limit = default_limit
        self._min_limit = min_limit
        self._max_limit = max_limit
        self._ema_alpha = ema_alpha
        self._safety_margin = safety_margin

    def calculate_next_limit(self, stats: FetchStats | None) -> int:
        """计算下次抓取的 limit 值。

        策略：
        1. 无历史数据：使用默认 limit
        2. 满抓取（上次全是新推文）：limit × 2（可能有遗漏）
        3. 连续空抓取 ≥ 3 次：退避到 min_limit
        4. 正常情况：基于 EMA 新推文率预测 + 安全边际

        Args:
            stats: 用户的抓取统计，None 表示新用户

        Returns:
            int: 建议的 limit 值
        """
        if stats is None or stats.total_fetches == 0:
            logger.debug("新用户，使用默认 limit=%d", self._default_limit)
            return self._default_limit

        # 满抓取检测：上次新推文数 == API 返回数，可能有遗漏
        if (
            stats.last_new_count > 0
            and stats.last_fetched_count > 0
            and stats.last_new_count == stats.last_fetched_count
        ):
            boosted = min(stats.last_fetched_count * 2, self._max_limit)
            logger.info(
                "用户 %s 上次满抓取 (%d/%d)，提升 limit=%d",
                stats.username,
                stats.last_new_count,
                stats.last_fetched_count,
                boosted,
            )
            return max(self._min_limit, boosted)

        # 连续空抓取退避
        if stats.consecutive_empty_fetches >= 3:
            logger.info(
                "用户 %s 连续 %d 次空抓取，使用最小 limit=%d",
                stats.username,
                stats.consecutive_empty_fetches,
                self._min_limit,
            )
            return self._min_limit

        # 正常计算：基于 EMA 新推文率
        if stats.avg_new_rate > 0 and stats.last_new_count > 0:
            predicted = stats.last_new_count / stats.avg_new_rate
            predicted = int(predicted * self._safety_margin)
            result = max(self._min_limit, min(predicted, self._max_limit))
            logger.debug(
                "用户 %s 动态 limit: new_rate=%.2f, last_new=%d, predicted=%d",
                stats.username,
                stats.avg_new_rate,
                stats.last_new_count,
                result,
            )
            return result

        # 边界情况（avg_new_rate == 0 但未触发空抓取退避）
        return self._default_limit

    def update_stats_after_fetch(
        self,
        stats: FetchStats | None,
        username: str,
        fetched_count: int,
        new_count: int,
    ) -> FetchStats:
        """抓取完成后更新统计数据。

        Args:
            stats: 当前统计数据（None 表示新建）
            username: 用户名
            fetched_count: 本次 API 返回的推文数
            new_count: 本次新增的推文数

        Returns:
            FetchStats: 更新后的统计数据
        """
        now = datetime.now(timezone.utc)

        if stats is None:
            # 新用户，创建初始统计
            current_rate = new_count / fetched_count if fetched_count > 0 else 0.0
            return FetchStats(
                username=username,
                last_fetch_at=now,
                last_fetched_count=fetched_count,
                last_new_count=new_count,
                total_fetches=1,
                avg_new_rate=current_rate,
                consecutive_empty_fetches=0 if new_count > 0 else 1,
            )

        # 更新 EMA
        if fetched_count > 0:
            current_rate = new_count / fetched_count
            new_avg = (
                self._ema_alpha * current_rate
                + (1 - self._ema_alpha) * stats.avg_new_rate
            )
        else:
            new_avg = stats.avg_new_rate

        # 更新连续空抓取计数
        if new_count == 0:
            consecutive_empty = stats.consecutive_empty_fetches + 1
        else:
            consecutive_empty = 0

        return FetchStats(
            username=username,
            last_fetch_at=now,
            last_fetched_count=fetched_count,
            last_new_count=new_count,
            total_fetches=stats.total_fetches + 1,
            avg_new_rate=new_avg,
            consecutive_empty_fetches=consecutive_empty,
        )
