"""pytest 共享 fixtures + sys.path 配置.

让 tests/ 下的测试能 import ecos/ web/ 等顶层包.
"""
import sys
from pathlib import Path

# 项目根目录加入 sys.path (pytest rootdir 行为)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# 共享 fixtures
import pytest

# ─── DB 隔离 (v0.98.5, 防御性自检 [8] 同类模式收口) ──────────────────────────
#
# 根因: get_db() / get_dual_agent_store() / get_lca_store() / belief._get_db()
#   等默认路径
#   硬编码 "web/ecos.db" (生产库), 本地 pytest 直写生产库 → test_* 学生
#   污染 (2026-09-07 清理过一轮, 见 CHANGELOG v0.98.5)。
# 修法: 生产代码统一支持 ECOS_DB_PATH 环境变量; 本 fixture 对**每个测试**
#   设置独立 tmp DB + 重置相关单例缓存, 双保险。
# 例外: 显式传非默认路径的调用不受影响 (如 DualAgentStore(db_path=...))。


@pytest.fixture(autouse=True)
def isolated_ecos_db(tmp_path, monkeypatch):
    """每个测试自动使用独立临时 DB, 防止污染 web/ecos.db 生产库."""
    import os

    # 12.4 (0-C): PluginRuntime + 默认事件总线无条件重置 (在 early-return
    # 之前!) — FastAPI TestClient 的 lifespan 会 ensure_started(), 若不重置,
    # 上一测试启动的 runtime 及其 bus subscriber 跨测试泄漏 (带着指向已删除
    # tmp DB 的 engine/store 引用, 后续 lca/dual_agent 测试走进陈旧 Plugin
    # 路径 → "重启后状态归零"假象)。reset_plugin_runtime 只置空单例不退订
    # bus, 所以 bus 也要 reset (test_event_stub 既有的同款模式, 提为全局)。
    try:
        from web.api.plugin_runtime import reset_plugin_runtime

        reset_plugin_runtime()
    except ImportError:
        pass
    try:
        from cogedu.event import reset_default_bus

        reset_default_bus()
    except ImportError:
        pass
    # dual_agent 开关归一化: 部分 module fixture 直接赋值 True 不复原
    # (历史遗留泄漏, 12.4 新增的 9 字段契约测试将其暴露)。conftest autouse
    # 先于 module 级 fixture 执行, 不影响需要 True 的测试自行设置。
    try:
        import web.api.dual_agent as _da_mod

        _da_mod.DUAL_AGENT_ENABLED = os.environ.get(
            "ECOS_DUAL_AGENT_ENABLED", "0"
        ) == "1"
    except ImportError:
        pass

    # 尊重已有隔离: 部分 module 级 fixture (test_teacher_api 等) 自设
    # ECOS_DB_PATH 指向专用 temp DB — 非生产路径时不覆盖
    current = os.environ.get("ECOS_DB_PATH")
    if current and current != "web/ecos.db":
        yield current
        return

    tmp_db = str(tmp_path / "ecos_test.db")
    monkeypatch.setenv("ECOS_DB_PATH", tmp_db)

    # 重置持久化单例缓存 (上一测试创建的实例指向已删除的 tmp DB)
    import cogedu.persistence.db as db_mod
    import cogedu.persistence.dual_agent_store as store_mod
    import cogedu.persistence.lca_store as lca_store_mod

    monkeypatch.setattr(db_mod, "_db_instance", None)
    monkeypatch.setattr(store_mod, "_store", None)
    monkeypatch.setattr(lca_store_mod, "_store", None)
    # Phase 2 (2-0): 账号持久化单例 (同上, 指向已删除 tmp DB 的缓存要清)
    try:
        from cogedu.persistence.auth_store import reset_auth_store

        reset_auth_store()
    except ImportError:
        pass

    # web 层单例缓存 (belief / lca / dual_agent) — 容错: 模块未必被 import
    try:
        import web.api.belief as belief_mod

        monkeypatch.setattr(belief_mod, "_db", None)
        monkeypatch.setattr(belief_mod, "_web_event_log", None)
        monkeypatch.setattr(belief_mod, "_evidence_engine", None)
        belief_mod._STUDENT_STATES.clear()
    except ImportError:
        pass
    try:
        import web.api.lca as lca_mod

        monkeypatch.setattr(lca_mod, "_store", None)
        monkeypatch.setattr(lca_mod, "_engine", None)
        lca_mod._loaded_students.clear()
    except ImportError:
        pass
    try:
        import web.api.dual_agent as da_mod

        monkeypatch.setattr(da_mod, "_dual_store", None)
    except ImportError:
        pass
    # Phase 1 (1-C): 呈现持久化单例 (同上, 指向已删除 tmp DB 的缓存要清)
    try:
        import web.api.presentation_service as pres_mod

        monkeypatch.setattr(pres_mod, "_store", None)
    except ImportError:
        pass
    # Phase 1 (1-G): cogedu.runtime.api 默认引擎单例 — 呈现引擎 /answer 链路
    # 的 plan()/update_belief() 不带引擎 kwarg 时会填充, 泄漏会破坏
    # test_runtime "Singleton 不被构造" 断言 (test_estimate_creates_initial_state)
    try:
        import cogedu.runtime.api as runtime_api_mod

        monkeypatch.setattr(runtime_api_mod, "_default_belief_engine", None)
        monkeypatch.setattr(runtime_api_mod, "_default_lca_engine", None)
        monkeypatch.setattr(runtime_api_mod, "_default_evaluator", None)
        monkeypatch.setattr(runtime_api_mod, "_default_event_log", None)
    except ImportError:
        pass

    yield tmp_db


