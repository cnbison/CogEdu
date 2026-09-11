"""CogEdu FastAPI 路由层 (12.4 / 0-C 框架迁移).

过渡期布局 (2026-09-11, 12.4 进行中):
  - web/api/fastapi_app.py  — FastAPI 应用装配 (新, 与 Flask app.py 并存)
  - web/api/routers/        — FastAPI routers (按域拆分, 迁移顺序见
                              docs/cogedu-整合技术方案.md 12.4)
  - web/api/app.py 等 Flask 模块 — 保持不动, 全部路由迁移完成后统一删除

迁移原则:
  - 路由层薄: 业务逻辑复用 web/api/ 下的框架无关模块
    (belief.py / teacher.py helpers / lca.py / qmatrix.py ...), 不复制逻辑
  - 请求/响应结构用 Pydantic 模型定义 (替代 Flask 手写 JSON 解析)
  - 响应 JSON 形状与 Flask 版保持一致 (前端零改动, 测试断言可平移)
  - 错误处理延续既有防御风格: 显式 warning 留痕, 不 silent pass
"""
