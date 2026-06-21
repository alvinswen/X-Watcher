"""M-5 子项目 4a 联调三级证据:provider 切换 / 真实调用点读真数据 / user 重表达端到端。

用法:XWATCHER_DATA_LAYER=file XWATCHER_DATA_ROOT=./data_migrated .venv/bin/python scripts/verify_summ_user_file_layer.py
判绿:进程退码 0 + 末行打印 'VERIFY OK'(勿用 cmd|tail 取 $?,会吞 SystemExit)。
"""

import asyncio
import os
import sys


def _fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


async def _amain() -> None:
    os.environ["XWATCHER_DATA_LAYER"] = "file"
    data_root = os.environ.get("XWATCHER_DATA_ROOT", "./data_migrated")
    os.environ["XWATCHER_DATA_ROOT"] = data_root

    from src.data_layer.provider import get_summary_repo, get_user_repo
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
    from src.user.infrastructure.file_user_repository import FileUserStore

    # —— 级 1:provider 切换 ——
    if not isinstance(get_summary_repo(), FileSummaryStore):
        _fail("get_summary_repo 非 FileSummaryStore")
    if not isinstance(get_user_repo(), FileUserStore):
        _fail("get_user_repo 非 FileUserStore")
    print("级1 provider 切换 OK")

    # —— 级 2:真实调用点读真数据 ——
    summaries = await get_summary_repo().get_all_summaries()
    if len(summaries) != 41018:
        _fail(f"summary 计数 {len(summaries)} != 41018")
    users = await get_user_repo().get_all_users()
    if len(users) != 3:
        _fail(f"user 计数 {len(users)} != 3")
    print(f"级2 真数据读取 OK(summary={len(summaries)} user={len(users)})")

    # —— 级 3:user 重表达端到端(本片真新东西的直接证据)——
    # 真数据中存在无密码的 bootstrap admin(password_hash=None,忠实保留),
    # 故挑一个真有 bcrypt hash 的用户证明 hash 经文件层往返非空一致。
    repo = get_user_repo()
    sample = None
    no_pw_count = 0
    for u in users:
        if await repo.get_password_hash_by_email(u.email):
            if sample is None:
                sample = u
        else:
            no_pw_count += 1  # 忠实性旁证:无密码 admin 经文件层读回 None
    if sample is None:
        _fail("无任何 user 有非空 password_hash,无法证明 hash 重表达往返")
    sample_email = sample.email
    pw_hash = await repo.get_password_hash_by_email(sample_email)
    if not pw_hash:
        _fail(f"重表达 get_password_hash_by_email({sample_email}) 读出空 hash")
    by_id_hash = await repo.get_password_hash_by_id(sample.id)
    if by_id_hash != pw_hash:
        _fail(f"by_email/by_id 双路径 hash 不一致: {by_id_hash!r} != {pw_hash!r}")
    dom = await repo.get_user_by_email(sample_email)
    if dom is None or dom.email != sample_email:
        _fail("get_user_by_email 域字段读取异常")
    print(
        f"级3 user 重表达端到端 OK(email={sample_email} hash_len={len(pw_hash)} "
        f"by_id==by_email is_admin={dom.is_admin} 无密码用户数={no_pw_count})"
    )

    print("VERIFY OK")


if __name__ == "__main__":
    asyncio.run(_amain())
