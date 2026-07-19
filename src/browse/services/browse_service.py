"""Browse 查询服务。

保留浏览路由复用的本地日期窗口计算。
"""

import logging
from datetime import datetime, timedelta, timezone, UTC

logger = logging.getLogger(__name__)


class BrowseService:
    """推文浏览 helper 容器。"""

    @staticmethod
    def _local_date_to_utc_range(
        date_str: str, tz_offset: int
    ) -> tuple[datetime, datetime]:
        """将用户本地日期 + tz_offset 转为 UTC 起止时间。

        Args:
            date_str: 用户本地日期字符串，YYYY-MM-DD 格式
            tz_offset: JS ``getTimezoneOffset()`` 的值（分钟），UTC+8 为 -480。
                       含义为 UTC - local，因此 local + offset = UTC。

        Returns:
            (day_start_utc, day_end_utc) 元组
        """
        local_midnight = datetime.strptime(date_str, "%Y-%m-%d")
        utc_start = (local_midnight + timedelta(minutes=tz_offset)).replace(
            tzinfo=UTC
        )
        utc_end = utc_start + timedelta(days=1)
        return utc_start, utc_end
