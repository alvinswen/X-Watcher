"""X-watcher CLI 入口。

提供 init / validate / serve / export / import-data 子命令。
"""

import click

from src.cli.init_command import init
from src.cli.sync_command import export, import_data
from src.cli.validate_command import validate


@click.group()
@click.version_option(version="0.1.0", prog_name="x-watcher")
def cli() -> None:
    """X-watcher — 面向 Agent 的 X 平台智能信息监控服务。"""
    pass


cli.add_command(init)
cli.add_command(validate)
cli.add_command(export)
cli.add_command(import_data)


@cli.command()
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8000, type=int, help="监听端口")
@click.option("--reload", is_flag=True, help="启用热重载（开发模式）")
def serve(host: str, port: int, reload: bool) -> None:
    """启动 X-watcher API 服务。"""
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    cli()
