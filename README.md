# CogEdu

面向 K12 数理化的教育认知系统。核心方法论继承自 ECOS（学生认知数字孪生 + AI 学习教练双 Agent 共进化架构），并借鉴 DeepTutor（记忆可追溯设计、可视化能力、家长权限模型）和 OpenMAIC（多智能体课堂呈现、白板动作引擎）的部分设计思路，用统一的技术栈（Python / FastAPI / PostgreSQL + pgvector / React + Vite + TypeScript）重新实现。

## 当前状态

**文档规划阶段，Phase 0 尚未开始**——仓库目前只有文档，没有任何代码。首个开发任务是技术方案 12.2 节"建立安全网"。

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
