"""3-C: 播放引擎 JS 时序测试的 pytest 包装 (node --test).

真身是 ``tests/js/playback.test.cjs`` (node:test, 零依赖) — 播放引擎的
时序正确性 (乱序/重叠/令牌失效/暂停恢复/语音三级路径) 必须自动化锁定,
grep 契约测试只能锁"接线存在", 锁不了行为。

无 node 环境 skip (对齐 PG 集成测试的 skip 惯例); pre-push 的 pytest
是唯一质量门禁, 本包装使其覆盖到 JS 侧。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS_JS_DIR = Path(__file__).resolve().parent / "js"


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="node 不可用 (播放引擎 JS 时序测试)")
def test_playback_engine_js_suite() -> None:
    test_files = sorted(TESTS_JS_DIR.glob("*.test.cjs"))
    assert test_files, "tests/js/ 下没有 .test.cjs 测试文件"
    proc = subprocess.run(
        ["node", "--test", *[str(p) for p in test_files]],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"播放引擎 JS 测试失败:\n{proc.stdout}\n{proc.stderr}")
