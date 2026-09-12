# Changelog

本文件记录 **CogEdu 自身**的版本演进。内核代码复制自 ECOS（v0.99.4，commit `9cdacab`，2026-09-11），ECOS 的历史版本记录不在本文件范围内——如需追溯内核的历史设计决策，见 `discussions/` 收录的设计文档与 ECOS 仓库。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

### 2026-09-12 — Phase 2 / 2-A 家长-学生权限模型（完成）

**guardian_learner_link 显式授权**（2-A-1/2，`auth_store.py` 增表）：状态机 `pending → active / rejected / revoked`，partial unique index `WHERE status IN ('pending','active')` 保证同对唯一活跃关系（撤销/拒绝后可重申）；撤销留痕（revoked_by / revocation_reason，对齐 DeepTutor）。权限项五档：view_progress / view_evidence / download_report / receive_alerts（留位）/ assign_materials（留位）。

**服务层**（`web/api/guardian.py`）：`guardian_can_access` 单一校验入口，**每次现查双方当前角色**（角色变更/禁用后旧授权自动失效）+ 无缓存（撤销下一请求即失效）；家长按学生 username 发起申请（自绑禁止 / 非 student 角色拒绝 / 权限白名单）。

**授权流程端点**（`routers/guardian.py`，2-A-3）：家长申请/列表/撤回撤销；学生查看待确认/确认/拒绝/撤销；低龄场景 admin 可代确认。错误分级 400/404/409。

**家长端数据接口接入 per-student 校验**（2-A-4）：roster 只列 active 关联学生的学习记录（学习记录懒创建语义不变）；overview 过 `view_progress` 权限，未授权 403；staff 全量视图不变（存量契约测试零破坏）。

**验证**：`tests/test_guardian_links.py` 21 用例（全流程/申请规则/撤销立即生效/角色变更失效/权限粒度/多家长互不干扰/staff 视图）。全量 **1786 用例通过**。授权管理前端页归 2-D。

### 2026-09-12 — Phase 2 / 2-0 最小账号体系（完成）

**背景**：Phase 2 任务清单细化时发现仓库完全没有账号/身份体系（无 users 表、无鉴权，家长端接口无鉴权枚举全部学生），而 2-A 权限模型与灰度验收都以此为前提，故 2-0 作为地基先行。

**持久化**（2-0-1）：`cogedu/persistence/auth_store.py` — users 表（bcrypt 凭证哈希、guardian/student/teacher/admin 四角色、学生账号经 `learning_student_id` 关联 students 学习记录 1:1，无 FK——学习记录懒创建）+ sessions 表（**token 只存 SHA-256 哈希**；服务端会话刻意不用 JWT——"撤销立即生效"是 2-A 验收点）。双后端沿用 LCAStore/PresentationStore 模式，独立 DDL 不动 kernel 镜像的 SCHEMA_SQL。

**认证服务与端点**（2-0-2）：`web/api/auth.py`（bcrypt 校验、会话签发/现查/撤销、禁用账号即撤全部活跃会话；TTL 默认 7 天 `COGEDU_SESSION_TTL_HOURS` 可配；登录统一 401 防用户名枚举）+ `routers/auth.py`（login/logout/me，Bearer header 方案）。

**路由角色矩阵**（2-0-3）：teacher→staff、parent→guardian+staff、student 数据/事件回写/呈现引擎→学生本人（路径参数或 body 的 student_id 与 `learning_student_id` 一致性校验）或 staff、stream→已登录、`/api/students/recent` 收紧。存量 ~1700 契约测试零破坏：conftest autouse `auth_bypass` patch `_resolve_request_user`（测试层设施，非生产后门）；鉴权语义由 `real_auth` marker 下的测试覆盖。canary 脚本接真实开户+登录；`scripts/manage_users.py` 开户 CLI（v1 无自助注册）。**遗留（记录在案）**：parent per-student 的 `guardian_learner_link` 校验随 2-A 落地。

**前端登录态**（2-0-4）：`web/auth.js`（token 存取/authFetch/页面守卫/logout）+ `web/login.html`（按角色跳转，防 open redirect）+ 学生端 authFetch 统一带 Authorization、scene 回写带身份、teacher/parent 页接守卫。

**验证**：新增 `tests/test_auth_api.py` 37 用例；真实进程冒烟（CLI 开户 → 登录 → 带 token 200 → logout → 旧 token 立即 401）。全量 **1765 用例通过**。

### 2026-09-12 — Phase 1 / 呈现引擎最小可用版本（完成，1-A~1-G 收官）

**两阶段生成**（`cogedu/presentation/`，Phase 1 新写包）：Runtime `plan()` → `GenerationContext`（duck-typing 提取，不建立 LCAResult 类型引用）→ `OutlineGenerator`（大纲）→ `SceneGenerator`（场景，每步 text+image 两 block）。契约 schema（Outline/Scene/GenerationContext）用 Pydantic，同时服务 LLM 输出校验 / HTTP 响应模型 / 落库 payload；契约映射表见 `docs/presentation-runtime-map.md`。包边界：只读调用 `cogedu.runtime.api`，LLM client 注入不绑 web 层；纳入零 mutation 扫描 + mypy strict。

