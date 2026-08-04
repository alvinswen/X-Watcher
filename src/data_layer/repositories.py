"""数据层仓储契约门面：为 provider.py 的 get_*_repo 工厂提供返回类型契约。

本文件只在类型检查期起作用，运行时零开销（全部符号在 TYPE_CHECKING 下引用，
Protocol 类本身不被实例化、不被继承）。

## 如何加宽本契约（施工者必读）

本文件的契约按「实测真正被调用到的成员」编写（CHG-043 Gate 1 Q3=B），**不是实现类的全量镜像**。
因此当你要用一个尚未写进契约的仓库能力时，mypy 会报：

    "XxxRepo" has no attribute "your_method"  [attr-defined]

**这不是故障，是预期行为。** 处理办法：

1. 打开该契约对应的实现类（每个 Protocol 下方的 `_assert_N` 断言里写明了实现类路径）；
2. 把你要用的那个方法的**签名整行照抄**进本文件对应的 Protocol 里，方法体写 `...`；
3. 重跑 `bash scripts/check-types.sh`，绿灯即可。

**不要**用 `# type: ignore` 绕过，也**不要**把返回类型改回 `Any`——
本项目门禁语义为「通过 = 全仓 0 类型债」（DIFF-004 收官口径），不得倒退。

## 防漂移闸（文件末尾 _assert_N）

每个契约配一道静态实现断言：把实现类喂给契约形参，实现与契约对不上时 mypy 当场报红。
这些断言**只在类型检查期存在，运行时零开销**（整块在 `if TYPE_CHECKING:` 内）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from src.api.status_schemas import FollowStats, SummaryStats, TweetStats
    from src.feed.domain.models import FeedResult
    from src.scraper.domain.fetch_stats import FetchStats
    from src.scraper.domain.models import Article, SaveResult, Tweet
    from src.scraper.domain.scrape_group_state import ScrapeGroupState
    from src.search.domain.models import SearchResult
    from src.source_candidates.models import CandidateStatus, MiningSignal, SourceCandidate
    from src.summarization.domain.models import SummaryRecord


class TweetStore(Protocol):
    """get_tweet_repo() 的返回契约（实现：FileTweetStore）。"""

    async def save_tweets(
        self, tweets: list[Tweet], early_stop_threshold: int = 5
    ) -> SaveResult: ...


class TweetReadStore(Protocol):
    """get_tweet_read_repo() 的返回契约（实现：FileTweetReadStore）。"""

    async def list_tweets(
        self,
        *,
        page: int,
        page_size: int,
        author: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_tweet_detail(self, tweet_id: str) -> dict[str, Any] | None: ...


class ArticleStore(Protocol):
    """get_article_repo() 的返回契约（实现：FileArticleStore）。"""

    async def article_exists(self, tweet_id: str) -> bool: ...

    async def save_article(self, article: Article) -> bool: ...


class ArticleReadStore(Protocol):
    """get_article_read_repo() 的返回契约（实现：FileArticleReadStore）。"""

    async def get_unarticled_tweets(
        self, username: str, max_tweets: int = 200
    ) -> list[str]: ...


class FetchStatsStore(Protocol):
    """get_fetch_stats_repo() 的返回契约（实现：FileFetchStatsStore）。"""

    async def get_stats(self, username: str) -> FetchStats | None: ...

    async def upsert_stats(self, stats: FetchStats) -> None: ...


class SummaryStore(Protocol):
    """get_summary_repo() 的契约；统一放在此处，summary_store.py 仅含 RepositoryError。"""

    async def get_summary_by_tweet(self, tweet_id: str) -> SummaryRecord | None: ...

    async def save_summary_record(self, record: SummaryRecord) -> SummaryRecord: ...


class SummarizationReadStore(Protocol):
    """get_summarization_read_repo() 的返回契约（实现：FileSummarizationReadStore）。"""

    async def get_unsummarized_tweets(
        self, since: Any = None, until: Any = None, author: Any = None, limit: Any = 50
    ) -> list[dict[str, Any]]: ...

    async def get_tweet_origins(self, tweet_ids: Any) -> dict[str, Any]: ...


class BrowseReadStore(Protocol):
    """get_browse_repo() 的返回契约（实现：FileBrowseReadStore）。"""

    async def get_tweets(
        self,
        date: Any,
        author: Any,
        page: Any,
        page_size: Any,
        tz_offset: Any = 0,
        min_text_length: Any = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_author_timeline(
        self,
        author: Any,
        since_utc: Any,
        until_utc: Any,
        page: Any,
        page_size: Any,
        min_text_length: Any = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int]: ...

    async def get_daily_stats(
        self, year: Any, month: Any, tz_offset: Any = 0, min_text_length: Any = None
    ) -> list[dict[str, Any]]: ...

    async def get_authors(
        self, date: Any, tz_offset: Any = 0, min_text_length: Any = None
    ) -> list[dict[str, Any]]: ...


class FeedReadStore(Protocol):
    """get_feed_repo() 的返回契约（实现：FileFeedReadStore）。"""

    async def get_feed(
        self,
        since: Any,
        until: Any,
        limit: Any,
        include_summary: Any = True,
        author: Any = None,
        authors: Any = None,
        keyword: Any = None,
    ) -> FeedResult: ...


class SearchReadStore(Protocol):
    """get_search_repo() 的返回契约（实现：FileSearchReadStore）。"""

    async def search_tweets(
        self,
        q: Any,
        page: Any = 1,
        page_size: Any = 20,
        include_summary: Any = True,
        author: Any = None,
        authors: Any = None,
        since: Any = None,
        until: Any = None,
    ) -> SearchResult: ...


class ScraperStatsReadStore(Protocol):
    """get_scraper_stats_repo() 的返回契约（实现：FileScraperStatsReadStore）。"""

    async def tweet_time_range(
        self, usernames: list[str]
    ) -> dict[str, tuple[datetime | None, datetime | None, int]]: ...

    async def period_analysis(
        self, username: str, interval_hours: int, periods: int
    ) -> list[tuple[datetime, datetime, int]]: ...


class StatusReadStore(Protocol):
    """get_status_repo() 的返回契约（实现：FileStatusReadStore）。"""

    async def get_tweet_stats(self) -> TweetStats: ...

    async def get_follow_stats(self) -> FollowStats: ...

    async def get_summary_stats(self) -> SummaryStats: ...


class SourceCandidateStore(Protocol):
    """get_source_candidate_repo() 的返回契约（实现：FileSourceCandidateStore）。"""

    async def get_candidate(self, candidate_id: str) -> SourceCandidate | None: ...

    async def list_candidates(
        self,
        status: CandidateStatus | None = None,
        subject_id: str | None = None,
    ) -> list[SourceCandidate]: ...

    async def upsert_candidate(self, candidate: SourceCandidate) -> None: ...

    async def get_candidate_by_platform_user_id(
        self, platform_user_id: str
    ) -> SourceCandidate | None: ...

    async def all_index_entries(self) -> dict[str, dict[str, Any]]: ...

    async def scan_citation_signals(
        self,
        tweet_id_filter: set[str] | None,
        since: datetime | None,
        until: datetime | None,
    ) -> dict[str, Any]: ...

    async def rebuild_index(self) -> None: ...

    async def merge_mining_signal(
        self,
        candidate_id: str,
        signal: MiningSignal,
        subject_id: str | None,
    ) -> SourceCandidate: ...


class ScrapeGroupStateStore(Protocol):
    """get_scrape_group_state_repo() 的返回契约。"""

    async def load_all(self) -> list[ScrapeGroupState]: ...

    async def upsert_group(self, state: ScrapeGroupState) -> None: ...

    async def replace_all(self, states: list[ScrapeGroupState]) -> None: ...


if TYPE_CHECKING:
    # === Q6 防漂移闸 · 17 道静态实现断言 ===
    # 机制：把实现类喂给「以契约为形参类型」的函数。实现少方法 / 签名对不上 → mypy 当场红。
    # 只在类型检查期存在，运行时零开销（本块不进字节码）。
    # 新增契约时：在此追加一道同形断言，编号顺延。
    from src.api.status_read_repository import FileStatusReadStore
    from src.browse.infrastructure.file_browse_read_repository import FileBrowseReadStore
    from src.feed.infrastructure.file_feed_read_repository import FileFeedReadStore
    from src.preference.infrastructure.file_follow_repository import FileFollowStore
    from src.preference.infrastructure.file_profile_repository import FileProfileStore
    from src.preference.infrastructure.follow_store import FollowStore
    from src.preference.infrastructure.profile_store import ProfileStore
    from src.preference.infrastructure.scraper_stats_read_repository import (
        FileScraperStatsReadStore,
    )
    from src.scraper.infrastructure.article_read_repository import FileArticleReadStore
    from src.scraper.infrastructure.file_article_repository import FileArticleStore
    from src.scraper.infrastructure.file_fetch_stats_repository import FileFetchStatsStore
    from src.scraper.infrastructure.file_scrape_group_state_repository import (
        FileScrapeGroupStateStore,
    )
    from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
    from src.scraper.infrastructure.tweet_read_repository import FileTweetReadStore
    from src.search.infrastructure.file_search_read_repository import FileSearchReadStore
    from src.source_candidates.infrastructure.file_source_candidate_repository import (
        FileSourceCandidateStore,
    )
    from src.summarization.infrastructure.file_summarization_read_repository import (
        FileSummarizationReadStore,
    )
    from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
    from src.user.infrastructure.file_user_repository import FileUserStore
    from src.user.infrastructure.user_store import UserStore

    # 14 张本文件新写契约
    def _assert_0(s: FileTweetStore) -> TweetStore: return s
    def _assert_1(s: FileTweetReadStore) -> TweetReadStore: return s
    def _assert_2(s: FileArticleStore) -> ArticleStore: return s
    def _assert_3(s: FileArticleReadStore) -> ArticleReadStore: return s
    def _assert_4(s: FileFetchStatsStore) -> FetchStatsStore: return s
    def _assert_5(s: FileSummaryStore) -> SummaryStore: return s
    def _assert_6(s: FileSummarizationReadStore) -> SummarizationReadStore: return s
    def _assert_7(s: FileBrowseReadStore) -> BrowseReadStore: return s
    def _assert_8(s: FileFeedReadStore) -> FeedReadStore: return s
    def _assert_9(s: FileSearchReadStore) -> SearchReadStore: return s
    def _assert_10(s: FileScraperStatsReadStore) -> ScraperStatsReadStore: return s
    def _assert_11(s: FileStatusReadStore) -> StatusReadStore: return s

    # 3 张复用的既有契约（Q4=A 接上电；议题域第 4 张由 CHG-034 在 subjects/protocol.py 自建）
    def _assert_12(s: FileFollowStore) -> FollowStore: return s
    def _assert_13(s: FileProfileStore) -> ProfileStore: return s
    def _assert_14(s: FileUserStore) -> UserStore: return s
    def _assert_15(s: FileSourceCandidateStore) -> SourceCandidateStore: return s
    def _assert_16(s: FileScrapeGroupStateStore) -> ScrapeGroupStateStore: return s
