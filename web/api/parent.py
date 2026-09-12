"""v0.98.0 (a-b): 家长端 API — 只读 roster + 单聚合 overview (Parent Dashboard 数据源).

Parent Dashboard 数据源 (全部只读, 不 mutate Kernel state, 防御性自检 [8] 0 mutation):
  - students 表: roster + five_d 摘要 (DB 直读, 不 init BeliefEngine)
  - ParentEngagementPlugin: engagement 状态 + 规则建议 (v0.98.0 (a-a) UI 可消费复活)
  - Runtime.diagnose_pomdp + diagnose_pomdp_evolution: POMDP 诊断 + 演化序列
    (lazy load LCA state, 缓存 miss 时按需诊断 → ingest 双喂入)
  - db.load_intervention_history: 干预历史 (接线审计 B 类 dead code → 本版本接活)

设计决策:
  - **严禁 _get_or_create_student** (v0.96.9 幽灵学生教训): 家长端只读,
    学生不存在直接 404, 不产生任何 DB 行
  - 单聚合端点 /overview: 家长端一次请求拿全部四卡数据 (Engagement / Advice /
    FiveD / Intervention), 避免多次往返
  - 不放校准视图 / misconceptions (Bisen 拍板 2026-09-06: 校准曲线是教师专业视图)
  - 复用 web.api.teacher 的 DB 直读 helpers (单一实现, 不复制解析逻辑)

路由: 12.4 (0-C) 起由 web/api/routers/parent.py 提供 (FastAPI),
  本文件只保留框架无关 helpers, Flask Blueprint 路由层已随迁移删除。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

# POMDP 状态名 (跟 ParentEngagementPlugin / teacher.py 一致)
_POMDP_STATE_NAMES = ("Engaged", "Frustrated", "Bored", "Confused")


def _get_parent_engagement_plugin() -> Any:
    """从 PluginRegistry 拿 ParentEngagementPlugin 实例 (跟 teacher.py 同模式).

    Returns:
        plugin 实例或 None (registry 未注册 / 不是该 plugin).
    """
    try:
        from cogedu.plugins.registry import get_default_registry
        return get_default_registry().get("parent_engagement")
    except Exception:
        _log.warning("parent: 拿 ParentEngagementPlugin 失败", exc_info=True)
        return None


def _get_engagement_report(student_id: str) -> Optional[Dict[str, Any]]:
    """获取学生 engagement 报告 (插件缓存 → 按需诊断 + ingest 双喂入).

    优先级:
      1. ParentEngagementPlugin.report_for(student_id) (bus 事件已缓存)
      2. 缓存 miss → Runtime.diagnose_pomdp + diagnose_pomdp_evolution
         按需派生 → ingest_diagnostic + ingest_evolution 喂 plugin

    Returns:
        report dict (current_state / recent_states / advice / cold_start) 或 None
        (非 POMDP policy / 学生无 LCA 状态 / 派生失败).
    """
    plugin = _get_parent_engagement_plugin()
    if plugin is not None:
        cached = plugin.report_for(student_id)
        if cached is not None:
            return cached

    # 缓存 miss: 按需诊断 (lazy load LCA state, 跟 teacher.py _get_progress_report 一致)
    try:
        from web.api.lca import _get_or_create_lca_state, get_lca_engine
        _get_or_create_lca_state(student_id)
        lca_engine = get_lca_engine()

        from cogedu.runtime.api import diagnose_pomdp, diagnose_pomdp_evolution
        diagnostic = diagnose_pomdp(student_id=student_id, lca_engine=lca_engine)
        if diagnostic is None:
            return None

        report: Optional[Dict[str, Any]] = None
        if plugin is not None:
            report = plugin.ingest_diagnostic(student_id, diagnostic)

        # evolution 序列 (diagnostic 不含 evolution, 经第 9 Runtime API 单独拿)
        evolution = diagnose_pomdp_evolution(student_id=student_id, lca_engine=lca_engine)
        if plugin is not None and evolution:
            report = plugin.ingest_evolution(student_id, evolution) or report

        return report
    except Exception:
        _log.warning(
            "parent: 按需诊断失败 (sid=%s), report=None",
            student_id, exc_info=True,
        )
        return None
