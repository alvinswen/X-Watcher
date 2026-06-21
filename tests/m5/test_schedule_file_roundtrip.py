"""M-5 schedule 文件层 round-trip:经 provider upsert→get 回读一致 + 盘面落地。

这同时验证:se file store 在旧应用解释器内用旧应用域模型 ScraperScheduleConfig 构造成功(域字段兼容)。
"""
from datetime import datetime


async def test_schedule_upsert_get_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    from src.data_layer.provider import get_schedule_repo

    repo = get_schedule_repo(session=None)
    await repo.upsert_schedule_config(
        interval_seconds=300,
        is_enabled=True,
        next_run_time=datetime(2030, 1, 1, 0, 0, 0),
        updated_by="m5",
    )
    cfg = await repo.get_schedule_config()

    assert cfg is not None
    assert cfg.interval_seconds == 300
    assert cfg.is_enabled is True
    assert cfg.updated_by == "m5"
    assert (tmp_path / "schedule" / "schedule.json").exists()
