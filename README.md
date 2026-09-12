# CogEdu

面向 K12 数理化的教育认知系统。核心方法论继承自 ECOS（学生认知数字孪生 + AI 学习教练双 Agent 共进化架构），并借鉴 DeepTutor（记忆可追溯设计、可视化能力、家长权限模型）和 OpenMAIC（多智能体课堂呈现、白板动作引擎）的部分设计思路，用统一的技术栈（Python / FastAPI / PostgreSQL + pgvector / React + Vite + TypeScript）重新实现。

## 当前状态

**Phase 1 完成**（2026-09-12）：**呈现引擎最小可用版本上线**——两阶段生成（Runtime `plan()` → 结构化大纲 → 讲解场景），学生端 `/student/scene.html` 翻页式播放（KaTeX 公式渲染），场景行为回写内核（human feedback 通道，影响后续干预选择）；生成健壮性（json-repair 容错 + 重试 + 模板化降级）；真实进程灰度 3 案例全通过。Phase 0 基础（FastAPI Web 层 / 双后端持久化 / 内核复制）见 [CHANGELOG.md](CHANGELOG.md)。全量 **1728 个测试用例通过**。下一步：Phase 2（家长端重新设计 + 导出能力）。

### 开发环境（克隆后一次性）

```bash
bash scripts/install-hooks.sh   # 启用 git hooks（pre-commit 零 mutation 扫描 / pre-push 全量测试）
```

未启用 hooks 时 commit/push 不做任何检查，建议所有贡献者启用。

### 本地运行

```bash
python -m web.api.app    # FastAPI 后端, 端口 5173 (前端 API base 沿用)
```

### 讲解场景（Phase 1）

登录学生端后点"讲解"标签（或直接访问 `/student/scene.html?sid=<学生ID>`）：系统按当前认知状态选干预 → LLM 生成大纲 → 逐步生成讲解场景，翻页式播放（KaTeX 公式渲染）；翻页/看完行为回写内核，影响后续干预选择。场景生成需要 LLM API key（MiniMax 主/Moonshot 备，同 ECOS 约定）。

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
