"""M-5 子项目 0 集成冒烟:file 模式下 schedule 经 provider 端到端 + 真实调用点(main helper)。

跑法(旧应用 venv):
  XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=$(mktemp -d) .venv/bin/python scripts/verify_schedule_file_layer.py
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ["XWATCHER_DATA_LAYER"] = "file"
os.environ.setdefault("XWATCHER_DATA_ROOT", tempfile.mkdtemp(prefix="m5-schedule-"))


async def main() -> int:
    from src.data_layer.provider import get_schedule_repo

    # ① provider 切换
    from src.preference.infrastructure.file_schedule_repository import FileScheduleStore
    assert isinstance(get_schedule_repo(None), FileScheduleStore), "provider 未切到 file"

    # ② round-trip via provider
    await get_schedule_repo(None).upsert_schedule_config(
        interval_seconds=600, is_enabled=True,
        next_run_time=datetime(2030, 1, 1, 0, 0, 0), updated_by="m5-verify",
    )
    cfg = await get_schedule_repo(None).get_schedule_config()
    assert cfg is not None and cfg.interval_seconds == 600 and cfg.is_enabled is True, "round-trip 失败"

    # ③ 真实调用点:main._get_schedule_config_from_db(file 模式 session 开而不用)
    from src.main import _get_schedule_config_from_db
    interval, _next, enabled = await _get_schedule_config_from_db()
    assert interval == 600 and enabled is True, f"真实调用点 file 模式返回异常: {(interval, enabled)}"

    print("VERIFY OK: provider 切换 / round-trip / 真实调用点(main)三级证据全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
