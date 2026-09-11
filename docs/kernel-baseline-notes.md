# 内核基线说明

> 这份文档的目的：把 ECOS `discussions/` 目录里真正有长期参考价值的内容提炼出来，避免把 ECOS"文档过多过乱"的包袱原样搬进 CogEdu。**这不是 ECOS 全部历史的搬运，只挑对 CogEdu 开发有实际约束意义的部分**。如果发现某条历史教训在这里没提到但确实相关，建议单独去 ECOS 仓库查阅原始 discussions，而不是把整个目录搬过来。

## 1. 内核代码的来源与信任基础

> 状态说明（2026-09-11 更新）：**复制已完成**。来源为 **ECOS v0.99.4（commit `9cdacab`）**，比本方案最初审定的 v0.98.0（2026-09-06 快照）更新——经维护者确认取最新版，理由：v0.98.0→v0.99.4 之间包含真实生产修复（Plugin 路径 log_event 落库恢复、LCA 重复决策去重、ECOS_DB_PATH 测试/生产库隔离）。复制时包名 `ecos` 改为 `cogedu`（仅 import 重命名，逻辑零改动），复制后全量测试与 ECOS 基线一致（1623 用例全绿）。**v0.98.0→v0.99.4 的内核增量共 7 个文件、+159 行，已逐文件补审**：版本号 bump、evidence 懒加载单例化、`Intervention.created_at` 加性字段、LCA 决策指纹去重、`judge_audit_log` 表 + `save_judge_audit`、三处 `get_*` 单例的 `ECOS_DB_PATH` 支持——无新增 mutation site、无绕过 Runtime 的新路径，v0.98.0 的审查结论全部仍成立。

CogEdu 的 `cogedu/cta/`、`cogedu/lca/`、`cogedu/evidence/`、`cogedu/event/`、`cogedu/goal/`、`cogedu/bloom/`、`cogedu/domain/`、`cogedu/plugins/`、`cogedu/runtime/` 这几个包，是**从 ECOS 原样复制过来的**（v0.99.4），规模约 27,600 行 Python 代码、121 个文件，配有 1623 个测试用例（v0.98.0 时为 1599，v0.99.4 新增 24 个）。

**为什么可以放心复制而不重写**：
- CTA 的 `belief_engine.py` 内部有清晰的读写分离设计：`InferenceEngine.run()` 只产出推断结果、不做状态变更；`BeliefUpdator.apply()` 是唯一的状态变更点。这是一个经过刻意设计、执行得比较彻底的 CQRS 式架构。
- LCA 的 POMDP/PBVI 策略学习（`lca/l4_optimization/pomdp.py` + `pomdp_solver.py`，约 1600 行）是真实实现（α-vector、belief points、贝叶斯 backup 公式都在代码里），不是占位符或简化版，且有清晰的版本演进记录（v0.87→v0.88→v0.89→v0.90 逐步从简化转移矩阵升级到 PBVI 完整集成），每一步升级都配有"防御性自检 hard block"和"canary 必须 PASS"的回归约束。

**结论**：内核算法层面是整个项目里质量最扎实、风险最低的部分，**不需要在整合过程中大改**。如果开发中发现某个内核模块"看起来可以优化"，先假设自己可能没理解它为什么这样设计，去查一下原始 ECOS 仓库对应模块有没有相关的 discussions 记录再决定要不要动。

## 2. "答题主链路是否绕过 Runtime"——一个已经想清楚的架构问题

这是本次架构评审过程中最容易被误判的一点，专门记一下，避免 CogEdu 开发时重蹈覆辙：

`web/api/belief.py` 里的 `submit_answer`（学生提交答案的核心入口）**并不是直接调用 `BeliefEngine.update()`**，而是先构造一个 `LearningEvent`，发布到一个事件总线（`bus.publish("response_submitted", event)`），由 `PluginRuntime._handle_response_submitted` 订阅者接手，内部再委托给 `Runtime.update_belief`。生产环境的 `app.py` 启动时会显式激活这个订阅者。

**这是一个刻意的、经过验证的解耦设计**：状态变更逻辑通过事件驱动的方式和 Web 层解耦，而不是让 Web 层直接持有对内核的强引用。**CogEdu 的新 FastAPI 实现应该延续这个模式**，不要简化成"Web 层直接调用 Runtime 函数"这种更直白但耦合更紧的写法——这里的间接性是有意为之的架构优点，不是历史遗留的绕弯路。

只有几处**具体、局部**的操作是真正的直接调用、值得在 CogEdu 重写时重新评估是否要纳入统一入口：题目 MIRT 参数注册（`engine.l2.register_item`）、状态持久化（`save_student_state`）、误概念 reconcile（`reconcile_for_student`）。详见 `docs/belief-migration-map.md`。

## 3. 工程决策：CI 为什么只能手动触发

ECOS 的 GitHub Actions 配置成只能 `workflow_dispatch` 手动触发，不是自动跑在每次 push/PR 上。这是刻意的选择：CI 环境缺真实的 LLM API/数据库依赖，曾多次出现"本地测试通过、CI 报红"的伪错配，团队改用本地 `pre-commit`/`pre-push` git hook 做实际的质量门禁。

**CogEdu 如果沿用类似的开发模式（个人/小团队为主），建议维持这个思路**，不要"顺手"改成标准的自动 CI，除非团队协作模式变化到确实需要（比如多人协作、需要 PR 自动检查）。

## 4. Goal Ontology 机制是现成的，内容是空的

`ecos/goal/goal.py` 定义的 `Capability(name, description, domain)` 和 `Goal(goal_id, capability, objective, bloom_level, metric_dimension, metric_threshold, evidence_ids, status)` 这套数据结构是完整可用的，`evidence_ids` 字段可以直接复用给知识库片段关联。**但现有 `ScienceDomain` 里只注册了三个通用科学方法能力**（`hypothesis`/`experiment`/`analysis`），不是具体的数理化课纲知识点。

**结论**：CogEdu 做教学素材接入（对应方案文档 Phase 5）时，不是"接入一套现成的数理化知识体系"，而是要从头把真实教材的知识点注册进这套现成的机制里。机制不用重新设计，内容需要重新填充。

## 5. Capability 之间目前没有先修/依赖关系建模

如果未来要做"知识点概念图"（方案文档 Phase 6 的 `CONCEPT_GRAPH` 区块），要注意 `Capability`/`Goal` 之间目前完全没有先修关系的数据结构——这不是一个"补个字段"就能解决的小事，是一项独立的知识工程工作，评估投入前先想清楚这一点。

## 6. 持久化现状

ECOS 用原生 `sqlite3`（标准库，无 ORM）+ 手写 SQL，9 张表：`event_log`/`evidence_log`/`students`/`interventions`/`calibration_log`/`bloom_goals`/`trajectory_snapshots`/`misconception_evidence`/`judge_audit_log`。表设计本身合理，可以作为 CogEdu 迁移到 PostgreSQL 时的 schema 参考蓝本，不需要重新设计表结构，只需要换底座（并评估哪些字段适合从 TEXT 存 JSON 改成原生 `JSONB`）。

## 7. 与 SelfLab / CogMirror 的关系

ECOS 自己的文档里提到过和一个叫 SelfLab 的项目、以及一个叫 CogMirror 的兄弟项目（面向成年自学者、无 LLM 依赖，用作确定性算法的低成本试验场）的关系。**按已经确认的决定，CogMirror 不纳入 CogEdu 的整合范围**，这里验证过的内容视为已经吸收进当前的 ECOS 内核里，不需要再单独去查 CogMirror 的代码或文档。
