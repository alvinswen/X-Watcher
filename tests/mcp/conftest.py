"""tests/mcp 公共 fixture。"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_mcp_transport():
    """隔离 src/mcp/auth.py 的模块级全局 _transport(stdio/sse 传输模式)。

    根因:`src/mcp/auth.py` 把 `_transport` 作模块全局,`is_admin()` 仅在 `_transport=="stdio"`
    时返 True。部分 TestMCPAuth 测试 `configure_transport("sse")` 后**不还原**(test_sse_no_token_not_admin
    / test_sse_admin_token_in_context / test_require_admin_fail),泄漏的 `_transport="sse"` 在某些
    跨目录收集序下使后续 admin-gated MCP 集成测试(manage_follows / get_follow_accounts_info)
    的 `is_admin()` 误判,报"需要管理员权限"。

    本 autouse 在每个 tests/mcp 测试后把 `_transport` 还原到测试前的值(默认 "stdio"),使套件
    顺序无关。镜像 test_admin_tools_require_permission 既有的 save/restore 范式,推广到全 tests/mcp。
    """
    import src.mcp.auth as auth

    original = auth._transport
    yield
    auth._transport = original
