"""M-5 数据层 provider:按 XWATCHER_DATA_LAYER 在旧 SQLAlchemy repo 与 se 文件层 store 间切换。

- 默认 sqlalchemy:旧应用零行为变化;设 XWATCHER_DATA_LAYER=file 切到文件层。
- 文件层 store 经 scripts/link_se_stores.sh 符号链接进 src.* 命名空间。
- import 延迟到函数内,使 env 变更逐调用生效(测试可 monkeypatch)。
"""
from __future__ import annotations

import os
from pathlib import Path


def _data_layer() -> str:
    return os.environ.get("XWATCHER_DATA_LAYER", "sqlalchemy").strip().lower()


def _data_root() -> Path:
    return Path(os.environ.get("XWATCHER_DATA_ROOT", "data"))


def get_schedule_repo(session=None):
    """返回 ScheduleStore 形态 repo(get_schedule_config / upsert_schedule_config)。

    file 模式:FileScheduleStore(data_root),忽略 session。
    sqlalchemy 模式:ScraperScheduleRepository(session)。
    """
    if _data_layer() == "file":
        from src.preference.infrastructure.file_schedule_repository import FileScheduleStore

        return FileScheduleStore(_data_root())
    from src.preference.infrastructure.schedule_repository import ScraperScheduleRepository

    return ScraperScheduleRepository(session)
