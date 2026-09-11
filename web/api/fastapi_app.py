"""CogEdu FastAPI 应用装配 (12.4 / 0-C: Flask → FastAPI 迁移).

过渡期说明 (2026-09-11):
  这是**新增**的 FastAPI 应用, 与 web/api/app.py (Flask) 并存。
  迁移顺序 (方案文档 12.4, 低风险 → 高风险):
    plugin_runtime (无路由, 接入验证) → teacher/parent → dual_agent
    → app.py 核心路由 → belief.py (答题主链路, 最复杂, 放最后)
  每个域迁移后在 tests/ 里把对应测试切到本应用, Flask 版保持不动
  直到全部迁移完成 (12.4-6) 统一删除。

  迁移完成后本文件更名为 web/api/app.py (Flask 版删除)。

行为对齐约定:
  - lifespan 启动时 ensure_started() 激活 PluginRuntime — 对齐 Flask 版
    `python web/api/app.py` 的 __main__ 激活路径 (v0.99.3 F-14b 收敛后的口径)
  - /api/version 返回 cogedu.__version__ (顺带修复 Flask 版遗留 bug:
    app.py:85 仍是 `import ecos`, CogEdu 重命名后该端点一直 500)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时激活 PluginRuntime (事件总线 subscriber 注册).

    对齐 Flask 版 __main__ 的 ensure_started() — 不依赖启动方式
    (uvicorn / gunicorn / TestClient lifespan), 记账口径统一 (F-14b)。
    测试里不想要 Plugin 路径时, 用裸 TestClient(app) 不进 with 块即可
    (不触发 lifespan → 走 legacy fallback, 同 Flask test_client 行为)。
    """
    try:
        from web.api.plugin_runtime import ensure_started

        if ensure_started():
            _log.info("FastAPI lifespan: PluginRuntime 已激活 (Plugin path)")
        else:
            _log.warning("FastAPI lifespan: PluginRuntime 激活失败, 走 legacy fallback")
    except Exception:
        # 激活失败不阻断应用启动 (与 Flask lazy ensure 兜底同思路),
        # 但必须留痕 — 防御性自检 [1]: 不 silent pass
        _log.warning("FastAPI lifespan: ensure_started 异常", exc_info=True)
    yield


app = FastAPI(
    title="CogEdu API",
    description="K12 数理化管理系统后端 (Phase 0-C: Flask → FastAPI 迁移过渡期)",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── 路由注册 (迁移顺序见文件头) ────────────────────────────────────────────
from web.api.routers import (  # noqa: E402
    dual_agent,
    events,
    parent,
    static_pages,
    student,
    stream,
    teacher,
)

app.include_router(stream.router)
app.include_router(teacher.router)
app.include_router(parent.router)
app.include_router(events.router)
app.include_router(dual_agent.router)
# 12.4-5: 核心路由 + 静态托管 (含 /api/answer 答题主链路, 最复杂, 最后迁)
app.include_router(student.router)
# 静态页放最后: /student/{path} 等宽路由兜底, 不能抢先匹配 API 路由
app.include_router(static_pages.router)


# ─── 基础端点 (自 Flask app.py 平移, 修复 import ecos 遗留 bug) ─────────────


@app.get("/api/version")
def api_get_version():
    """返回版本号 (dashboard 角标用, 报问题时对齐代码版本).

    Flask 版遗留 bug 修复: 原 app.py:85 `import ecos` 在包名重命名后
    恒 ImportError → 一直返回 500 "unknown"。CogEdu 包名是 cogedu。
    """
    try:
        import cogedu

        return {"version": cogedu.__version__}
    except Exception as e:
        return JSONResponse({"error": str(e), "version": "unknown"}, status_code=500)


@app.get("/api/students/recent")
def api_get_recent_students():
    """最近活跃学生列表 (登录页快捷选择, 按 last_active_at 倒序前 N)."""
    try:
        from cogedu.persistence.db import Database

        # 共享同一个 DB (v0.98.5: ECOS_DB_PATH 可覆盖, 与 belief.py 一致)
        db = Database(os.environ.get("ECOS_DB_PATH", "web/ecos.db"))
        sids = db.load_student_ids(limit=5)  # 只读, 不 init_schema
        return {"students": sids}
    except Exception as e:
        return JSONResponse({"error": str(e), "students": []}, status_code=500)
