# Changelog

本文件记录 **CogEdu 自身**的版本演进。内核代码复制自 ECOS（v0.99.4，commit `9cdacab`，2026-09-11），ECOS 的历史版本记录不在本文件范围内——如需追溯内核的历史设计决策，见 `discussions/` 收录的设计文档与 ECOS 仓库。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

### 2026-09-12 — Phase 0 / 12.4 Flask → FastAPI（完成，Flask 删除）

**迁移策略**：过渡期 FastAPI 与 Flask 并存（`web/api/fastapi_app.py` + `web/api/routers/`），按方案文档 12.4 建议顺序分 4 个 commit 递进（每步全量测试绿），最后一步翻转：`fastapi_app.py` 更名 `app.py` 替换 Flask 版，剥离 teacher/parent/event_stub 的 Blueprint 路由层（helpers 保留），pyproject 移除 flask 依赖。

**新布局**：`web/api/app.py`（装配 + lifespan 激活 PluginRuntime + `__main__` uvicorn 启动）+ `web/api/routers/`（student/teacher/parent/events/dual_agent/stream/static_pages 7 域）+ 框架无关业务模块（belief/lca/qmatrix/interpretation/dual_agent/plugin_runtime 未重写）+ 新抽出的 `web/api/llm.py`（get_llm 单例）与 `web/api/judge.py`（judge 三件套，解除业务层对装配模块的反向依赖）。

**关键决策**：
- `/api/answer` 9 字段契约用 `AnswerResponse`（response_model + exclude_none）框架层锁定
- `score`/`self_confidence`/`response_time` 保留"非数字诚实降级 + warning 留痕"语义（Any 字段 + 手工解析，Pydantic 422 会丢整份学生答案）
- SSE 能力打通：`GET /api/events/stream` 订阅事件总线实时推送（Phase 1 呈现引擎流式生成复用此模式）
- 响应 JSON 形状与 Flask 版逐字段一致，前端零改动

**顺带修复**：
- Flask 版 `/api/version` 与 `/api/report` 的 `import ecos` 重命名漏改（两端点此前恒 500）
- 硬边界违规 ×2：test_event_stub / test_judge_event 硬编码参考项目绝对路径 `/Users/loubicheng/project/ecos/...`，改为项目内相对路径
- conftest 隔离加固：PluginRuntime + 默认事件总线无条件重置、`DUAL_AGENT_ENABLED` 每测试归一化（修复 TestClient lifespan 引入的跨测试泄漏，曾导致 lca "重启后归零"假象）

**验证**：全量 **1640 用例通过**（1627 基线 + 13 新增）；uvicorn 真实启动冒烟通过；dual_agent 开关两条路径 HTTP 级测试锁定。

### 2026-09-11 — Phase 0 / 12.3 补齐状态入口的具体缺口（完成）

**三处直连调用评估（结论：均维持直接调用，不改代码）**
- `engine.l2.register_item`：改的是题目参数缓存（Q 矩阵内容装载，全学生共享），不触碰 `BeliefState`，属内容/配置装载。已在方案文档 12.3 留迁移纪律注记（0-C 迁 FastAPI 时两处调用不能漏，v0.47.4 事故依据）
- `_get_db().save_student_state`：纯持久化 I/O，已有 `persisted=false` + warning 防线和 HTTP 契约测试第 ④ 项锁定
- `reconcile_for_student`：写的 `misconception_evidence` 计数今天无任何认知内核消费者（仅教师展示视图，v0.97.2 拍板"不挂 BeliefState"）。已在方案文档 12.3 留 **A2 闭环 tripwire**：将来 evidence 计数参与信念更新时必须改走 Runtime
- 同时确认 `submit_answer` 核心路径事件总线路由（`_update_via_plugin_or_legacy` → bus → `PluginRuntime` → `Runtime.update_belief`）无需改动，作为 FastAPI 迁移的参考模式

**长期防线（12.3 第 4 项）**
- 新建 `githooks/pre-commit`（零 mutation AST 扫描，~1s）+ `githooks/pre-push`（同一扫描 + pytest 全量 ~25s），沿用 ECOS `core.hooksPath` 模式，hook 文件入仓 tracked
- `scripts/install-hooks.sh` 文案自 ECOS 版更新为 CogEdu 实况（原"5 项静态检查"描述与实际 hook 不符）
- 两 hook 已实测通过（扫描 54 文件 + 1627 用例全绿）；README 增加克隆后启用说明
- 注：ECOS 的 `check_defensive.sh` 暂不接入（内部硬编码扫描 `ecos/` 目录，需先适配 CogEdu 包名），留待后续按需处理

### 2026-09-11 — Phase 0 / 12.2 建立安全网（完成）

**内核复制（基线建立）**
- 从 ECOS v0.99.4（commit `9cdacab`）复制内核：`ecos/` → `cogedu/`（121 个 Python 文件），连同 `web/api/`（Flask，过渡期，0-C 迁 FastAPI 时重写）、`tests/`、`scripts/`、`examples/`、`data/`（Q 矩阵）、`web/student/` + `web/parent/`（静态页）一并迁入
- 包名 `ecos.*` → `cogedu.*`：仅重命名 import 语句与功能性字符串引用（logger 名、patch 目标、路径字面量），逻辑零改动
- 基线选择：方案原定 v0.98.0 快照，经确认改为最新 v0.99.4（含三处真实生产修复）；v0.98.0→v0.99.4 内核增量（7 文件/+159 行）已逐文件补审，v0.98.0 审查结论全部仍成立
- 复制保真验证：ECOS 侧基线 1623 用例全绿（18.92s）；CogEdu 侧复制后 1623 用例全部通过

**安全网补齐（12.2 第 2 项）**
- 新增 `tests/test_answer_endpoint_contract.py`（4 用例，HTTP 级）：
  - `/api/answer` 响应 9 字段契约（8 个函数级字段 + 路由层回显的 `reasoning`）
  - partial credit 派生口径（score ≥ 0.6 → correct=True）
  - `persisted=true` 正向锚点
  - save 失败可见性：`persisted=false` 必须返回前端 + warning 留痕（v0.47.5 "Bisen 反馈 4 道题没存" 真实事故的防线）
- 当前全量：**1627 用例通过**

**工程配置**
- `pyproject.toml` 建立：依赖随 ECOS 平移（flask 为过渡依赖），ruff（E/F/W/I/B/UP）+ mypy（lenient 起步）规则配置
- 零 mutation AST 扫描器（`scripts/check_no_direct_state_mutation.py`）扫描路径已指向 `cogedu/`，本仓库扫描通过（54 文件无违规）
- `docs/plugin_sdk.md`、`docs/plugin_library.md`、`docs/pomdp_diagnostic.md` 随内核迁入（docs-sync 测试的检查对象），内部代码路径引用同步更新为 `cogedu/`
