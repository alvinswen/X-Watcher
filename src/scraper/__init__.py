"""新闻抓取器包。

提供从 X 平台抓取推文数据的功能。
"""

from src.scraper.client import TwitterClient, TwitterClientError
from src.scraper.domain.models import Media, ReferenceType, Tweet
from src.scraper.parser import TweetParser
from src.scraper.scraping_service import ScrapingService
from src.scraper.services.article_fetch_service import ArticleFetchService
from src.scraper.services.profile_sync_service import ProfileSyncService
from src.scraper.task_registry import TaskRegistry, TaskStatus
from src.scraper.validator import TweetValidator

__all__ = [
    "TwitterClient",
    "TwitterClientError",
    "Media",
    "ReferenceType",
    "Tweet",
    "TweetParser",
    "TweetValidator",
    "TaskRegistry",
    "TaskStatus",
    "ScrapingService",
    "ArticleFetchService",
    "ProfileSyncService",
]
