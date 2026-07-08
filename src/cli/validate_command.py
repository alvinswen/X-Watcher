"""x-watcher validate 命令实现。

逐一检查 Twitter API、数据库的连通性。
"""

import asyncio
import time

import click


@click.command()
def validate() -> None:
    """验证 X-watcher 配置和服务连通性。"""
    click.echo("X-watcher 配置验证")
    click.echo("=" * 40)

    results: list[dict] = []

    # 1. 数据库检查
    click.echo("\n[数据库]")
    db_result = _check_database()
    results.append(db_result)
    _print_result(db_result)

    # 2. Twitter API 检查
    click.echo("\n[Twitter API]")
    twitter_result = asyncio.run(_check_twitter_api())
    results.append(twitter_result)
    _print_result(twitter_result)

    # 汇总
    click.echo("\n" + "=" * 40)
    healthy = sum(1 for r in results if r["status"] == "healthy")
    total = len(results)
    click.echo(f"结果: {healthy}/{total} 项检查通过")

    if healthy < total:
        click.echo("提示: 部分检查未通过，请检查 .env 配置")


def _check_database() -> dict:
    """检查数据库连接。"""
    from src.data_layer.provider import data_root

    # file 模式(pg 下线守卫):不连 pg,改探数据目录存在性
    root = data_root()
    if root.exists():
        return {"name": "database", "status": "healthy", "mode": "file", "data_root": str(root)}
    return {"name": "database", "status": "unhealthy", "error": f"data_root 不存在: {root}"}


async def _check_twitter_api() -> dict:
    """检查 Twitter API 连通性。"""
    try:
        import os

        import httpx

        api_key = os.getenv("TWITTER_API_KEY", "")
        base_url = os.getenv("TWITTER_BASE_URL", "https://api.twitterapi.io/twitter")

        if not api_key:
            return {"name": "twitter_api", "status": "unhealthy", "error": "TWITTER_API_KEY 未配置"}

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url}/user/info",
                params={"userName": "twitter"},
                headers={"X-API-Key": api_key},
            )
        latency_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            return {"name": "twitter_api", "status": "healthy", "latency_ms": latency_ms}
        else:
            return {
                "name": "twitter_api",
                "status": "unhealthy",
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as e:
        return {"name": "twitter_api", "status": "unhealthy", "error": str(e)[:200]}


def _print_result(result: dict) -> None:
    """打印检查结果。"""
    name = result["name"]
    status = result["status"]
    icon = "OK" if status == "healthy" else "FAIL"

    parts = [f"  [{icon}] {name}"]

    if "model" in result:
        parts.append(f"model={result['model']}")
    if "latency_ms" in result:
        parts.append(f"latency={result['latency_ms']}ms")
    if "error" in result:
        parts.append(f"error={result['error']}")

    click.echo("  ".join(parts))
