"""user 单元迁移:users + api_keys → users.json(自定义直写,含 password_hash/key_hash)。

为何自定义:FileUserStore 无 seed,且 password_hash/key_hash 是"存而不投"
(UserDomain/ApiKeyInfo 域模型不含 hash,pydantic 读回时 extra=ignore 丢弃)→ 必须直接
构造 on-disk doc。盘面 rec 格式严格对齐 store create_user/create_api_key:
- users[<id>]   = {id, name, email, password_hash, is_admin, created_at}
- api_keys[<id>]= {id, user_id, key_hash, key_prefix, name, is_active, created_at, last_used_at}
- created_at/last_used_at 存 iso STRING(atomic_write_doc 用裸 json.dumps 无 datetime 编码器,
  必须传 str;_now_naive 同样是 naive isoformat 字符串)。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from src.data_layer.migration.base import MigrationReport, naive
from src.data_layer.migration.registry import register
from src.database.models import ApiKey, User
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc
from src.user.infrastructure.file_user_repository import FileUserStore


def _iso(dt):
    n = naive(dt)
    return n.isoformat() if n is not None else None


def _build_doc(users, keys) -> dict:
    """纯函数:ORM 行(或 duck-typed 假对象)→ on-disk doc(便于单测)。"""
    user_recs = {
        str(u.id): {"id": u.id, "name": u.name, "email": u.email,
                    "password_hash": u.password_hash, "is_admin": u.is_admin,
                    "created_at": _iso(u.created_at)}
        for u in users
    }
    key_recs = {
        str(k.id): {"id": k.id, "user_id": k.user_id, "key_hash": k.key_hash,
                    "key_prefix": k.key_prefix, "name": k.name, "is_active": k.is_active,
                    "created_at": _iso(k.created_at), "last_used_at": _iso(k.last_used_at)}
        for k in keys
    }
    return {"users": user_recs, "api_keys": key_recs,
            "_seq": {"users": max((u.id for u in users), default=0),
                     "api_keys": max((k.id for k in keys), default=0)}}


@register("user")
async def migrate_user(session, data_root: Path) -> MigrationReport:
    users = (await session.execute(select(User))).scalars().all()
    keys = (await session.execute(select(ApiKey))).scalars().all()
    rep = MigrationReport(entity="user", pg_count=len(users) + len(keys))
    store = FileUserStore(data_root)
    store._path.unlink(missing_ok=True)
    doc = _build_doc(users, keys)
    async with shard_lock(store._path):
        atomic_write_doc(store._path, doc)
    rep.written = len(users) + len(keys)
    # 校验:① domain 读回(不含 hash)逐字段;② 盘面 JSON 的 hash 直比 pg;③ active key 读回
    disk = read_doc(store._path)
    rep.validated = 0
    for u in users:
        d = await store.get_user_by_id(u.id)
        dr = disk["users"][str(u.id)]
        if (d is not None and d.id == u.id and d.email == u.email and d.name == u.name
                and d.is_admin == u.is_admin and d.created_at == naive(u.created_at)
                and dr["password_hash"] == u.password_hash):
            rep.validated += 1
        else:
            rep.mismatches.append(f"user id={u.id}: domain/hash mismatch")
    for k in keys:
        dr = disk["api_keys"][str(k.id)]
        ok = dr["key_hash"] == k.key_hash and dr["user_id"] == k.user_id
        if k.is_active:  # active key 必须经 hash 读回得到正确 user_id
            got = await store.get_active_key_by_hash(k.key_hash)
            ok = ok and got is not None and got[1] == k.user_id and got[0].id == k.id
        if ok:
            rep.validated += 1
        else:
            rep.mismatches.append(f"api_key id={k.id}: hash/user mismatch")
    return rep
