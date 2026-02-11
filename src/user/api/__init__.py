from src.user.api.auth_router import router as auth_router
from src.user.api.user_router import router as user_router
from src.user.api.admin_user_router import router as admin_user_router

__all__ = ["auth_router", "user_router", "admin_user_router"]
