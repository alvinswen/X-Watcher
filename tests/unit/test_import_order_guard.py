"""CHG-DSH-004 · 导入顺序守卫的回归测试。

契约见 `01-需求细化.md` §4.3 与 §五 断言 3–5：

- 对照：未抢先导入时，根级测试入口配置正常执行，目标测试文件 13 passed；
- 抢先：先在独立子进程里 ``import src.config``，再启动同一目标，守卫必须在
  收集前中止：退出码 4、输出含固定标记「导入顺序守卫失败」与三个固定子串、
  0 个测试被执行；
- 负例：只 ``import src``（未导入 ``src.config``）不触发守卫。

本文件**不**直接 ``import src.config`` 来模拟抢先——根级 conftest 本来就会导入它，
在测试进程内造这个状态只能证明守卫函数，证明不了真实入口（`01` §4.7 给 A6 第 4 条）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = "tests/unit/test_config.py"
GUARD_MARKER = "导入顺序守卫失败"
GUARD_SUBSTRINGS = ("已被导入", "不可信", "重跑")
TEST_COUNT = re.compile(r"\d+\s+(?:passed|failed|error)")
TIMEOUT_SECONDS = 300

# 子进程脚本：先 import src.config（模拟更早的插件/配置抢先导入），再启动 pytest。
PREEMPT_SCRIPT = """
import sys

import src.config  # noqa: F401  # 模拟更早的插件/配置抢先导入
import pytest

sys.exit(pytest.main(["-q", "tests/unit/test_config.py", "-p", "no:cacheprovider"]))
"""

# 负例脚本：只导入 src 命名空间，不导入 src.config。
NEGATIVE_SCRIPT = """
import sys

import src  # noqa: F401  # 只导入命名空间，不导入 src.config
import pytest

sys.exit(pytest.main(["-q", "tests/unit/test_config.py", "-p", "no:cacheprovider"]))
"""


def _run_pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )


def _run_script(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )


def test_control_run_executes_target_tests() -> None:
    result = _run_pytest("-q", TARGET)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "13 passed" in output, output
    assert GUARD_MARKER not in output, output


def test_preempted_import_fails_fast() -> None:
    result = _run_script(PREEMPT_SCRIPT)
    output = result.stdout + result.stderr
    assert result.returncode == 4, output
    assert GUARD_MARKER in output, output
    for text in GUARD_SUBSTRINGS:
        assert text in output, output
    assert not TEST_COUNT.search(output), output


def test_unrelated_src_import_does_not_trigger() -> None:
    result = _run_script(NEGATIVE_SCRIPT)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "13 passed" in output, output
    assert GUARD_MARKER not in output, output
