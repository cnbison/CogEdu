# CLAUDE.md — CogEdu 项目指南

> 本文件是 Claude Code 每次在本仓库工作时会自动读取的上下文。请严格遵守本文件里的架构红线，不确定的地方优先去查阅 `docs/cogedu-整合技术方案.md`（完整方案）或直接询问维护者，不要自行假设。

## 项目是什么

CogEdu 是一个面向 K12 数理化的教育认知系统，**核心方法论继承自 ECOS**（学生认知数字孪生 + AI 学习教练双 Agent 共进化架构），并借鉴了 DeepTutor（记忆可追溯设计、可视化能力、家长权限模型）和 OpenMAIC（多智能体课堂呈现、白板动作引擎）的部分设计思路，用统一的技术栈重新实现。

**完整的架构决策和分阶段任务清单见 `docs/cogedu-整合技术方案.md`——这是本项目最重要的参考文档，涉及架构判断、技术栈选型、Phase 划分的问题都应该先查这份文档，不要重新发明。**

## 三个参考项目的本机路径

这三个项目**不是本仓库的依赖，只是本机的参考代码**，供随时查阅、复制具体实现细节用。请在下面填入实际路径（建议用相对路径或环境变量，避免因为路径不同导致文档失效）：

```
ECOS（核心方法论来源，内核代码从这里复制而来）：../ecos
OpenMAIC（呈现层/白板/动作引擎参考）：../OpenMAIC
DeepTutor（记忆/可视化/家长权限模型参考）：../DeepTutor
```

需要参考某个具体功能的实现细节时，直接去对应路径下查代码，不要凭记忆/训练数据里的通用知识去猜测这几个项目的具体实现。

**硬边界（不可协商）**：这三个项目只是本机的参考代码，**绝对不能变成 CogEdu 的依赖项或不可或缺的一部分**：

- CogEdu 代码中不得出现任何指向参考项目路径的 import、`sys.path` 操作或构建/运行配置引用。
- 借鉴的实现要么复制进来后自包含维护（复制时在提交说明里记录来源），要么按其思路用 CogEdu 技术栈重写，不做运行时引用。
- 全部测试和构建必须在不接触参考项目路径的情况下通过——即使删掉这三个本机目录，CogEdu 仍应是一个完整可开发、可测试、可部署的仓库。
- 怀疑某处引用是否越界时，先指出并询问维护者，不要自行放行。

## 架构红线（不可协商，任何 Phase 的开发都必须遵守）

1. **状态只能通过 Runtime（或其认可的事件驱动路径）变更**。任何新代码都不允许直接 import 并调用内核内部类（`ecos.cta.*`、`ecos.evidence.*` 等）来改变学生的认知状态。ECOS 自己的核心答题路径是通过事件总线间接调用 Runtime 的（发布事件 → Runtime 订阅者处理），这是一个刻意的解耦设计，值得在 CogEdu 里延续，不是必须改成直接函数调用。
2. **Plugin 只产生 Event，不直接改状态**（零 mutation site 原则）。新功能优先以 Plugin 形式接入，而不是修改内核。
3. **验证优先于新功能**。不要因为某个 Phase 的功能"看起来很酷"就超前于验证工作投入过多资源。
4. **内核算法层面（CTA 的 belief 推断/更新、LCA 的 POMDP/PBVI 策略学习）不需要大改**——这部分代码质量经过审查确认是扎实的（读写分离清晰、有版本演进记录和防御性自检）。如果发现需要修改内核算法，先确认是否真的必要，不要顺手"顺便优化"。
5. **不要凭空"修复"看起来奇怪的工程决策**。比如 ECOS 的 CI 只能手动触发（`workflow_dispatch`），这是刻意的设计（避免 CI 环境和本地环境因缺 LLM/DB 而产生伪错配），不要"好心"把它改成自动触发的 CI，除非确认团队协作模式已经变化到需要这样做。

## 当前状态（2026-09-12 更新）

