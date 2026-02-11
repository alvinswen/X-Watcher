"""RelevanceService - 推文相关性计算服务。

定义相关性计算的抽象接口和 MVP 实现。
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.scraper.domain.models import Tweet

logger = logging.getLogger(__name__)


class RelevanceServiceError(Exception):
    """相关性服务错误。"""

    pass


class RelevanceService(ABC):
    """相关性计算服务抽象接口。

    定义推文与关键词相关性计算的抽象方法。
    未来可扩展为基于嵌入模型的语义相似度计算。
    """

    @abstractmethod
    async def calculate_relevance(
        self,
        tweet: "Tweet",
        keywords: list[str],
    ) -> float:
        """计算推文与关键词的相关性分数。

        Args:
            tweet: 推文领域模型
            keywords: 关键词列表

        Returns:
            float: 相关性分数（0.0-1.0）

        Raises:
            RelevanceServiceError: 如果计算失败
        """
        pass


class KeywordRelevanceService(RelevanceService):
    """基于关键词匹配的相关性计算服务。

    MVP 实现使用简单的关键词匹配算法。
    计算推文中关键词出现的频率和位置，生成 0.0-1.0 的相关性分数。

    算法说明：
    - 将推文文本和关键词都转换为小写
    - 使用子串匹配（支持部分单词匹配）
    - 统计关键词出现的次数
    - 根据匹配次数和关键词数量归一化分数

    分数计算：
    - 基础分数：每个匹配的关键词贡献 1/N 分（N 为关键词数量）
    - 频率加权：多次出现的关键词额外加分，最高 1.5 倍
    - 最终分数限制在 0.0-1.0 范围内
    """

    async def calculate_relevance(
        self,
        tweet: "Tweet",
        keywords: list[str],
    ) -> float:
        """计算推文与关键词的相关性分数。

        Args:
            tweet: 推文领域模型
            keywords: 关键词列表

        Returns:
            float: 相关性分数（0.0-1.0）
        """
        try:
            if not keywords:
                return 0.0

            # 准备文本
            text = tweet.text.lower()

            # 统计匹配
            total_matches = 0
            keyword_count = len(keywords)

            for keyword in keywords:
                keyword_lower = keyword.lower()
                # 计算关键词在文本中出现的次数
                matches = len(re.findall(re.escape(keyword_lower), text))
                if matches > 0:
                    # 基础分数：每个关键词最多贡献 1 分
                    # 频率加权：最多 1.5 倍（防止过度加权）
                    weight = min(1.5, 1.0 + (matches - 1) * 0.25)
                    total_matches += weight

            # 归一化分数到 0.0-1.0
            score = min(1.0, total_matches / keyword_count)

            logger.debug(
                f"相关性计算: tweet_id={tweet.tweet_id}, "
                f"keywords={keywords}, score={score:.3f}"
            )

            return score

        except Exception as e:
            logger.error(f"相关性计算失败: {e}")
            # 降级处理：返回 0 分而不是抛出异常
            return 0.0