**生成健壮性**（1-D）：`json-repair`（PyPI，MIT）容错解析（think 块剥离 + 围栏清理 + 不合规 JSON 修复）；`RetryPolicy` 环境变量可配，生成层只重试解析失败（传输层由 client 内部重试）；重试耗尽 → 模板化 degraded scene（`degraded=true` + warnings 留痕，学生端不空白）。**灰度发现**：MiniMax-M3 thinking 块计入 max_tokens，默认 1024 会被推理耗尽 → 生成器显式 4096。

**回写事件闭环**（1-F，语义决策偏离 13.7 字面并已记录）：场景行为不伪造作答 Observation 进 `update_belief`（会污染 CTA 推断），走 v0.91.0-b 确立的 human feedback 通道——内核 additive 扩展 `scene_viewed`/`scene_completed` 事件类型（算法零改动，见 `kernel-baseline-notes.md` §8）→ `POST /api/presentation/event` → PluginRuntime → `append_human_feedback` → 影响后续 `plan()`。

**前端**：学生端新增"讲解"标签 + `scene.html|js|css` 独立场景页（翻页式，KaTeX 公式渲染——LLM 文本一律 textContent 进 DOM 不裸 innerHTML；图片懒加载 + 失败占位；degraded 提示条）。

**持久化**：`PresentationStore` 双后端（SQLite/PG 奇偶校验测试），`presentation_outlines`/`presentation_scenes` 两表，追溯列索引含 `idx_scenes_evidence` 错因反查（第 11 章可视化的物理前提）。

**端到端验证**（1-G）：真实进程灰度 3 案例（真实 MiniMax LLM）全部通过——5 场景零降级、行为回写 200、答对后 theta K 上移、内容质量人工复核（算术全对、Bloom 目标体现于讲解形态）；`tests/test_presentation_e2e.py` 全链路 HTTP 级回归。全量 **1728 用例通过**（Phase 0 收官时 1651）。

### 2026-09-12 — Phase 0 / 12.6 回归与灰度（完成，Phase 0 收官）

**全量回归**：1651 用例通过，pre-push hook 持续复验。

**真实进程灰度**（uvicorn + PG canary 库）：答题主链路（9 字段契约 / theta 演化 / M8 误概念 F-10 触发 / lca_decision passthrough）、真实 LLM judge、事件落库、教师端 7 视图、家长端（幽灵学生 404）、报告 interpretation、SSE 真实服务端推流、静态页 no-cache、重启持久化（theta_cov 真实 SE 恢复 / history / answered_ids 防重复出题）、dual_agent 开关两路径进程级验证——全部通过。

**灰度发现并修复**：`web/teacher/` 静态页为 12.2 内核复制遗漏（ECOS 有、CogEdu 无，`/teacher/` 自复制起恒 404），已按复制自包含原则补入。

### 2026-09-12 — Phase 0 / 12.5 SQLite → PostgreSQL（完成，双后端化）

**轻量适配层**（`cogedu/persistence/adapter.py`）：占位符翻译 / 行值归一化 / DSN scheme 识别 / executescript 分句 / 连接工厂。不上 ORM，"换数据库不触碰业务逻辑"落到全部 5 个持久化模块（db.py Database + DualAgentStore + LCAStore + EventLog.from_sqlite + evidence_engine，比原计划 db.py 单点多覆盖 4 个）。

**PostgreSQL schema**（`pg_schema.py`）：9 表 + 2 状态表 DDL。JSONB 评估结论：Phase 0 维持 TEXT（整存整取无 SQL 级查询需求 + 5 写入口统一 JSON 字符串契约优先，升级 ALTER 已备档）；布尔语义列 INTEGER 0/1、时间戳 TEXT ISO。

**双后端行为统一**：`RETURNING` 统一取代 `lastrowid`（SQLite ≥3.35）、`INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`、upsert 限定目标表列名（PG AmbiguousColumn 教训）、PG 事务 = autocommit 连接 + `transaction()` 块 + RLock 串行（对齐 SQLite 单写者语义）。

**数据迁移脚本**（`scripts/migrate_sqlite_to_pg.py`）：FK 依赖序写入、幂等重跑、IDENTITY 序列对齐；四重校验（行数逐表 / JSON 抽检 / FK 孤儿行 / BYTEA 字节）。端到端实测通过。

**PG 集成测试**（`tests/test_pg_backend.py`，11 用例，无 PG 服务器 skip）：双后端 CRUD 奇偶校验、事务回滚/提交（SQLite 原语义零回归）、20 线程并发写 + 读写混合、psycopg_pool 连接池并发验证、全部持久化模块 PG 走通。

**验证**：SQLite 路径全量 **1651 用例通过**（零回归）；开发机 PostgreSQL 17.11 实测 PG 用例全过。

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