@pytest.fixture(scope="session")
def project_root() -> Path:
    """项目根目录路径."""
    return PROJECT_ROOT


# ─── 鉴权 (Phase 2, 2-0-3) ───────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def auth_bypass(request, monkeypatch):
    """存量契约测试的鉴权 bypass — 测试层设施, 不是生产后门.

    背景 (2-0-3): 账号体系落地后全部 /api/* 需登录, 存量 ~1700 用例的
    HTTP 契约测试若逐一补登录, 改动面巨大且与被测契约无关。本 fixture
    autouse patch web.api.auth._resolve_request_user (dependencies 的
    唯一取数点, patch 面约定见该模块 docstring), 让存量测试免登录跑,
    以 admin 身份通过 (角色矩阵对存量测试透明)。

    鉴权语义本身的测试 (登录/401/403/角色矩阵/学生越权) 用
    @pytest.mark.real_auth 退出 bypass, 配合下方 auth_factory 造真实
    账号+会话。鉴权回归由 tests/test_auth_api.py 负责 — 存量契约测试
    不重复覆盖这块。
    """
    if request.node.get_closest_marker("real_auth"):
        yield None
        return
    try:
        import web.api.auth as auth_mod
    except ImportError:
        yield None
        return
    fake_user = {
        "user_id": "u_test_bypass",
        "username": "test_bypass",
        "role": "admin",
        "display_name": None,
        "learning_student_id": None,
        "password_hash": "",
        "created_at": "",
        "disabled_at": None,
    }
    monkeypatch.setattr(auth_mod, "_resolve_request_user", lambda req: fake_user)
    yield fake_user


@pytest.fixture()
def auth_factory():
    """real_auth 测试用: 经服务层直接造账号 + 会话.

    返回工厂 (username, role, learning_student_id, ...) ->
    (headers dict 含 Bearer token, user dict)。
    """
    from web.api import auth as auth_service

    def _make(username="test_user", password="password123", role="student",
              learning_student_id=None, **kwargs):
        user = auth_service.create_user(
            username=username,
            password=password,
            role=role,
            learning_student_id=learning_student_id,
            **kwargs,
        )
        token, _ = auth_service.issue_session(user["user_id"])
        return {"Authorization": f"Bearer {token}"}, user

    return _make


@pytest.fixture(scope="session")
def ecos_dir() -> Path:
    """内核 Python 包路径 (cogedu/, 自 ECOS 复制并改名; fixture 名 ecos_dir 为历史命名保留)."""
    return PROJECT_ROOT / "cogedu"


@pytest.fixture(scope="session")
def web_dir() -> Path:
    """web/ Flask 应用路径."""
    return PROJECT_ROOT / "web"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    """data/ 数据文件路径."""
    return PROJECT_ROOT / "data"


@pytest.fixture(scope="session")
def research_dir() -> Path:
    """research/ 文档路径."""
    return PROJECT_ROOT / "research"


@pytest.fixture(scope="session")
def lbc_history() -> dict:
    """黄金重放数据: lbc001/002/003 response_history.

    v0.98.5 从生产库导出到 tests/fixtures/lbc_response_history.json —
    此前回归测试直接 sqlite3.connect("web/ecos.db") 读生产库, 数据清理
    后改走 fixture 文件 (CI 可复现, 不依赖本地 DB 状态).
    """
    import json

    path = PROJECT_ROOT / "tests" / "fixtures" / "lbc_response_history.json"
    return json.loads(path.read_text(encoding="utf-8"))
