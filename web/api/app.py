"""CogEdu FastAPI 应用装配 (12.4 / 0-C: Flask → FastAPI 迁移完成版).

2026-09-12 翻转: 原 Flask app.py 删除, 本文件 (原 fastapi_app.py) 成为
唯一 Web 入口。迁移过程与安全网见 docs/cogedu-整合技术方案.md 12.4 +
CHANGELOG (每个域一个 commit, HTTP 契约测试全程锁定)。

布局:
  web/api/app.py          — 本文件, 应用装配 + 基础端点
  web/api/routers/        — 按域拆分的 FastAPI routers
                            (student/teacher/parent/events/dual_agent/
                             stream/static_pages)
  web/api/belief.py 等    — 框架无关业务逻辑 (自 ECOS 平移, 未重写)
  web/api/llm.py          — LLM 客户端单例 (get_llm)
  web/api/judge.py        — LLM judge 三件套 (retry/prompt/parse)

启动:
  python -m web.api.app          (等价 python web/api/app.py, 端口 5173)
  uvicorn web.api.app:app        (gunicorn/uvicorn 部署形态)

激活口径 (v0.99.3 F-14b): lifespan 启动时 ensure_started() 激活
PluginRuntime — 不依赖启动方式, /api/answer 等走 Plugin 事件总线路径。
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

    对齐 Flask 时代 __main__ 的 ensure_started() 口径 (F-14b) — 不依赖
    启动方式 (uvicorn / gunicorn / TestClient lifespan), 记账口径统一。
    测试里不想要 Plugin 路径时, 用裸 TestClient(app) 不进 with 块即可
    (不触发 lifespan → 走 legacy fallback)。
    """
    try:
        from web.api.plugin_runtime import ensure_started

        if ensure_started():
            _log.info("lifespan: PluginRuntime 已激活 (Plugin path)")
        else:
            _log.warning("lifespan: PluginRuntime 激活失败, 走 legacy fallback")
    except Exception:
        # 激活失败不阻断应用启动, 但必须留痕 — 防御性自检 [1]: 不 silent pass
        _log.warning("lifespan: ensure_started 异常", exc_info=True)
    yield


app = FastAPI(
    title="CogEdu API",
    description="K12 数理化管理系统后端",
    version="0.1.0",
    lifespan=lifespan,
)

# ─── 路由注册 ────────────────────────────────────────────────────────────────
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
# 核心路由 (含 /api/answer 答题主链路)
app.include_router(student.router)
# 静态页放最后: /student/{path} 等宽路由兜底, 不能抢先匹配 API 路由
app.include_router(static_pages.router)


# ─── 基础端点 ────────────────────────────────────────────────────────────────


@app.get("/api/version")
def api_get_version():
    """返回版本号 (dashboard 角标用, 报问题时对齐代码版本).

    注: Flask 版此端点因 `import ecos` 重命名漏改恒 500, 12.4 迁移时修复。
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


if __name__ == "__main__":
    # Production activation — 注册 PluginRuntime subscriber (与 lifespan
    # 双保险: uvicorn.run 走 lifespan, 这里显式调保证任何嵌入用法一致)
    from web.api.plugin_runtime import ensure_started

    ensure_started()

    import uvicorn

    # 端口 5173 沿用 Flask 时代端口 (前端 API base 不变)
    uvicorn.run(app, host="0.0.0.0", port=5173)
