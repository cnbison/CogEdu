# 呈现引擎 → Runtime 调用映射（Phase 1，1-A-2 / 1-A-4 / 1-A-5）

> 状态：Phase 1 契约文档。改 `GenerationContext` 字段、持久化表结构或回写事件路径前，先改本文档。
> 姊妹篇：`belief-migration-map.md`（答题主链路调用关系）。生效日期：2026-09-12。

## 1. 调用入口（唯一）

呈现引擎拿 intervention 的**唯一**方式：

```python
from cogedu.runtime.api import plan
lca_result = plan(student_id, audience="student")   # 返回 LCAResult
```

- `cogedu/presentation/` 只允许通过 `cogedu.runtime.api` 读内核，禁止
  import `cogedu.cta` / `cogedu.lca` / `cogedu.evidence` 内部类。
- 连 `LCAResult` 的**类型引用都不建立**：`GenerationContext.from_lca_result()`
  用 duck-typing getattr 读取（见 `cogedu/presentation/types.py`），
  防止未来顺手开始调用其内部方法。这也意味着若 Runtime API 返回结构
  变化（字段改名/类型变 Enum 变 str），出错点是显式 ValueError 或
  默认值口径，不会是隐蔽的类型耦合。

## 2. LCAResult 字段映射：哪些进 prompt，哪些只记录

| LCAResult / Intervention 字段 | GenerationContext 字段 | 进 LLM prompt | 理由 |
|---|---|---|---|
| `student_id` | `student_id` | 否 | 仅标识/落库，模型不需要 |
| `intervention.intervention_id` | `intervention_id` | 否 | 追溯引用，进 prompt 无意义 |
| `intervention.intervention_type` | `intervention_type` | **是** | 5 类干预决定讲解形态（explanatory→worked example 式；inquiry→提问引导式；feedback→对错因针对性讲解…） |
| `intervention.target_skills` | `target_skills` | **是** | 讲什么知识点 |
| `intervention.target_misconceptions` | `target_misconceptions` | **是** | 针对什么错因讲——这是第 11 章"错因诊断可视化"的数据源头 |
| `intervention.target_tcs` | `target_tcs` | **是** | 待跨越的概念边界 |
| `intervention.difficulty` | `difficulty` | **是** | 内容深度 [0,1] |
| `intervention.scaffolding_level` | `scaffolding_level` | **是** | 支持程度 → 提示/铺垫的多寡 |
| `intervention.clt_level` | `clt_level` | **是** | CLT 4 级 → worked example 完整度（expertise reversal） |
| `intervention.ca_stage` | `ca_stage` | **是** | CA 阶段 → 教练口吻 |
| `intervention.bloom_target` | `bloom_target` | **是** | 认知层次目标（理解/应用/分析…） |
| `intervention.rationale`（LCAResult 顶层 rationale 兜底） | `rationale` | **是**（可选） | LCA 为什么选这个干预，作为生成上下文提升内容针对性 |
| `intervention.quantity` | — | 否 | 题目数量，练习/出题侧参数，场景生成不消费 |
| `intervention.feedback_density` | — | 否 | 练习反馈密度，场景生成不消费 |
| `intervention.bjork_triggers` | — | 否 | 记忆调度标签（test/space/…），v1 与文字场景无关 |
| `intervention.estimated_duration_sec` | — | 否 | 预计时长，落库记录即可 |
| `expected_gain` | — | 否，**只记录** | LinUCB reward 内部估计值，进 prompt 会诱导 LLM 编造"预期效果"表述 |
| `expected_risk` | — | 否，**只记录** | 同上（Frustration 概率估计） |
| `timestamp` | — | 否 | — |

## 3. goal_id / evidence_id 的来源（v1 允许为 None）

`LCAResult` 本身不携带 goal/evidence 引用。约定：

- `GenerationContext` / `Outline` / `Scene` 上的 `goal_id` / `evidence_id`
  由**调用方（web 层）**在知道上下文时显式传入（例如从"答错某题 →
  生成讲解"入口进入时带上该次答题的 evidence_id）。
- Phase 1 允许为 None（直达入口没有错因上下文），但字段**现在就要
  存在并落库**——第 11 章可视化和 Evidence Engine 呈现依赖它。
