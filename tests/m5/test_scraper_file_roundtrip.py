"""M-5 scraper 文件层 round-trip:scheduler-log 同步写入器经 provider 写→异步 repo 读一致。

验证本片真新东西:file 模式同步桥接(asyncio.run)端到端落盘 + id 分配。
本测试是 sync def(非 async)——同步桥接内部 asyncio.run 不能在 running loop 内调,
sync 测试无 running loop,恰好镜像 BackgroundScheduler 同步线程上下文。
"""

import asyncio


def test_scheduler_log_sync_write_then_async_read(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_scheduler_log_repo, get_scheduler_log_sync_writer
    from src.scraper.domain.scheduler_log import SchedulerEventType, SchedulerExecutionLog

    writer = get_scheduler_log_sync_writer()
    log = SchedulerExecutionLog(
        job_id="job-roundtrip-1",
        event_type=SchedulerEventType.EXECUTED,
        duration_seconds=1.5,
    )
    writer.write_log(log)  # 同步调用,内部 asyncio.run —— 测试无 running loop,OK

    repo = get_scheduler_log_repo()
    logs = asyncio.run(repo.get_recent_logs(limit=10))
    assert any(l.job_id == "job-roundtrip-1" for l in logs)
    matched = next(l for l in logs if l.job_id == "job-roundtrip-1")
    assert matched.event_type == SchedulerEventType.EXECUTED
    assert matched.id == 1  # seq+1 分配
    assert (tmp_path / "scheduler_logs" / "scheduler_logs.json").exists()