- **参考文档版本**：`docs/cogedu-整合技术方案.md` v0.5
- **当前 Phase**：**Phase 1 全部完成**（2026-09-12）——1-A「接口契约」+ 1-B「大纲生成」+ 1-C「场景生成」+ 1-D「生成健壮性」+ 1-E「前端渲染」+ 1-F「回写事件闭环」+ 1-G「端到端验证」（真实进程灰度 3 案例全通过，内容质量人工复核无误）。**呈现引擎 = `cogedu/presentation/`**（两阶段生成：Runtime `plan()` → Outline → Scene，只读调用 Runtime API，LLM 注入不绑 web 层）；场景页 `web/student/scene.html`（翻页式 + KaTeX）；行为回写走 human feedback 通道（`scene_viewed`/`scene_completed` 事件 → PluginRuntime → `append_human_feedback`，**刻意不走 `update_belief`**，理由见 `docs/presentation-runtime-map.md` §6）。**Phase 2 进行中**：任务清单已细化（方案文档第 14 章）；**2-0 最小账号体系已完成（2026-09-12）**——`cogedu/persistence/auth_store.py`（users/sessions 双后端，bcrypt + 服务端会话不用 JWT）+ `web/api/auth.py`（login/logout/me + 角色矩阵 dependencies）+ `web/login.html`/`auth.js` 前端登录态；存量测试经 conftest `auth_bypass` 零破坏，鉴权语义由 `real_auth` marker 测试覆盖；parent per-student 关系校验随 2-A 落地。全量 **1765 用例通过**。**2-A 权限模型已完成（2026-09-12）**——`guardian_learner_link` 显式授权（pending→active/rejected/revoked 状态机 + 同对唯一活跃关系 partial unique index）+ `guardian_can_access` 单一校验入口（每次现查双方角色、无缓存、撤销下一请求即失效）+ 授权流程端点（学生本人确认制，admin 可代确认）；家长端 roster/overview 已接 per-student 校验。全量 **1786 用例通过**。**2-C 学习报告导出已完成（2026-09-12）**——`web/api/formula_render.py`（mathtext LaTeX→PNG，spike 验证 88%、预检不支持构造）+ `report.py`（ReportDocument 结构层，同源 overview 聚合）+ `docx_renderer.py`（公式 PNG 嵌入/失败降级原文）+ `GET /api/parent/students/{sid}/report`（download_report 权限）。全量 **1804 用例通过**。**Phase 2 收官（2026-09-12）**：2-0 账号 + 2-A 权限 + 2-C Word 报告导出 + **2-D 前端**（`web/parent/index.html` 真实家长端：roster/概览/授权管理/报告下载；`web/student/guardian-links.html` 学生确认页）+ **2-E 灰度**（`scripts/canary_phase2_parent.py` 14 步真实进程通过，含越权 403 与撤销立即生效验证）。全量 **1804 用例通过**。**待维护者**：小范围真实家长用户灰度验证后全量发布。下一步：继续 Phase 3（白板与语音）——任务清单已于 2026-09-12 细化落档（方案文档 v0.6 第 15 章，四项决策拍板：DOM+SVG 渲染路线、增补 `wb_draw_line`、砍撤销/重做换"重播本页"、TTS 异步补齐+播放端降级）。**3-A 动作模型已完成（2026-09-13）**——`types.py` 新增五动作 Pydantic union（`ActionBase` 公共字段 + 白名单常量 + `clamp_canvas_point`）+ `schema_version` 机制（actions 非空自动升 v2，Phase 1 存量 payload 兼容回归锁定）。**3-C 播放引擎已完成（2026-09-13）**——`web/student/playback.js`（三态状态机 + 代数令牌 + 剩余时间暂停恢复 + 音频 ended/估算兜底三级路径 + 重播本页，renderer/speechPlayer 依赖注入）；时序正确性由 **node:test 真测试**锁定（`tests/js/playback.test.cjs` 14 用例，`test_playback_engine_js.py` pytest 包装、无 node skip）——仓库首个 JS 行为测试。**3-B 白板渲染已完成（2026-09-13）**——`web/student/whiteboard.js`（DOM+SVG path 路线，虚拟画布 1000×562.5 等比缩放，实现 3-C renderer 接口）+ `web/student/formula.js`（KaTeX 共享模块，scene 文字块与白板公式同源）+ scene 页白板讲解区（播放/暂停/重播控件 + 字幕 + 翻页联动 `stopPlayback`）；`tests/js/whiteboard.test.cjs` 10 用例 + `test_whiteboard_wiring.py` 9 用例 grep 契约。全量 **1838 用例通过**（含 JS 24 例）。下一步：3-D 语音合成集成（MiniMax TTS + 字节嗅探时长 + presentation_audio 表），之后 3-E/3-F/3-G。
- **内核代码状态**：**已复制**（2026-09-11）。来源 **ECOS v0.99.4，commit `9cdacab`**（比方案文档原定的 v0.98.0 快照新，经用户确认取最新版；v0.98.0→v0.99.4 内核增量 7 文件/+159 行已补审，结论见 `docs/kernel-baseline-notes.md`）。包名 `ecos` → `cogedu`，仅重命名 import，逻辑零改动，复制后全量测试与基线一致。**Phase 1 内核 additive 变更**（1-F 事件类型 +2 / 新 factory，算法零改动，见 `kernel-baseline-notes.md` §8）。
- **仓库现状**：`cogedu/`（内核，121 文件）+ `cogedu/presentation/`（**Phase 1 新写**：types.py 契约 schema + outline/scene 生成器 + json_repair/retry 健壮层；纳入零 mutation 扫描 + mypy strict）+ `web/`（**FastAPI 后端**：`app.py` 装配 + `routers/` 8 域路由（含 presentation）+ 框架无关业务模块 `belief.py`/`llm.py`/`judge.py`/`presentation_service.py` 等；student/parent 静态页由 FastAPI 托管，student 场景页 `scene.html|js|css`）+ `cogedu/persistence/`（双后端：adapter.py 适配层 + pg_schema.py PG DDL + 迁移脚本 + **presentation_store.py**）+ `githooks/`（pre-commit/pre-push，核心架构红线静态防线）+ `tests/`（1728 用例，含 PG 集成测试无服务器时 skip）+ `scripts/`（含零 mutation AST 扫描器 + Phase 1 灰度脚本）+ `examples/`（Plugin SDK 样例）+ `data/`（Q 矩阵）+ `discussions/`、`research/`（仅收录测试与文档引用的设计文档）+ `docs/`（含 **presentation-runtime-map.md** 呈现引擎契约映射）。

