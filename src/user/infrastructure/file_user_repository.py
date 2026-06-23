# src/user/infrastructure/file_user_repository.py
"""文件版 UserStore:data/users/users.json 单文件双集合。

盘面: {"users": {<id>: {id,name,email,password_hash,is_admin,created_at}},
       "api_keys": {<id>: {id,user_id,key_hash,key_prefix,name,is_active,created_at,last_used_at}},
       "_seq": {"users": N, "api_keys": M}}
- _seq.users / _seq.api_keys 各自 +1 单调;无 delete → 永不回收(deactivate 软态不删行)
- shard_lock 下 load→mutate→atomic_write_doc(写路径);读路径无锁(同前十一片)
- 参数式接口:create_user/create_api_key/update_user 收散列参数,手工建 rec(含 password_hash/key_hash + naive now)
- password_hash/key_hash 存盘但 Domain(**rec) extra-ignore 丢弃(存而不投)
- email 唯一性文件层手动拦 → DuplicateError(进 parity,两侧同类型)
- key_hash 唯一性文件层手动拦 → DuplicateError(changed:旧抛裸 IntegrityError;出 parity 入 invariant)
- update_password_hash/update_key_last_used 缺 id 静默 no-op(复刻旧 bulk update 无 NotFound)
- deactivate_key 软态(翻 is_active);缺 id → NotFoundError
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.user.domain.models import ApiKeyInfo, UserDomain
from src.user.infrastructure.user_store import DuplicateError, NotFoundError
from src.storage.atomic import shard_lock
from src.storage.doc_store import atomic_write_doc, read_doc


def _now_naive() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


class FileUserStore:
    """UserStore 的文件实现(14 方法)。"""

    def __init__(self, data_root: Path) -> None:
        self._path = Path(data_root) / "users" / "users.json"

    def _load(self) -> dict:
        doc = read_doc(self._path)
        if doc is None:
            doc = {}
        doc.setdefault("users", {})
        doc.setdefault("api_keys", {})
        seq = doc.setdefault("_seq", {})
        seq.setdefault("users", 0)
        seq.setdefault("api_keys", 0)
        return doc

    @staticmethod
    def _to_user(rec: dict) -> UserDomain:
        return UserDomain(**rec)

    @staticmethod
    def _to_apikey(rec: dict) -> ApiKeyInfo:
        return ApiKeyInfo(**rec)

    # —— users ——
    async def create_user(self, name: str, email: str, password_hash: str) -> UserDomain:
        async with shard_lock(self._path):
            doc = self._load()
            for rec in doc["users"].values():
                if rec["email"] == email:
                    raise DuplicateError(f"该邮箱已被注册: {email}")
            doc["_seq"]["users"] = int(doc["_seq"]["users"]) + 1
            uid = doc["_seq"]["users"]
            rec = {"id": uid, "name": name, "email": email, "password_hash": password_hash,
                   "is_admin": False, "created_at": _now_naive()}
            doc["users"][str(uid)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_user(rec)

    async def get_user_by_id(self, user_id: int) -> UserDomain | None:
        rec = self._load()["users"].get(str(user_id))
        return self._to_user(rec) if rec is not None else None

    async def get_user_by_email(self, email: str) -> UserDomain | None:
        for rec in self._load()["users"].values():
            if rec["email"] == email:
                return self._to_user(rec)
        return None

    async def get_password_hash_by_id(self, user_id: int) -> str | None:
        rec = self._load()["users"].get(str(user_id))
        return rec["password_hash"] if rec is not None else None

    async def get_password_hash_by_email(self, email: str) -> str | None:
        for rec in self._load()["users"].values():
            if rec["email"] == email:
                return rec["password_hash"]
        return None

    async def get_all_users(self) -> list[UserDomain]:
        return [self._to_user(r) for r in self._load()["users"].values()]

    async def update_user(self, user_id: int, name: str | None = None,
                          email: str | None = None, is_admin: bool | None = None) -> UserDomain:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["users"].get(str(user_id))
            if rec is None:
                raise NotFoundError(f"用户不存在: {user_id}")
            if email is not None:
                for oid, other in doc["users"].items():
                    if oid != str(user_id) and other["email"] == email:
                        raise DuplicateError(f"该邮箱已被注册: {email}")
            if name is not None:
                rec["name"] = name
            if email is not None:
                rec["email"] = email
            if is_admin is not None:
                rec["is_admin"] = is_admin
            doc["users"][str(user_id)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_user(rec)

    async def count_admins(self) -> int:
        return sum(1 for r in self._load()["users"].values() if r["is_admin"])

    async def update_password_hash(self, user_id: int, password_hash: str) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["users"].get(str(user_id))
            if rec is None:
                return
            rec["password_hash"] = password_hash
            doc["users"][str(user_id)] = rec
            atomic_write_doc(self._path, doc)

    # —— api_keys ——
    async def create_api_key(self, user_id: int, key_hash: str, key_prefix: str,
                             name: str = "default") -> ApiKeyInfo:
        async with shard_lock(self._path):
            doc = self._load()
            for rec in doc["api_keys"].values():
                if rec["key_hash"] == key_hash:
                    raise DuplicateError(f"API Key 已存在: {key_hash}")
            doc["_seq"]["api_keys"] = int(doc["_seq"]["api_keys"]) + 1
            kid = doc["_seq"]["api_keys"]
            rec = {"id": kid, "user_id": user_id, "key_hash": key_hash, "key_prefix": key_prefix,
                   "name": name, "is_active": True, "created_at": _now_naive(), "last_used_at": None}
            doc["api_keys"][str(kid)] = rec
            atomic_write_doc(self._path, doc)
            return self._to_apikey(rec)

    async def get_active_key_by_hash(self, key_hash: str) -> tuple[ApiKeyInfo, int] | None:
        for rec in self._load()["api_keys"].values():
            if rec["key_hash"] == key_hash and rec["is_active"]:
                return self._to_apikey(rec), rec["user_id"]
        return None

    async def get_keys_by_user(self, user_id: int) -> list[ApiKeyInfo]:
        return [self._to_apikey(r) for r in self._load()["api_keys"].values()
                if r["user_id"] == user_id]

    async def deactivate_key(self, key_id: int) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["api_keys"].get(str(key_id))
            if rec is None:
                raise NotFoundError(f"API Key 不存在: {key_id}")
            rec["is_active"] = False
            doc["api_keys"][str(key_id)] = rec
            atomic_write_doc(self._path, doc)

    async def update_key_last_used(self, key_id: int) -> None:
        async with shard_lock(self._path):
            doc = self._load()
            rec = doc["api_keys"].get(str(key_id))
            if rec is None:
                return
            rec["last_used_at"] = _now_naive()
            doc["api_keys"][str(key_id)] = rec
            atomic_write_doc(self._path, doc)
