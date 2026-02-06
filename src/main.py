"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.database.models import Base, engine

# 获取配置
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    启动时创建数据库表。
    """
    # 启动时创建数据库表
    Base.metadata.create_all(engine)
    yield
    # 关闭时的清理工作（如果需要）


# 创建 FastAPI 应用
app = FastAPI(
    title="SeriousNewsAgent",
    description="智能新闻助理系统 - 面向科技公司高管的个性化新闻流",
    version="0.1.0",
    lifespan=lifespan,
)

# 配置 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """健康检查端点。"""
    return {"status": "healthy"}


def main():
    """主函数 - 用于开发服务器启动。"""
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
