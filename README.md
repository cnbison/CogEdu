# CogEdu

面向 K12 数理化的教育认知系统。核心方法论继承自 ECOS（学生认知数字孪生 + AI 学习教练双 Agent 共进化架构），并借鉴 DeepTutor（记忆可追溯设计、可视化能力、家长权限模型）和 OpenMAIC（多智能体课堂呈现、白板动作引擎）的部分设计思路，用统一的技术栈（Python / FastAPI / PostgreSQL + pgvector / React + Vite + TypeScript）重新实现。

## 当前状态

**方向修正（2026-09-16 拍板）**：内容层复盘（`docs/cogedu-复盘与方向修正-2026-09.md`）确认系统尚未用真实数理化内容跑过端到端（Q 矩阵全占位），**Phase 4/5/6 顺延**，先行双轨推进——**轨 1：P0-1a 三学科试点内容准备**（数学「一元一次方程」/物理「密度」/化学「物质的变化与性质」，真题 + 逐题评分 rubric + 误概念标注，原 Phase 5-1 并入）；**轨 2：UI-R 学生端桌面优先重设计**（学生设备口径定为横屏平板/电脑为主，工作台形态替代底部 Tab，白板讲解全幅呈现）。汇合后：学生实测 + 人工评估 → 呈现内容闸门 → 三学科内容规模化 → Phase 4/6。任务清单见[整合技术方案第 19 章](docs/cogedu-整合技术方案.md)。

**UI 现代化全量发布**（2026-09-16，人工验收通过）：React 18 + Vite + TS 前端（`web/frontend/`，移植自 ECOS v0.99.5 前端，只读复制自包含维护）三端落地——教师端（roster/学生详情证据链/POMDP 诊断，7 端点 1:1）、学生端（答题/成长/报告 + **讲解场景 React 化**：挂载式整合保留 Phase 3 vanilla 白板/播放模块与其 node:test 行为测试，渐进渲染——生成期间边生成边出页、音频逐场景回填）、家长端（概览四卡 + 授权管理 + Word 报告下载 + 学生端确认页）。认证走 CogEdu 自建体系（Bearer + 服务端会话，sid 取登录身份）；构建产物由 FastAPI dist 优先托管，**legacy 静态页已删除（双轨终点）**——克隆后须先 `cd web/frontend && npm run build` 再启动。验收期发现并修复 9 个真缺陷（学生样式表漏引 / 复看路由参数断链 / katex.min.js 漏引 / 家长端漏 Router 白屏 / 并发会话误判 401 等），均有契约锁。

**Phase 3 已全量发布**（2026-09-14）：**白板与语音**——讲解场景从"翻页阅读"升级为"白板讲解播放"：LLM 生成的动作序列（文字标注 / 图形 / 线段 / LaTeX 公式 / 语音讲解词）由播放引擎（三态状态机 + 代数令牌，支持暂停/重播本页）驱动白板渲染（虚拟画布 1000×562.5 等比缩放，DOM + SVG，KaTeX 本地 vendor 渲染公式）；语音经 MiniMax TTS 后台异步补齐，无音频时静音降级、字幕同步推进；已生成讲解支持只读复看。三项人工验收（动作序列 / 真实 TTS 听音 / 页面观感）完成。Phase 2（账号体系 / 家长端 / Word 报告导出）与 Phase 0/1 基础见 [CHANGELOG.md](CHANGELOG.md)。全量 **1955 个测试用例通过**（含 26 个 node:test JS 行为测试；前端另有 vitest 50 例）。下一步已由 2026-09-16 方向修正调整为 P0 内容验证冲刺 + UI 桌面化（见上）。

### 开发环境（克隆后一次性）

```bash
bash scripts/install-hooks.sh   # 启用 git hooks（pre-commit 零 mutation 扫描 / pre-push 全量测试）
```

未启用 hooks 时 commit/push 不做任何检查，建议所有贡献者启用。

### 本地运行

```bash
python -m web.api.app    # FastAPI 后端, 端口 5173 (前端 API base 沿用)
```

### 讲解场景（Phase 1 + Phase 3 白板语音）

登录学生端后点"看 AI 讲解"（React 路由 `/#/scene`）：讲解记录页可复看已生成的讲解（不触发生成），或点"生成新讲解" → 系统按当前认知状态选干预 → LLM 生成大纲 → 逐场景渐进生成（边生成边出页，含白板动作序列），翻页阅读 + 白板讲解播放（播放/暂停/重播，KaTeX 公式渲染，语音逐场景回填字幕同步）；翻页/看完行为回写内核，影响后续干预选择。场景生成需要 LLM API key（MiniMax 主/Moonshot 备，同 ECOS 约定）；语音合成需要 `COGEDU_TTS_API_KEY`（未配置时字幕静音推进，不影响使用）。**前端 UI 需先构建**：`cd web/frontend && npm run build`（React 三入口由 FastAPI dist 优先托管；无 dist 时页面入口 404）。

### 数据库切换（SQLite → PostgreSQL）

`ECOS_DB_PATH` 环境变量填 SQLite 文件路径（默认行为不变）或 `postgres://...` DSN 即可切换后端；存量数据迁移用 `python scripts/migrate_sqlite_to_pg.py --sqlite web/ecos.db --pg-dsn "postgres:///cogedu"`（自带行数/JSON/FK/BYTEA 四重校验）。

## 文档索引

| 文档 | 用途 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Claude Code 工作上下文：架构红线、技术栈结论、目录约定、协作规范 |
| [`docs/cogedu-整合技术方案.md`](docs/cogedu-整合技术方案.md) | **主文档**。架构决策、技术栈选型、Phase 0-6 分阶段任务清单（活文档，随进展更新） |
| [`docs/kernel-baseline-notes.md`](docs/kernel-baseline-notes.md) | 内核基线说明：从 ECOS 继承了什么、哪些工程决策是刻意的不能"修复" |
| [`docs/belief-migration-map.md`](docs/belief-migration-map.md) | 答题主链路（`belief.py`）的行为对照表：重写 FastAPI 版时不能遗漏的实战检验行为点 |

建议阅读顺序：CLAUDE.md → 整合技术方案第 2/5 章（原则与技术栈）→ 按需查阅其余章节。

## 关于三个参考项目

本仓库的开发参考了三个本机项目：ECOS（核心方法论与内核代码来源）、DeepTutor、OpenMAIC。

**它们只是本机参考代码，不是本仓库的依赖。** CogEdu 不 import 它们、不引用它们的路径，借鉴的实现均复制后自包含维护或重新实现——即使删掉这三个本机目录，本仓库仍应完整可开发、可测试。详细边界见 [`CLAUDE.md`](CLAUDE.md)。

## 许可证

[Apache-2.0](LICENSE)
