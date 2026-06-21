"""M-5 子项目 2 集成冒烟:file 模式下 follows/profile 经 provider 端到端 + 真实迁移数据。

跑法(旧应用 venv,先重生 data_migrated):
  XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=./data_migrated .venv/bin/python scripts/verify_preference_file_layer.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ["XWATCHER_DATA_LAYER"] = "file"
DATA_ROOT = os.environ.get("XWATCHER_DATA_ROOT", "./data_migrated")


async def main() -> int:
    from src.data_layer.provider import get_follows_repo, get_profile_repo
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    from src.preference.infrastructure.file_profile_repository import FileProfileStore

    # ① provider 切换
    assert isinstance(get_follows_repo(None), FileFollowStore), "follows provider 未切到 file"
    assert isinstance(get_profile_repo(None), FileProfileStore), "profile provider 未切到 file"

    # ② round-trip via provider(临时 data_root,不污染 data_migrated)
    tmp = tempfile.mkdtemp(prefix="m5-pref-")
    os.environ["XWATCHER_DATA_ROOT"] = tmp
    f = get_follows_repo(None)
    await f.create_scraper_follow(username="verify_alice", reason="m5", added_by="verify")
    assert (await f.get_follow_by_username("verify_alice")) is not None, "follows round-trip 失败"
    assert (Path(tmp) / "follows" / "follows.json").exists(), "follows 未落盘"

    # ③ 真实调用点 + 真实迁移数据(指回 data_migrated)
    os.environ["XWATCHER_DATA_ROOT"] = DATA_ROOT
    follows = await get_follows_repo(None).get_all_follows(include_inactive=True)
    profiles = await get_profile_repo(None).get_all_profiles()
    assert len(follows) == 64, f"follows 真实数据计数异常: {len(follows)} (期望 64)"
    assert len(profiles) == 64, f"profiles 真实数据计数异常: {len(profiles)} (期望 64)"
    # 抽样字段非空(证不是空壳读)
    assert all(x.username for x in follows[:5]), "follows 抽样 username 为空"
    assert all(x.platform_user_id for x in profiles[:5]), "profiles 抽样 platform_user_id 为空"

    print(f"VERIFY OK: provider 切换 / round-trip / 真实调用点(follows {len(follows)} + profiles {len(profiles)})三级证据全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
