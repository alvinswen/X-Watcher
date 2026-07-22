"""CHG-043 · 复用入口必须绑定既有契约，禁止另建同形影子契约（P2-8 射程边界机器守卫）。

背景：mypy 只拦「把契约写窄」，**不拦「不复用」**——施工方若另抄一份等宽的重复契约，
门禁一声不吭放行，却造出与既有契约并存、日后各自漂移的影子契约。本用例补上这一半。
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER = _ROOT / "src" / "data_layer" / "provider.py"
_REPOS = _ROOT / "src" / "data_layer" / "repositories.py"

# 工厂名 → (必须逐字使用的既有契约名, 该契约的唯一权威模块)
EXPECTED: dict[str, tuple[str, str]] = {
    "get_follows_repo": ("FollowStore", "src.preference.infrastructure.follow_store"),
    "get_profile_repo": ("ProfileStore", "src.preference.infrastructure.profile_store"),
    "get_user_repo": ("UserStore", "src.user.infrastructure.user_store"),
    "get_subject_repo": ("SubjectRepoProtocol", "src.subjects.protocol"),
}


def _provider_tree() -> ast.Module:
    return ast.parse(_PROVIDER.read_text(encoding="utf-8"))


def test_reused_entries_annotate_existing_contract_verbatim() -> None:
    """① 四个复用入口的返回标注必须逐字等于既有契约名。"""
    tree = _provider_tree()
    ann = {
        n.name: ast.unparse(n.returns)
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.returns is not None
    }
    for fn, (contract, _mod) in EXPECTED.items():
        assert fn in ann, f"{fn} 缺返回标注"
        assert ann[fn] == contract, f"{fn} 返回标注为 {ann[fn]!r}，必须逐字为 {contract!r}"


def test_reused_contracts_imported_from_canonical_module() -> None:
    """② 该契约名必须 import 自既有权威模块，禁本地另建。"""
    tree = _provider_tree()
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module
    for fn, (contract, mod) in EXPECTED.items():
        assert imported.get(contract) == mod, (
            f"{fn} 用的 {contract} 必须 import 自 {mod}，实为 {imported.get(contract)!r}"
        )


def test_no_shadow_contract_redefined_in_repositories() -> None:
    """③ repositories.py 不得定义与既有契约同名的影子契约。"""
    defined = {
        n.name
        for n in ast.walk(ast.parse(_REPOS.read_text(encoding="utf-8")))
        if isinstance(n, ast.ClassDef)
    }
    for contract, _mod in EXPECTED.values():
        assert contract not in defined, (
            f"repositories.py 重定义了既有契约 {contract} —— 影子契约，禁止"
        )


def test_new_contracts_follow_house_naming_rule() -> None:
    """④ 房规：新写契约名 = 实现类名去掉 File 前缀（防第三套命名皮肤）。"""
    defined = {
        n.name
        for n in ast.walk(ast.parse(_REPOS.read_text(encoding="utf-8")))
        if isinstance(n, ast.ClassDef)
    }
    assert defined, "repositories.py 未定义任何契约"
    for name in defined:
        assert name.endswith("Store"), f"契约 {name} 不符房规（须 *Store，= 实现类去 File 前缀）"
        assert not name.startswith("File"), f"契约 {name} 不得带 File 前缀（那是实现类命名）"
