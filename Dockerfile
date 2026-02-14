# =============================================================================
# Stage 1: 前端构建 (Vue 3 + Vite)
# =============================================================================
FROM node:20-alpine AS frontend

WORKDIR /build

# 先复制依赖文件以利用缓存
COPY src/web/package.json src/web/package-lock.json* ./

# 安装依赖（有 lockfile 用 ci，无则用 install）
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# 复制前端源码并构建
COPY src/web/ ./
RUN npm run build

# 产出: /build/dist/

# =============================================================================
# Stage 2: Python 依赖安装
# =============================================================================
FROM python:3.11-slim AS python-deps

# 安装编译依赖（gcc for bcrypt/scikit-learn, libpq-dev for asyncpg）
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 复制项目文件用于 pip install
COPY pyproject.toml ./
COPY src/ ./src/

# 创建虚拟环境并安装依赖
RUN python -m venv /build/venv \
    && /build/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /build/venv/bin/pip install --no-cache-dir .

# =============================================================================
# Stage 3: 运行时镜像
# =============================================================================
FROM python:3.11-slim

LABEL maintainer="X-watcher Development Team"
LABEL description="X-watcher - AI Agent-oriented X Platform Monitoring Service"

# 安装运行时依赖（libpq5 for PostgreSQL, curl for healthcheck）
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r appuser -g 1000 \
    && useradd -r -u 1000 -g appuser -m -s /bin/bash appuser

WORKDIR /app

# 从 Stage 2 复制 Python 虚拟环境
COPY --from=python-deps /build/venv /app/venv

# 复制应用源码
COPY --chown=appuser:appuser src/ /app/src/
COPY --chown=appuser:appuser alembic/ /app/alembic/
COPY --chown=appuser:appuser alembic.ini pyproject.toml ./
COPY --chown=appuser:appuser scripts/ /app/scripts/

# 从 Stage 1 复制前端构建产物
COPY --from=frontend --chown=appuser:appuser /build/dist /app/src/web/dist

# 复制入口脚本
COPY --chown=appuser:appuser docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

# 创建数据目录
RUN mkdir -p /app/data && chown appuser:appuser /app/data

# 切换到非 root 用户
USER appuser

# 环境变量
ENV PATH="/app/venv/bin:$PATH" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
