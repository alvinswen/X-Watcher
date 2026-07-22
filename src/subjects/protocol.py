"""议题仓储契约与带类型工厂。

- SubjectRepoProtocol: FileSubjectStore 公开方法面的结构化接口承诺
  (32 成员 = 31 既有公开方法 + publish_window_matches 转正, 编译期检查、运行时零开销)。
- default_subject_repo(): 议题仓储获取单点, 内部包裹 provider.get_subject_repo()
  (黑名单① 不绕行: 不直构 FileSubjectStore、不改 provider 签名)。
- 静态实现断言(文件末尾): FileSubjectStore 与本契约漂移时 mypy 门禁即红。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.subjects.models import (
    Provenance,
    Subject,
    SubjectDigest,
    SubjectEval,
    SubjectFeedback,
    SubjectMatch,
    SubjectReview,
    SubjectStatus,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from src.subjects.store import FileSubjectStore, PublishWindowMatches


@runtime_checkable
class SubjectRepoProtocol(Protocol):
    """镜像 src/subjects/store.py FileSubjectStore 公开方法面(签名逐字段一致)。"""

    async def list_subjects(self, status: str | None = None) -> list[Subject]: ...

    async def list_active_subjects(self) -> list[Subject]: ...

    async def active_count(self) -> int: ...

    async def get_subject(self, subject_id: str) -> Subject | None: ...

    async def create_subject(
        self,
        *,
        name: str,
        nl_description: str,
        keywords: list[str] | None = None,
        status: SubjectStatus = SubjectStatus.active,
    ) -> Subject: ...

    async def save_subject(self, subject: Subject) -> Subject: ...

    async def update_subject(
        self,
        subject_id: str,
        *,
        name: str | None = None,
        nl_description: str | None = None,
        keywords: list[str] | None = None,
        status: SubjectStatus | None = None,
    ) -> Subject | None: ...

    async def touch_subject(self, subject_id: str, when: datetime | None = None) -> None: ...

    async def set_pending(
        self,
        subject_id: str,
        *,
        classify: bool | None = None,
        review: bool | None = None,
    ) -> Subject | None: ...

    async def list_pending(self, subject_id: str | None = None) -> list[dict[str, bool | str]]: ...

    async def delete_subject(self, subject_id: str) -> bool: ...

    async def upsert_matches(self, matches: Iterable[SubjectMatch]) -> list[SubjectMatch]: ...

    async def list_matches(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[SubjectMatch]: ...

    async def count_matches(self, subject_id: str) -> int: ...

    async def last_classified_at(self, subject_id: str) -> datetime | None: ...

    async def save_digest(self, digest: SubjectDigest) -> SubjectDigest: ...

    async def append_feedback(self, feedback: SubjectFeedback) -> SubjectFeedback: ...

    async def append_eval(self, eval_record: SubjectEval) -> SubjectEval: ...

    async def read_feedbacks(self, subject_id: str) -> list[SubjectFeedback]: ...

    async def read_evals(self, subject_id: str) -> list[SubjectEval]: ...

    async def list_digests(
        self,
        subject_id: str,
        limit: int = 24,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[SubjectDigest]: ...

    async def get_digest(
        self,
        subject_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> SubjectDigest | None: ...

    async def save_review(self, review: SubjectReview) -> SubjectReview: ...

    async def save_provenance(
        self,
        *,
        subject_id: str,
        kind: str,
        key: str,
        provenance: Provenance,
    ) -> Provenance: ...

    async def read_provenance(
        self,
        *,
        subject_id: str,
        kind: str,
        key: str,
    ) -> Provenance | None: ...

    async def get_review(self, subject_id: str) -> SubjectReview | None: ...

    async def list_review_history(self, subject_id: str) -> list[SubjectReview]: ...

    async def get_tweets_by_ids(
        self, tweet_ids: list[str]
    ) -> tuple[list[dict[str, Any]], list[str]]: ...

    async def get_tweet_author_ids(
        self,
        tweet_ids: list[str],
    ) -> tuple[dict[str, str | None], list[str]]: ...

    async def publish_window_matches(
        self,
        subject_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> PublishWindowMatches: ...

    async def get_subject_feed(
        self,
        subject_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        time_axis: str = "ingest",
    ) -> dict[str, Any]: ...

    async def get_updates(
        self, since_cursor: str | None = None, limit: int = 200
    ) -> dict[str, Any]: ...


def default_subject_repo() -> SubjectRepoProtocol:
    """议题仓储获取单点(全域 34 处获取点统一入口)。

    历史过渡状态(CHG-043 起): provider.get_subject_repo() 自身已带类型契约
    (-> SubjectRepoProtocol), 本函数退化为薄透传。议题域沿用本入口不动;
    其余域直接用 provider 带类型入口即可。二者归一另行安排。
    CHG-034 当年建本函数的理由是「provider 签名/实现零改动」硬约束,
    该约束已由 CHG-043 Gate 1 Q1=A 正式解除。
    import 延迟到函数内, 与 provider 自身惰性风格一致(env 变更逐调用生效)。
    """
    from src.data_layer.provider import get_subject_repo

    return get_subject_repo()


if TYPE_CHECKING:
    # 静态实现断言(本包机器闸门核心): cast 不校验结构实现,
    # 这里让 mypy 真验 FileSubjectStore ⊨ SubjectRepoProtocol ——
    # 32 成员任一签名漂移(含 keyword-only `*` 与默认值差异)门禁即红。
    def _assert_file_subject_store_implements(store: FileSubjectStore) -> SubjectRepoProtocol:
        return store
