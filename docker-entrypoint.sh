#!/bin/bash
set -e

echo "========================================="
echo " X-watcher Container Starting"
echo "========================================="

# 1. SQLite: 调整数据库路径到持久化卷
if [[ "${DATABASE_URL}" == "sqlite:///./news_agent.db" ]] || [[ -z "${DATABASE_URL}" ]]; then
    export DATABASE_URL="sqlite:////app/data/news_agent.db"
    echo "Database: SQLite (/app/data/news_agent.db)"
elif [[ "${DATABASE_URL}" == sqlite* ]]; then
    echo "Database: SQLite (${DATABASE_URL})"
elif [[ "${DATABASE_URL}" == postgresql* ]]; then
    echo "Database: PostgreSQL"

    # 2. 等待 PostgreSQL 就绪（使用已有的 asyncpg 依赖）
    echo "Waiting for PostgreSQL..."
    python -c "
import asyncio, sys, os

async def wait_for_postgres():
    import asyncpg
    url = os.environ['DATABASE_URL']
    for attempt in range(30):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            print('PostgreSQL is ready!')
            return
        except Exception:
            print(f'  Attempt {attempt + 1}/30: waiting...')
            await asyncio.sleep(2)
    print('ERROR: PostgreSQL did not become ready in 60 seconds')
    sys.exit(1)

asyncio.run(wait_for_postgres())
"
fi

# 3. 运行 Alembic 数据库迁移
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

# 4. 可选：种子数据
if [[ "${SEED_ADMIN}" == "true" ]]; then
    echo "Seeding admin user..."
    python scripts/seed_admin.py
fi

if [[ "${SEED_FOLLOWS}" == "true" ]]; then
    echo "Seeding follow list..."
    python scripts/seed_follows.py
fi

echo "========================================="
echo " Starting application..."
echo "========================================="

# 5. 启动应用（exec 替换当前进程，确保信号正确传递）
exec "$@"
