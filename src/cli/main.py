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
@click.option(
    "--host",
    default="127.0.0.1",
    help="监听地址（默认 127.0.0.1，仅本机；LAN 访问请显式指定对外监听地址）",
)
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


@cli.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="传输模式：stdio（本地 AI 助手）或 sse（内网远程访问）",
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="SSE 模式监听地址（默认 127.0.0.1；LAN 访问请显式指定对外监听地址）",
)
@click.option("--port", default=8001, type=int, help="SSE 模式监听端口")
@click.option("--api-key", default=None, help="SSE 模式 API Key（用于权限验证）")
def mcp(transport: str, host: str, port: int, api_key: str | None) -> None:
    """启动 MCP Server，供 AI 助手集成使用。

    stdio 模式（默认）：通过标准输入输出通信，适用于 Claude Code / Claude Desktop 等本地 AI 助手。
    sse 模式：通过 SSE 协议通信，适用于内网其他机器的 Agent 远程访问。
    """
    from src.mcp.server import run_mcp_server

    run_mcp_server(
        transport=transport,
        host=host,
        port=port,
        api_key=api_key,
    )


if __name__ == "__main__":
    cli()
