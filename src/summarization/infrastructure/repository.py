"""摘要仓储。

管理摘要结果的持久化和查询操作。
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.summarization.domain.models import CostStats, SummaryRecord
from src.summarization.infrastructure.models import SummaryOrm

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """仓库操作错误。"""

    pass


class NotFoundError(RepositoryError):
    """资源未找到错误。"""

    pass


class SummarizationRepository:
    """摘要仓储。

    负责摘要结果的持久化和查询操作。
    """

    def __init__(self, session: AsyncSession) -> None:
        """初始化仓储。

        Args:
            session: 异步数据库会话
        """
        self._session = session

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord:
        """保存摘要记录。

        如果摘要已存在（基于 summary_id），则更新；否则创建新记录。

        Args:
            record: 摘要记录对象

        Returns:
            SummaryRecord: 保存后的摘要记录

        Raises:
            RepositoryError: 保存失败时抛出
        """
        try:
            # 检查是否已存在
            existing = await self._session.get(SummaryOrm, record.summary_id)

            if existing:
                # 更新现有记录
                existing.summary_text = record.summary_text
                existing.translation_text = record.translation_text
                existing.model_provider = record.model_provider
                existing.model_name = record.model_name
                existing.prompt_tokens = record.prompt_tokens
                existing.completion_tokens = record.completion_tokens
                existing.total_tokens = record.total_tokens
                existing.cost_usd = record.cost_usd
                existing.cached = record.cached
                existing.content_hash = record.content_hash
                existing.updated_at = datetime.now(timezone.utc)

                logger.debug(f"更新摘要记录: {record.summary_id}")
            else:
                # 创建新记录
                orm_record = SummaryOrm.from_domain(record)
                self._session.add(orm_record)
                await self._session.flush()

                logger.debug(f"创建摘要记录: {record.summary_id}")

            return record

        except Exception as e:
            logger.error(f"保存摘要记录失败: {e}")
            raise RepositoryError(f"保存摘要记录失败: {e}") from e

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None:
        """根据推文 ID 查询摘要。

        Args:
            tweet_id: 推文 ID

        Returns:
            SummaryRecord 或 None
        """
        try:
            stmt = select(SummaryOrm).where(SummaryOrm.tweet_id == tweet_id)
            result = await self._session.execute(stmt)
            orm_summary = result.scalar_one_or_none()

            if orm_summary:
                return orm_summary.to_domain()

            return None

        except Exception as e:
            logger.error(f"查询推文摘要失败 (tweet_id={tweet_id}): {e}")
            raise RepositoryError(f"查询推文摘要失败: {e}") from e

    async def get_cost_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> CostStats:
        """获取成本统计。

        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）

        Returns:
            CostStats: 成本统计结果

        Raises:
            RepositoryError: 查询失败时抛出
        """
        try:
            # 构建查询
            stmt = select(
                func.sum(SummaryOrm.prompt_tokens).label("prompt_tokens"),
                func.sum(SummaryOrm.completion_tokens).label("completion_tokens"),
                func.sum(SummaryOrm.total_tokens).label("total_tokens"),
                func.sum(SummaryOrm.cost_usd).label("total_cost"),
                func.count(SummaryOrm.summary_id).label("count"),
            )

            # 应用日期范围过滤
            if start_date:
                stmt = stmt.where(SummaryOrm.created_at >= start_date)
            if end_date:
                stmt = stmt.where(SummaryOrm.created_at <= end_date)

            result = await self._session.execute(stmt)
            row = result.one()

            # 查询各提供商的分解数据
            provider_stmt = select(
                SummaryOrm.model_provider,
                func.sum(SummaryOrm.total_tokens).label("tokens"),
                func.sum(SummaryOrm.cost_usd).label("cost"),
                func.count(SummaryOrm.summary_id).label("count"),
            )

            if start_date:
                provider_stmt = provider_stmt.where(SummaryOrm.created_at >= start_date)
            if end_date:
                provider_stmt = provider_stmt.where(SummaryOrm.created_at <= end_date)

            provider_stmt = provider_stmt.group_by(SummaryOrm.model_provider)

            provider_result = await self._session.execute(provider_stmt)
            provider_rows = provider_result.all()

            # 构建提供商分解数据
            provider_breakdown: dict[str, dict[str, float | int]] = {}
            for provider_row in provider_rows:
                provider_breakdown[provider_row.model_provider] = {
                    "total_tokens": provider_row.tokens or 0,
                    "cost_usd": provider_row.cost or 0.0,
                    "count": provider_row.count,
                }

            return CostStats(
                start_date=start_date,
                end_date=end_date,
                total_cost_usd=float(row.total_cost or 0),
                total_tokens=int(row.total_tokens or 0),
                prompt_tokens=int(row.prompt_tokens or 0),
                completion_tokens=int(row.completion_tokens or 0),
                provider_breakdown=provider_breakdown,
            )

        except Exception as e:
            logger.error(f"获取成本统计失败: {e}")
            raise RepositoryError(f"获取成本统计失败: {e}") from e

    async def delete_summary(self, summary_id: str) -> bool:
        """删除摘要记录。

        Args:
            summary_id: 摘要 ID

        Returns:
            bool: 是否成功删除

        Raises:
            NotFoundError: 摘要不存在时抛出
            RepositoryError: 删除失败时抛出
        """
        try:
            orm_summary = await self._session.get(SummaryOrm, summary_id)
            if not orm_summary:
                raise NotFoundError(f"摘要不存在: {summary_id}")

            await self._session.delete(orm_summary)
            await self._session.flush()

            logger.debug(f"删除摘要记录: {summary_id}")
            return True

        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"删除摘要记录失败: {e}")
            raise RepositoryError(f"删除摘要记录失败: {e}") from e

    async def find_by_content_hash(self, content_hash: str) -> SummaryRecord | None:
        """根据内容哈希查询摘要。

        用于缓存查询。

        Args:
            content_hash: 内容哈希

        Returns:
            SummaryRecord 或 None
        """
        try:
            stmt = select(SummaryOrm).where(
                SummaryOrm.content_hash == content_hash,
            ).limit(1)
            result = await self._session.execute(stmt)
            orm_summary = result.scalars().first()

            if orm_summary:
                return orm_summary.to_domain()

            return None

        except Exception as e:
            logger.error(f"根据内容哈希查询摘要失败: {e}")
            raise RepositoryError(f"根据内容哈希查询摘要失败: {e}") from e
