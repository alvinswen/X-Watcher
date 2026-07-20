"""REST 与 MCP host 默认收敛回归（CHG-041）。"""

import inspect

from click.testing import CliRunner

from src.cli.main import cli
from src.mcp.server import create_mcp_server, run_mcp_server


def _host_default(command_name: str) -> str:
    command = cli.commands[command_name]
    return next(param.default for param in command.params if param.name == "host")


def test_host_defaults_are_localhost():
    """CLI 两入口与 MCP 两签名的默认值统一为 127.0.0.1。"""
    assert _host_default("serve") == "127.0.0.1"
    assert _host_default("mcp") == "127.0.0.1"
    assert inspect.signature(create_mcp_server).parameters["host"].default == "127.0.0.1"
    assert inspect.signature(run_mcp_server).parameters["host"].default == "127.0.0.1"


def test_serve_default_explicit_override_and_restore(monkeypatch):
    """A→B→A：默认本机、显式 LAN、再回默认，传播链无残留。"""
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))
    runner = CliRunner()

    first_default = runner.invoke(cli, ["serve"])
    explicit_lan = runner.invoke(cli, ["serve", "--host", "0.0.0.0"])
    second_default = runner.invoke(cli, ["serve"])

    assert first_default.exit_code == 0
    assert explicit_lan.exit_code == 0
    assert second_default.exit_code == 0
    assert [call["host"] for call in calls] == [
        "127.0.0.1",
        "0.0.0.0",
        "127.0.0.1",
    ]


def test_mcp_default_explicit_override_and_restore(monkeypatch):
    """MCP SSE 同样支持默认→显式放开→恢复默认。"""
    from src.mcp import server

    calls = []

    def fake_run_mcp_server(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(server, "run_mcp_server", fake_run_mcp_server)
    runner = CliRunner()

    first_default = runner.invoke(cli, ["mcp", "--transport", "sse"])
    explicit_lan = runner.invoke(
        cli,
        ["mcp", "--transport", "sse", "--host", "0.0.0.0"],
    )
    second_default = runner.invoke(cli, ["mcp", "--transport", "sse"])

    assert first_default.exit_code == 0
    assert explicit_lan.exit_code == 0
    assert second_default.exit_code == 0
    assert [call["host"] for call in calls] == [
        "127.0.0.1",
        "0.0.0.0",
        "127.0.0.1",
    ]


def test_development_main_uses_localhost(monkeypatch):
    """热重载入口同样只绑定本机。"""
    from src import main

    calls = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: calls.append(kwargs))

    main.main()

    assert calls[0]["host"] == "127.0.0.1"


def test_host_help_explains_local_default_and_lan_override():
    runner = CliRunner()

    serve_help = runner.invoke(cli, ["serve", "--help"])
    mcp_help = runner.invoke(cli, ["mcp", "--help"])

    assert serve_help.exit_code == 0
    assert mcp_help.exit_code == 0
    assert "默认 127.0.0.1" in serve_help.output
    assert "LAN 访问请显式指定" in serve_help.output
    assert "默认 127.0.0.1" in mcp_help.output
    assert "LAN 访问请显式指定" in mcp_help.output
