# CogEdu

面向 K12 数理化的教育认知系统。核心方法论继承自 ECOS（学生认知数字孪生 + AI 学习教练双 Agent 共进化架构），并借鉴 DeepTutor（记忆可追溯设计、可视化能力、家长权限模型）和 OpenMAIC（多智能体课堂呈现、白板动作引擎）的部分设计思路，用统一的技术栈（Python / FastAPI / PostgreSQL + pgvector / React + Vite + TypeScript）重新实现。

## 当前状态

**Phase 0 进行中**（2026-09-12）：12.2「建立安全网」+ 12.3「补齐状态入口缺口」+ 12.4「Flask → FastAPI」已完成——内核已从 ECOS v0.99.4 复制（包名改为 `cogedu`，仅 import 重命名）；**Web 层已全量迁移 FastAPI**（Flask 已删除，含 SSE 流式端点，响应契约与 Flask 版逐字段一致，前端零改动），全量 **1640 个测试用例通过**。下一步：12.5「SQLite → PostgreSQL」。进展明细见 [CHANGELOG.md](CHANGELOG.md)。

### 开发环境（克隆后一次性）

```bash
bash scripts/install-hooks.sh   # 启用 git hooks（pre-commit 零 mutation 扫描 / pre-push 全量测试）
```

未启用 hooks 时 commit/push 不做任何检查，建议所有贡献者启用。

### 本地运行

```bash
python -m web.api.app    # FastAPI 后端, 端口 5173 (前端 API base 沿用)
```

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