- Phase 4/5 接 Evidence Engine 后，从答错链路进入的生成应强制携带。

## 4. 持久化契约（1-A-4，实现在 1-C-3）

双后端（SQLite 原路径 + PG 经 DSN），延续 12.5 `adapter.py` 模式。
实现位置：`cogedu/persistence/presentation_store.py`（仿 `lca_store.py` /
`dual_agent_store.py`），PG DDL 进 `pg_schema.py`。

```sql
-- outline：一行一份 Outline 完整 JSON payload
CREATE TABLE presentation_outlines (
  outline_id      TEXT PRIMARY KEY,
  student_id      TEXT NOT NULL,
  intervention_id TEXT NOT NULL,
  goal_id         TEXT,
  evidence_id     TEXT,
  payload         TEXT NOT NULL,   -- Outline JSON 全文；查询列只做索引不解析
  created_at      TEXT NOT NULL
);
-- scene：一行一个 Scene（大纲每步一个）
CREATE TABLE presentation_scenes (
  scene_id        TEXT PRIMARY KEY,
  outline_id      TEXT NOT NULL,
  step_id         TEXT NOT NULL,
  student_id      TEXT NOT NULL,
  intervention_id TEXT NOT NULL,
  goal_id         TEXT,
  evidence_id     TEXT,
  payload         TEXT NOT NULL,   -- Scene JSON 全文
  degraded        INTEGER NOT NULL DEFAULT 0,   -- 1-D-3 降级标记（可查询统计）
  created_at      TEXT NOT NULL
);
```

索引（追溯查询形状，第 11 章可视化的物理前提）：

- `idx_outlines_student (student_id)` / `idx_scenes_student (student_id)`
- `idx_scenes_outline (outline_id)` — 大纲 → 场景列表
- `idx_scenes_intervention (intervention_id)` — 这次干预产出了哪些场景
- `idx_scenes_evidence (evidence_id)` — **错因 → 场景反查**（证据链呈现入口）
- `idx_scenes_degraded (student_id, degraded)` — 降级率统计（1-D 观测）

查询形状（`PresentationStore` 方法）：

- `save_outline(outline) -> None` / `save_scene(scene) -> None`
- `get_outline(outline_id) -> Optional[Outline]`
- `list_scenes_by_outline(outline_id) -> List[Scene]`
- `list_scenes_by_intervention(intervention_id) -> List[Scene]`
- `list_scenes_by_evidence(evidence_id) -> List[Scene]`

失败语义：序列化/写库失败**不静默吞**——返回失败信号 + warning 留痕
（v0.47.5 教训的仓库约定），生成结果仍可返回给前端（呈现不因落库
失败而不可用），但调用方要能感知。

## 5. LLM 依赖注入（1-A-5）

- `cogedu/presentation/` **不 import `web.api.llm`**（方向倒置）。
- 生成器构造时注入 LLM client，presentation 侧只声明最小 Protocol
  （`chat_json(messages, ...) -> Any`），不绑定 `ECOSLLMClient` 具体类型
  （后者在 `cogedu/llm_client.py`，注入它的实例是 web 装配层的职责：
  FastAPI 依赖项里传 `get_llm()`；测试注入 mock）。
- `ECOSLLMClient.chat_json` 已自带 think 块剥离 + markdown 围栏清理 +
  JSON 解析失败抛 ValueError（含原始文本），1-D 的容错解析在其之上
  补"格式不完全合规 JSON"的修复层。

## 6. 回写路径（1-F 预告，Phase 1 后半实现）

场景行为（翻页/停留/提问）→ `LearningEvent` publish 到进程内事件总线 →
Plugin 订阅者 → `Runtime.update_belief`。零 mutation：呈现引擎不改任何
内核状态，只发事件（复用 12.3 验证的 `response_submitted` 模式）。
实现时在本节补事件类型与 payload 契约。

## 7. 防线

- `scripts/check_no_direct_state_mutation.py` 扫描范围已含
  `cogedu/presentation/**/*.py`（githooks pre-commit / pre-push 强制）。
- mypy 对 `cogedu.presentation.*` 启用 strict（pyproject override）。
