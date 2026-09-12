"""12.4 (0-C): 前端静态页托管 FastAPI 路由 — 自 Flask app.py 迁移.

路由结构 (与 Flask 版一一对应, 注册顺序敏感 — assets 等具体路由必须在
/student/{filename:path} 这类宽路由之前注册, FastAPI 按注册顺序匹配):

  /                              学生端入口 (dist 优先, fallback web/student)
  /student/  /student/assets/*  /student/{path}    学生端 SPA
  /assets/*                      根路径相对资源 (v0.96.1 白屏修复)
  /teacher/  /teacher/assets/*  /teacher/{path}    教师端
  /parent/   /parent/assets/*   /parent/{path}     家长端

行为契约 (前端零改动):
  - React build 产物 (web/frontend/dist/) 优先, 无 build 时 fallback
    legacy 静态页 (web/student|teacher|parent/)
  - HTML 入口一律带 no-cache 头 (W5 修复: 浏览器缓存旧 JS 导致渲染异常;
    dist 资产文件名带 hash, 本身可缓存, 不加 no-cache)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(include_in_schema=False, tags=["static"])

# web/ 目录 (routers/ 的上上级)
WEB_DIR = Path(__file__).resolve().parents[2]
DIST_DIR = WEB_DIR / "frontend" / "dist"

# HTML 入口的 no-cache 头 (W5 修复, 见文件头)
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _serve(path: Path, no_cache: bool = False) -> FileResponse:
    return FileResponse(path, headers=_NO_CACHE_HEADERS if no_cache else None)


def _serve_first(*candidates: Path, no_cache: bool = False):
    """按优先级服务第一个存在的文件; 全不存在 → 404 (不 fallback 到目录)."""
    for path in candidates:
        if path.is_file():
            return _serve(path, no_cache=no_cache)
    return JSONResponse({"error": "not found"}, status_code=404)


# ─── 学生端 ─────────────────────────────────────────────────────────────────


@router.get("/")
def index():
    """学生端入口: dist/student.html 优先, 否则 legacy web/student/index.html."""
    return _serve_first(
        DIST_DIR / "student.html",
        WEB_DIR / "student" / "index.html",
        no_cache=True,
    )


@router.get("/student/")
def student_app():
    """学生端 SPA 入口 (dist 优先, fallback 老静态)."""
    if (DIST_DIR / "student.html").is_file():
        return _serve(DIST_DIR / "student.html", no_cache=True)
    return student_static("index.html")


# ─── 登录态 (2-0-4, Phase 2) ─────────────────────────────────────────────────


@router.get("/login")
def login_page():
    """登录页 (各端共用, 按角色跳对应首页)."""
    return _serve(WEB_DIR / "login.html", no_cache=True)


@router.get("/auth.js")
def auth_js():
    """前端登录态共享脚本 (token 存取 / authFetch / 页面守卫)."""
    return _serve(WEB_DIR / "auth.js")


@router.get("/student/assets/{filename:path}")
def student_assets(filename: str):
    """React build 静态资源 (js/css), fallback legacy web/student/."""
    return _serve_first(
        DIST_DIR / "assets" / filename,
        WEB_DIR / "student" / filename,
    )


@router.get("/assets/{filename:path}")
def root_assets(filename: str):
    """v0.96.1: 根入口的相对路径资源 ./assets/... (缺这条会白屏)."""
    return _serve_first(
        DIST_DIR / "assets" / filename,
        WEB_DIR / "student" / filename,
    )


@router.get("/student/{filename:path}")
def student_static(filename: str):
    """学生端静态文件 (dist 优先, fallback web/student/)."""
    return _serve_first(
        DIST_DIR / filename,
        WEB_DIR / "student" / filename,
    )


# ─── 教师端 ─────────────────────────────────────────────────────────────────


@router.get("/teacher/")
def teacher_app():
    """教师端 SPA 入口 (dist/index.html 优先, fallback 老 teacher/index.html)."""
    if (DIST_DIR / "index.html").is_file():
        return _serve(DIST_DIR / "index.html", no_cache=True)
    return teacher_static("index.html")


@router.get("/teacher/assets/{filename:path}")
def teacher_assets(filename: str):
    """教师端 React build 资源, fallback legacy web/teacher/."""
    return _serve_first(
        DIST_DIR / "assets" / filename,
        WEB_DIR / "teacher" / filename,
    )


@router.get("/teacher/{filename:path}")
def teacher_static(filename: str):
    """教师端静态文件 (dist 优先, fallback web/teacher/)."""
    return _serve_first(
        DIST_DIR / filename,
        WEB_DIR / "teacher" / filename,
    )


# ─── 家长端 ─────────────────────────────────────────────────────────────────


@router.get("/parent/")
def parent_app():
    """家长端 SPA 入口 (dist/parent.html 优先, fallback web/parent/index.html)."""
    if (DIST_DIR / "parent.html").is_file():
        return _serve(DIST_DIR / "parent.html", no_cache=True)
    return parent_static("index.html")


@router.get("/parent/assets/{filename:path}")
def parent_assets(filename: str):
    """家长端 React build 资源, fallback legacy web/parent/."""
    return _serve_first(
        DIST_DIR / "assets" / filename,
        WEB_DIR / "parent" / filename,
    )


@router.get("/parent/{filename:path}")
def parent_static(filename: str):
    """家长端静态文件 (dist 优先, fallback web/parent/)."""
    return _serve_first(
        DIST_DIR / filename,
        WEB_DIR / "parent" / filename,
    )
