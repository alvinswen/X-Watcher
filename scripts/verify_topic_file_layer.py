#!/usr/bin/env python
# scripts/verify_topic_file_layer.py
"""file 模式 topic 联调:服务写 → 独立读 topics.json 核对(防假绿)。
用法:XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=<dir> python scripts/verify_topic_file_layer.py"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.database.models import Base
from src.data_layer.provider import get_topic_store, get_topic_summary_task_store
from src.topic.services.topic_service import TopicService
from src.topic.services.topic_summary_service import TopicSummaryService
from src.topic.domain.models import TopicSummaryTaskStatus


async def main() -> int:
    assert os.environ.get("XWATCHER_DATA_LAYER") == "file", "必须 file 模式"
    data_root = Path(os.environ.get("XWATCHER_DATA_ROOT", "data_migrated"))
    topics_json = data_root / "topics" / "topics.json"
    assert topics_json.exists(), f"无迁移数据: {topics_json}"

    # 服务侧需要一个 session 对象(file 模式忽略其数据,但 commit no-op + 跨域校验占位)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()

    # 1) 独立读迁移数据基线
    before = json.loads(topics_json.read_text())
    n_topics_before = len(before["topics"])
    print(f"[基线] 迁移 topics={n_topics_before}")

    # 2) 服务写一个新 topic + task + summary(file 模式)
    svc_t, svc_s = TopicService(), TopicSummaryService(providers=[])
    t = await svc_t.create_topic(session, name="__verify_probe__", description="probe")
    task = await svc_s.save_external_summary(
        session, topic_id=t.id, content="probe-report", time_span_hours=1,
        deadline=datetime(2026, 1, 1), tz_offset=0, tweet_count=0, account_count=0)
    print(f"[服务] 新建 topic id={t.id} task id={task.id} status={task.status}")

    # 3) 服务回读
    got = await svc_s.get_task(session, task.id)
    assert got is not None and got.summary.content == "probe-report", "服务回读失败"

    # 4) 绕服务,独立读文件核对(防假绿)
    after = json.loads(topics_json.read_text())
    assert str(t.id) in after["topics"], "文件中无新 topic"
    assert after["topics"][str(t.id)]["name"] == "__verify_probe__"
    assert any(s["content"] == "probe-report" for s in after["summaries"].values()), "文件中无新 summary"
    assert len(after["topics"]) == n_topics_before + 1
    print(f"[独立核对] 文件 topics={len(after['topics'])}(+1)、summary 落盘 OK")

    # 5) 清理 probe,恢复迁移数据
    assert await svc_s.delete_task(session, task.id) is True
    assert await svc_t.delete_topic(session, t.id) is True
    restored = json.loads(topics_json.read_text())
    assert str(t.id) not in restored["topics"] and len(restored["topics"]) == n_topics_before
    print(f"[清理] probe 已删,topics 恢复={len(restored['topics'])}")

    await session.close()
    await engine.dispose()
    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
