"""x-watcher validate 命令实现。

逐一检查 Twitter API、数据库的连通性。
"""

import asyncio
from typing import Any

import click

from src.shared.connectivity_check import check_database, check_twitter_api


@click.command()
def validate() -> None:
    """验证 X-watcher 配置和服务连通性。"""
    click.echo("X-watcher 配置验证")
    click.echo("=" * 40)

    results: list[dict[str, Any]] = []

    # 1. 数据库检查
    click.echo("\n[数据库]")
    db_result = {"name": "database", **check_database()}
    results.append(db_result)
    _print_result(db_result)

    # 2. Twitter API 检查
    click.echo("\n[Twitter API]")
    twitter_result = {
        "name": "twitter_api",
        **asyncio.run(check_twitter_api()),
    }
    results.append(twitter_result)
    _print_result(twitter_result)

    # 汇总
    click.echo("\n" + "=" * 40)
    healthy = sum(1 for r in results if r["status"] == "healthy")
    total = len(results)
    click.echo(f"结果: {healthy}/{total} 项检查通过")

    if healthy < total:
        click.echo("提示: 部分检查未通过，请检查 .env 配置")


def _print_result(result: dict[str, Any]) -> None:
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