## 技术栈（详见方案文档第 5 章，这里只列结论）

- 认知内核：Python（原样复制自 ECOS，不重写）
- Web 框架：FastAPI（新写，不是 Flask）
- 数据库：PostgreSQL + pgvector（不是 SQLite）
- 前端：React + Vite + TypeScript
- 数学公式渲染：网页端用 KaTeX；导出 Office 文档时公式转换参考 OpenMAIC 的 mathml2omml 思路

## 目录约定（新仓库，建议约定，可按实际情况调整）

```
cogedu/
├── docs/
│   ├── cogedu-整合技术方案.md       # 完整架构方案（本文档引用的主文档）
│   ├── kernel-baseline-notes.md    # 内核基线说明（从 ECOS 继承了什么、为什么这么设计）
│   └── belief-migration-map.md     # 答题主链路的调用关系映射（写新 FastAPI 实现时的对照表）
├── cogedu/                          # 核心 Python 包
│   ├── cta/ lca/ evidence/ event/ goal/ bloom/ domain/ plugins/ runtime/   # 从 ECOS 原样复制
│   ├── presentation/                # 呈现引擎（新写，Phase 1/3 涉及）
│   └── persistence/                 # 新写（PostgreSQL）
├── web/                             # FastAPI 路由层（新写，不是 Flask）
├── frontend/                        # React + Vite + TS
└── tests/                           # 从 ECOS 迁移过来的测试 + 新增测试
```

## 协作规范

- 涉及内核代码（`cogedu/cta/`、`cogedu/lca/` 等从 ECOS 复制的部分）的改动，先去 `docs/kernel-baseline-notes.md` 查一下有没有相关的历史教训/设计约束，再动手。
- **任何可能失败的序列化/持久化操作，宁可返回明确的失败信号或安全默认值并记录 warning，也不要静默吞掉异常**。这不是泛泛的最佳实践建议，是 ECOS 真实踩过的坑（`docs/belief-migration-map.md` 记录了至少三次同类历史事故，包括一次真实的学生数据丢失事故），CogEdu 的新代码延续这个约定。
- 每完成一个 Phase 0-6 的具体任务项，回到 `docs/cogedu-整合技术方案.md` 对应章节勾掉/更新状态，保持文档和实际进展同步——这份文档本身应该是"活文档"。
- **每完成一个任务（无论是文档修正还是代码任务），自动收尾**：更新相关文档状态 → `git add` + `commit`（信息写清楚做了什么、为什么）→ `push` 到 `origin`。不等用户提醒；如果 push 失败（网络/权限），如实报告并保留本地提交。提交信息使用中文或英文均可，但要能从提交历史还原每一步决策。
- 不确定某个改动是否符合架构红线时，优先询问，不要自行假设"应该没问题"就继续。
