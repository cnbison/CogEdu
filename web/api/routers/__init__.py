"""CogEdu FastAPI 路由层 (12.4 / 0-C 框架迁移完成).

布局 (2026-09-12 翻转后, Flask 已删除):
  - web/api/app.py      — FastAPI 应用装配 + 基础端点 + __main__ 启动
  - web/api/routers/    — 按域拆分的路由:
      student.py        答题主链路 (state/question/judge/answer/report/...)
      teacher.py        教师端 (7 只读端点)
      parent.py         家长端 (2 只读端点, 防幽灵学生)
      events.py         前端事件 (hint/idle/goal_change/reflection)
      dual_agent.py     双 Agent 互校调试
      stream.py         SSE 流式 (事件总线实时推送, Phase 1 复用)
      static_pages.py   前端静态托管 (dist 优先 fallback legacy)
  - web/api/{belief,lca,qmatrix,interpretation,teacher,parent,event_stub,
    dual_agent,plugin_runtime}.py — 框架无关业务逻辑 (helpers, 无路由)
  - web/api/llm.py / judge.py — LLM 客户端单例 / judge 三件套

迁移原则 (已全程执行):
  - 路由层薄: 业务逻辑复用框架无关模块, 不复制逻辑
  - 请求/响应结构用 Pydantic 模型定义 (替代 Flask 手写 JSON 解析)
  - 响应 JSON 形状与 Flask 版一致 (前端零改动, HTTP 契约测试锁定)
  - 错误处理延续既有防御风格: 显式 warning 留痕, 不 silent pass
"""
