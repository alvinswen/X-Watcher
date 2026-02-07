"""推文去重检测器。

提供精确重复检测和相似内容检测功能。
"""

import logging
from collections import defaultdict

from src.deduplication.domain.models import DuplicateGroup, SimilarGroup
from src.scraper.domain.models import Tweet

logger = logging.getLogger(__name__)


class ExactDuplicateDetector:
    """精确重复检测器。

    检测推文之间的精确重复关系，包括：
    - 文本完全相同的推文
    - 转发关系（referenced_tweet_id + reference_type=retweeted）

    时间复杂度: O(n)
    """

    def detect_duplicates(self, tweets: list[Tweet]) -> list[DuplicateGroup]:
        """检测精确重复组。

        Args:
            tweets: 待检测的推文列表

        Returns:
            重复组列表，每组包含重复的推文和主记录
        """
        if not tweets:
            return []

        # 按文本哈希分组
        text_groups: defaultdict[str, list[Tweet]] = defaultdict(list)
        # 按转发关系分组
        retweet_groups: defaultdict[str, list[Tweet]] = defaultdict(list)

        for tweet in tweets:
            # 检查转发关系
            if (
                tweet.referenced_tweet_id
                and tweet.reference_type
                and tweet.reference_type.value == "retweeted"
            ):
                # 使用被转发的推文 ID 作为分组键
                retweet_groups[tweet.referenced_tweet_id].append(tweet)
            else:
                # 使用文本作为分组键（去除多余空格）
                normalized_text = " ".join(tweet.text.split())
                text_groups[normalized_text].append(tweet)

        # 合并转发关系和文本相同的情况
        # 转发关系中，原推文可能在 tweets 列表中
        all_groups: list[list[Tweet]] = []

        # 处理文本相同组
        for group in text_groups.values():
            if len(group) > 1:
                all_groups.append(group)

        # 处理转发组
        for original_id, retweets in retweet_groups.items():
            # 查找原推文是否在列表中
            original_tweets = [t for t in tweets if t.tweet_id == original_id]
            group = original_tweets + retweets
            if len(group) > 1:
                all_groups.append(group)

        # 转换为 DuplicateGroup
        result = []
        for group in all_groups:
            # 选择最早创建的推文作为代表
            sorted_group = sorted(group, key=lambda t: t.created_at)
            representative = sorted_group[0]

            duplicate_group = DuplicateGroup(
                representative_id=representative.tweet_id,
                tweet_ids=[t.tweet_id for t in sorted_group],
                created_at=representative.created_at,
            )
            result.append(duplicate_group)

        logger.debug(
            f"精确重复检测: 输入 {len(tweets)} 条推文, "
            f"发现 {len(result)} 个重复组"
        )

        return result


class SimilarityDetector:
    """相似内容检测器。

    使用 TF-IDF 和余弦相似度检测内容相似的推文。

    时间复杂度: O(n^2) 受相似度矩阵计算影响
    """

    def __init__(self) -> None:
        """初始化相似度检测器。"""
        self._vectorizer = None
        self._model_loaded = False

    def _preprocess_text(self, text: str) -> str:
        """预处理文本。

        移除 URL、提及、多余空格，转换为小写。

        Args:
            text: 原始文本

        Returns:
            预处理后的文本
        """
        import re

        # 移除 URL
        text = re.sub(r"http\S+|www\S+", "", text)
        # 移除提及
        text = re.sub(r"@\w+", "", text)
        # 移除多余空格和换行
        text = " ".join(text.split())
        # 转小写
        text = text.lower()

        return text

    def detect_similar(
        self,
        tweets: list[Tweet],
        threshold: float = 0.85,
    ) -> list[SimilarGroup]:
        """检测相似内容组。

        Args:
            tweets: 待检测的推文列表
            threshold: 相似度阈值（0-1）

        Returns:
            相似组列表，包含相似度分数
        """
        if not tweets or len(tweets) < 2:
            return []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            # 预处理文本
            texts = [self._preprocess_text(tweet.text) for tweet in tweets]

            # 创建 TF-IDF 向量
            if self._vectorizer is None:
                self._vectorizer = TfidfVectorizer(
                    max_features=1000,
                    min_df=1,
                    ngram_range=(1, 2),
                )

            tfidf_matrix = self._vectorizer.fit_transform(texts)

            # 计算相似度矩阵
            similarity_matrix = cosine_similarity(tfidf_matrix)

            # 根据阈值分组
            groups = self._group_by_similarity(
                tweets, similarity_matrix, threshold
            )

            logger.debug(
                f"相似度检测: 输入 {len(tweets)} 条推文, "
                f"阈值 {threshold}, 发现 {len(groups)} 个相似组"
            )

            return groups

        except ImportError:
            logger.warning("scikit-learn 未安装，跳过相似度检测")
            return []
        except Exception as e:
            logger.error(f"相似度检测失败: {e}")
            return []

    def _group_by_similarity(
        self,
        tweets: list[Tweet],
        similarity_matrix: list[list[float]],
        threshold: float,
    ) -> list[SimilarGroup]:
        """根据相似度矩阵分组。

        使用简单的贪心算法：
        1. 遍历相似度矩阵的上三角
        2. 当相似度 >= 阈值时，将两条推文加入同一组
        3. 合并重叠的组

        Args:
            tweets: 推文列表
            similarity_matrix: 相似度矩阵
            threshold: 相似度阈值

        Returns:
            相似组列表
        """
        n = len(tweets)
        visited = [False] * n
        groups: list[set[int]] = []

        for i in range(n):
            if visited[i]:
                continue

            current_group = {i}

            for j in range(i + 1, n):
                if similarity_matrix[i][j] >= threshold:
                    current_group.add(j)

            # 合并重叠的组
            merged = False
            for group in groups:
                if current_group & group:  # 有交集
                    group.update(current_group)
                    for idx in group:
                        visited[idx] = True
                    merged = True
                    break

            if not merged and len(current_group) > 1:
                groups.append(current_group)
                for idx in current_group:
                    visited[idx] = True

        # 转换为 SimilarGroup
        result = []
        for group in groups:
            if len(group) < 2:
                continue

            group_tweets = [tweets[idx] for idx in sorted(group)]
            # 选择最早创建的推文作为代表
            representative = min(group_tweets, key=lambda t: t.created_at)

            # 计算平均相似度
            avg_similarity = self._calculate_avg_similarity(
                list(group), similarity_matrix
            )

            similar_group = SimilarGroup(
                representative_id=representative.tweet_id,
                tweet_ids=[t.tweet_id for t in group_tweets],
                similarity_score=avg_similarity,
            )
            result.append(similar_group)

        return result

    def _calculate_avg_similarity(
        self,
        indices: list[int],
        similarity_matrix: list[list[float]],
    ) -> float:
        """计算组的平均相似度。

        Args:
            indices: 组内推文索引列表
            similarity_matrix: 相似度矩阵

        Returns:
            平均相似度
        """
        if len(indices) < 2:
            return 1.0

        total = 0.0
        count = 0

        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                total += similarity_matrix[indices[i]][indices[j]]
                count += 1

        return total / count if count > 0 else 0.0
