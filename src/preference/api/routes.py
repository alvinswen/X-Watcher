"""偏好管理 API 路由模块。

导出所有 API 路由器供主应用集成。
"""

from src.preference.api.scraper_config_router import router as scraper_config_router
from src.preference.api.scraper_config_router import public_router as scraper_public_router

__all__ = ["scraper_config_router", "scraper_public_router"]
