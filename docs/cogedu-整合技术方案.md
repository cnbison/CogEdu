# 教育认知操作系统整合方案（CogEdu）

> 版本：v0.5 draft　|　日期：2026-09-10　|　基础项目：ECOS（核心） + DeepTutor（记忆/知识借鉴） + OpenMAIC（呈现层借鉴）
>
> **v0.5 相对 v0.4 的主要变化**：**更正了一处此前的分析错误**——v0.3 曾判断"学生答题主链路绕过 Runtime 直连内核"，进一步核实代码后发现这个判断不准确：核心路径其实通过事件总线正确接入了 Runtime，只是调用方式是间接的（发布事件而非直接函数调用），之前的分析方法（只搜字面 import）没有覆盖到这种模式。第 2.2 节、第 8/12 章的 Phase 0 范围已相应收窄和修正。

---

## 0. 本文档的目的与读法

这是一份**开发前的架构决策文档**。v0.1/v0.2 基于三个项目的 README 做判断，v0.3 起基于实际代码复核过一轮，属于目前信息量最扎实的版本。仍然建议先看第 2 章和第 5 章，其余章节建立在其上。

---

## 1. 一句话定位

**以 ECOS 的认知理念（状态优先计算、双 Agent 互校、可追溯证据）为核心方法论，把 DeepTutor 的记忆可追溯设计经验和 OpenMAIC 的多智能体课堂呈现能力，以"服务/插件"的形式接入，用一套面向长期演进的技术栈重新实现，形成一个功能相对完备的教育认知系统产品。**

---

## 2. 整合原则

### 2.1 理念 / 架构原则 / 具体实现三层（结合代码审查更新）

| 层次 | 内容 | 能不能动 | 代码审查后的更新判断 |
|---|---|---|---|
| **理念层** | 状态优先计算、双 Agent 互校、可追溯证据、抗幻觉 | 不能动 | 无变化 |
| **架构原则层** | 状态只能通过 Runtime 变更、Plugin 零 mutation site | 不能动，但要**补齐落地** | **实证发现：这条原则目前在代码里还没有被彻底执行**（见 2.2 和 8 章 Phase 0），需要作为整合的第一步任务，而不是已经具备的前提 |
| **具体实现层** | 内核内部各模块的具体代码 | 开放评审 | **实证发现：CTA 核心引擎（`belief_engine.py`）内部质量相当扎实**——`InferenceEngine.run()` 只产出推断结果、不做状态变更，`BeliefUpdator.apply()` 是唯一的状态变更点，这是一个清晰的"读写分离"设计，说明内核算法层面不需要大动，需要处理的技术债主要在"外部调用是否规范接入内核"这一层 |

### 2.2 一个需要更正的早期判断

> **更正说明**：这一节在 v0.3 版本里曾判断"学生答题主链路绕过 Runtime、直连内核"，后续更细致的代码核实（追踪 `_update_via_plugin_or_legacy` 的完整实现和 `app.py` 的启动流程）发现**这个判断不准确**，特此更正，避免继续误导后续的 Phase 0 排期。

真实情况是：`web/api/belief.py` 的 `submit_answer` 在**生产环境下**并不直接调用 `BeliefEngine.update()`，而是先构造一个 `LearningEvent`、发布到事件总线（`bus.publish("response_submitted", event)`），由 `PluginRuntime._handle_response_submitted` 订阅者接手，内部委托给 `Runtime.update_belief`——`app.py` 启动时会显式激活这个订阅者（注释标注"v0.85.0-d: Production activation"）。也就是说**核心的 belief 更新路径其实已经在走 Runtime，只是通过事件总线间接调用，而不是直接函数调用**，这是一个刻意的解耦设计，不是debt。

只有在**没有订阅者的场景**（比如某些测试环境没有启动 PluginRuntime）时，`bus.publish` 返回 0，才会走"legacy 直连路径"作为向后兼容的 fallback，代码注释里明确写了这是"Plugin SDK 雏形验证期间"的过渡兜底，不是生产环境的常态。

**真正值得关注的是几处更小、更具体的缺口**：`submit_answer` 里除了核心 belief 更新之外，还有几处**确实是直接调用、没有经过 Runtime** 的操作——`engine.l2.register_item(item_params)`（注册题目的 MIRT 参数，直接改 engine 内部状态）、`_get_db().save_student_state(...)`（持久化，可以认为是 Runtime 之外的合理 I/O 操作）、`reconcile_for_student(...)`（A2 误概念 reconcile，直接读写数据库）。这几处是 Phase 0 真正需要逐一评估"要不要也纳入 Runtime 统一入口"的具体对象，范围比之前设想的"整个答题主链路绕过 Runtime"要小得多、也更精确。

### 2.3 三条原则（维持 v0.2 表述）

1. 状态权威原则不能动，且要在 Phase 0 优先补齐（见上）。
2. 验证优先于新功能，不因整合而拖延。
3. 技术栈选择以长期开发效率为准，见第 5 章。

---

## 3. 三源项目功能取舍一览表（结合代码审查更新）

### 来自 ECOS

| 模块 | 处置 | 代码审查备注 |
|---|---|---|
| 状态优先计算理念、双 Agent 互校 | 保留 | |
| 五引擎 + 六对象 | 保留职责划分 | 内核规模：`ecos/` 包 121 个 Python 文件，约 27,600 行；CTA 子模块约 5,600 行、LCA 子模块约 7,200 行；测试 1599 个用例（124 个文件）——规模扎实，不建议大范围重写 |
| Runtime API（8 plan API） | 保留设计 | 见 2.2 更正——核心答题路径实际已通过事件总线正确接入，只有少数几处具体操作（题目参数注册/持久化/误概念 reconcile）需要评估是否也纳入 |
| Plugin SDK | 保留 | `ecos/plugins/base.py` + `registry.py` 共约 670 行，结构清晰 |
| 持久化层 | **确认现状：SQLite**，非未知 | `ecos/persistence/db.py`（1218 行）用原生 `sqlite3` + 手写 SQL DDL，表结构包括 `event_log`/`evidence_log`/`students`/`interventions`/`calibration_log`/`bloom_goals`/`trajectory_snapshots`/`misconception_evidence`/`judge_audit_log` 共 9 张表。表设计本身是合理的关系型建模，**问题在于 SQLite 本身不适合真实多学生并发写入场景**，这是本次审查确认的真实技术债（详见第 5.5 节） |
| Web 层 | **确认现状：Flask** | `web/api/` 共 11 个文件、约 5,453 行代码。**注意：这不是一个"薄路由层"**——`app.py`（1018 行）、`belief.py`（806 行）、`dual_agent.py`（698 行）、`teacher.py`（685 行）都有相当的业务逻辑分量，Flask→FastAPI 迁移的实际工作量比 v0.1/v0.2 预估的"仅路由层、成本很低"更大，需要重新估算（见 8 章 Phase 0） |
| 家长端 | 已有约 785 行实现（`web/parent/` + `web/api/parent.py` + `web/frontend/src/parent/`） | **按你的决定：不受现状约束，可自由重新设计**，现有代码作为参考而非必须保留的基础 |
| CI/质量工具 | GitHub Actions 仅 `workflow_dispatch` 手动触发（非自动） | 这是**有意为之的工程决策**，不是疏漏——注释说明是因为 CI 环境缺真实 LLM/DB，曾多次出现"本地绿/CI 红"的伪错配，改用本地 pre-commit/pre-push git hooks 做实际质量门禁。属于合理权衡，不建议整合时"修正"回自动 CI，除非团队协作模式发生变化 |
| mypy/ruff 配置 | 声明为 dev 依赖，但 `pyproject.toml` 里未见规则配置 | 小缺口，优先级低，Phase 0 可顺手补上 |

### 来自 DeepTutor（借鉴设计，重新实现）

| 模块 | 处置 | 代码审查备注 |
|---|---|---|
| 文档解析引擎 | **借鉴其抽象接口设计**，重新实现一个简化版 | `deeptutor/services/parsing/base.py` 定义了一个 `Parser` Protocol（`resolve_config` / `supported_formats` / `signature` 等方法），`factory.py` 按配置选择具体引擎——是一个干净的策略模式（Strategy Pattern）。实际支持 **6 种引擎**：docling / liteparse / markitdown / mineru / pymupdf4llm / tika，其中 MinerU 明确面向复杂公式/表格场景。**这个"Protocol + Factory"的设计模式值得直接借鉴**，但 6 种引擎的量级对 CogEdu 现阶段不需要——建议按第 7 章的方式，先只接 1-2 个引擎，但接口按同样的 Protocol 风格设计，方便以后要上 MinerU 时直接插拔，不用改调用方代码 |
| L1/L2/L3 记忆分层 | **修正**：ECOS 已有 L1/L3 对应物，只需补中间层 | 见第 16 章——`Evidence` ≈ L1，`CognitiveTwinAgent` ≈ L3，缺的是按知识点归纳且引用具体证据的"L2 摘要层"，不是整套三层架构都要新建 |
| Partners/My Agents/OpenClaw/代码沙箱 | 不引入 | |

### 来自 OpenMAIC（借鉴思路，重新实现为"呈现引擎"）

| 模块 | 处置 | 代码审查备注 |
|---|---|---|
| 动作引擎 | 重新实现最小子集 | `lib/action/engine.ts`（902 行）实际支持的动作类型：`spotlight`/`laser`/`play_video`/`speech`/`discussion`/`widget_highlight`/`widget_setState`/`widget_annotation`/`widget_reveal`，以及一组白板动作 `wb_open`/`wb_draw_text`/`wb_draw_shape`/`wb_draw_chart`/`wb_draw_latex`/`wb_draw_table`/`wb_draw_line`/`wb_draw_code`/`wb_edit_code`/`wb_clear`/`wb_delete`/`wb_close`。**结合数理化场景，Phase 3（白板与语音）的最小必要集可以更精确地定为**：`wb_draw_text` + `wb_draw_shape` + `wb_draw_latex`（公式，数理化刚需）+ `speech`，其余（spotlight/laser/discussion 辩论/widget_* 系列）明确排除在 v1 外 |
| 播放引擎 | 重新实现，可作为直接的设计参考 | `lib/playback/engine.ts`（902 行）是一个单文件状态机，状态包括 `idle`/`playing`/`paused`/`live`，实现规整、没有过度设计，是一个体量适中、值得直接参考结构重写的模块 |
| 白板 UI 组件 | 重新实现 | `components/whiteboard/` 共约 840 行（canvas + history + index），SVG/Canvas 渲染 + 历史记录（撤销/重做），体量可控 |
| mathml2omml | 值得参考的独立小包 | 用于公式格式转换（MathML→OMML，供 Office 文档使用），如果呈现引擎的导出功能要生成含公式的 PPTX/Word，这个转换逻辑可以直接参考甚至直接复用（它是独立的 npm 包，非深度耦合在 OpenMAIC 主体里） |

---

## 4. 系统总体架构

```
┌────────────────────────────────────────────────────────────────────┐
│                        应用层（Web / 移动）                          │
│   学生端 SPA   │   教师端 SPA   │   家长端 SPA（可重新设计）           │
└────────────────────────────────────────────────────────────────────┘
                                  ↕ REST/SSE
┌────────────────────────────────────────────────────────────────────┐
│                    呈现引擎（Presentation Engine，新）                │
│   两阶段生成 + 白板(文字/图形/公式)/语音 + AI同学追问 + 导出            │
└────────────────────────────────────────────────────────────────────┘
                                  ↕ 调用（唯一入口，含学生答题主链路）
┌────────────────────────────────────────────────────────────────────┐
│                  认知运行时（Cognitive Runtime）                     │
│    plan API：estimate / update_belief / replay / evaluate /         │
│    simulate / plan (+domain / human_feedback / action_aware)        │
│    ★ Phase 0 任务：评估并补齐几处具体的直接调用缺口（见 2.2 更正）      │
└────────────────────────────────────────────────────────────────────┘
                                  ↕
┌────────────────────────────────────────────────────────────────────┐
│              认知内核（State-based Cognitive Kernel）                │
│  State ─ Event ─ Policy ─ Evidence ─ Evaluation 五引擎               │
│  内部质量良好（推断/变更分离清晰），核心算法不建议大改                 │
└────────────────────────────────────────────────────────────────────┘
                                  ↕ Plugin 接口（零 mutation site）
┌────────────────────────────────────────────────────────────────────┐
│                      领域层 & 插件                                   │
│  Education Domain（原有）│ 知识库检索 Plugin（新，Protocol+Factory式）│
└────────────────────────────────────────────────────────────────────┘
```

---

## 5. 技术栈决策

### 5.1 认知内核语言：Python（高置信度，维持不变）

### 5.2 呈现引擎后端语言：Python（维持不变，理由同 v0.2）

### 5.3 Web 框架：FastAPI（结论不变，但工作量估计上修）

之前把这个迁移估成"工作量最小、成本很低"，代码审查后发现 `web/api/` 层有实打实的业务逻辑（5453 行），不是薄路由。修正判断：**这仍然是值得做的迁移**（FastAPI 对异步/SSE/类型校验的支持明显更好，长期收益仍然成立），但**工作量应该按"中等改造"而不是"轻量清理"排期**，且应该和 2.2 节说的"补齐 Runtime 接线"合并成一次改造——与其先迁移框架、再补线，不如趁着触碰这些文件的机会一次做完，减少两次回归测试的成本。

### 5.4 前端：React + Vite + TypeScript（结论不变）

### 5.5 数据库：从"待确认"转为已确认需要处理的技术债

**确认现状**：ECOS 用原生 SQLite（`sqlite3` 标准库，无 ORM），9 张表，表设计合理。

**明确建议**：迁移到 PostgreSQL。这不再是 v0.2 里"倾向性建议"，而是审查后更有把握的结论——SQLite 的单写锁机制在"多学生并发答题+多个后台服务读写同一批状态"的场景下会成为瓶颈，且面向 6-12 年长期数据积累的产品定位，迁移宜早不宜晚（越往后数据量越大、迁移成本越高）。现有的表结构可以基本平移，属于"换底座、不用重新设计表"的中等成本迁移，建议和 Phase 0 的其他改造一起做。

### 5.6 技术栈决策速查表（更新置信度）

| 层 | 决策 | 置信度 | 备注 |
|---|---|---|---|
| 认知内核语言 | Python | 高 | |
| 呈现引擎后端语言 | Python | 中 | |
| Web 框架 | FastAPI | 高（结论）/ 工作量中等（原先低估） | 需与 Runtime 接线补齐合并施工 |
| 前端框架 | React + Vite + TS | 高 | |
| 数据库 | **PostgreSQL（确认需要迁移）** | 高 | 现状是 SQLite，已核实 |
| 知识检索引擎接口 | Protocol + Factory 模式（借鉴 DeepTutor） | 高 | 具体引擎选型见第 7 章 |
| LLM 供应商 | MiniMax/Moonshot 为主 | 中 | |
| Agent 编排框架 | 不引入 LangGraph | 中 | |

---

## 6. 核心业务流程（端到端，含 Phase 0 改造后的目标态）

```
1. 学生答题/交互
        ↓（产生 LearningEvent）
2. Event Engine 记录事件
        ↓
3. CTA：Observation → FeatureExtractor → Inference（只读，不改状态）
        → BeliefUpdator（唯一状态变更点）
        ↓
   【Phase 0 后】这一步统一经过 Runtime API，不再有旁路
        ↓
4. LCA：Planner → ExperimentDesigner → Evaluator → PolicyLearner
        ↓
5. 呈现引擎接收 intervention → 两阶段生成 → 场景（文字/图片，后续+白板+语音）
        ↓
6. 学生端播放，产生新的 LearningEvent（回到步骤 1）

（旁路）教师/家长查看 Evidence Engine 输出的证据链（分层可视化，具体设计见第 16 章——补齐 L2 摘要层，而非新建整套三层架构）
```

---

## 7. 教学素材接入设计

### 7.1 现状与约束（不变）

数理化优先，PDF 格式的课本/大纲/讲义，规模不确定，可能需要 LLM 辅助生成配套素材。

### 7.2 解析引擎选型：借鉴 DeepTutor 的 Protocol + Factory 设计（已确认可行）

审查确认 DeepTutor 的 `services/parsing/base.py` 定义了一个干净的 `Parser` Protocol，`factory.py` 按配置动态选择引擎。**建议 CogEdu 采用同样的设计模式**：

```python
class Parser(Protocol):
    name: str
    def supported_formats(self) -> frozenset[str]: ...
    def parse(self, source_path: Path) -> ParsedDocument: ...
    # 可选：is_available() 探测运行环境是否满足（本地模型/远程服务等）
```

**具体引擎选型建议（不照搬 DeepTutor 的 6 种，按需精简）**：
- 起步用一个轻量引擎（比如 pymupdf4llm 同等能力的方案）先跑通规整排版的教材文本+基础公式提取。
- 接口按上面的 Protocol 定义，预留位置——如果轻量方案在数理化公式密度下效果不够，直接加一个 MinerU 实现类插进 factory，调用方代码不用改。
- 不需要一开始就接 6 种引擎、不需要 Tika/Docling 这类偏通用文档处理场景的选项。

### 7.3 知识片段挂靠 Goal Ontology（不变，维持 v0.2 判断）

### 7.4 LLM 自动生成素材的可信度分级（不变，维持 v0.2 判断）

### 7.5 推进方式（不变）：先小范围手动跑通，再评估规模。

---

## 8. 分阶段路线图（结合代码审查与最新决策更新）

### Phase 0：地基评审与清理（范围已修正，比 v0.3 版本更精确）
- **【已更正范围】补齐状态入口的具体缺口**：核心 belief 更新路径其实已经通过事件总线正确接入 Runtime（见第 2.2 节更正），真正需要处理的是三处更小的具体缺口——题目 MIRT 参数注册（`engine.l2.register_item`）、状态持久化（`save_student_state`）、误概念 reconcile（`reconcile_for_student`）——逐一评估是否也该纳入统一入口，而不是"重建整条主链路"
- **Flask → FastAPI 迁移**：与上一条合并施工，按中等工作量排期（不是之前预估的"仅路由层"）。
- **SQLite → PostgreSQL 迁移**：现有 9 张表结构可基本平移，随上面两项一起做。
- 确认迁移后现有测试用例全部通过，作为改动不破坏功能的基线（v0.99.4 基线为 1623 用例 + 4 个 12.2 节新增安全网 = 1627，2026-09-11 已全绿）。
- mypy/ruff 规则配置补齐（顺手做，低成本）。

### Phase 1：呈现引擎最小可用版本（已确认范围不变，工作量分布已明确）
- 两阶段生成（intervention → 大纲 → 场景），场景仅"文字+图片"
- 打通 LCA 输出 → 呈现引擎 → 学生端展示的端到端链路，全程走 Phase 0 改造后的统一 Runtime 入口
- **实证补充**：审查了 OpenMAIC 的生成流水线包（`packages/@openmaic/generation/`，共约 3800 行），确认**第一阶段（大纲生成，`outline-generator.ts`）只有 233 行，相对简单；真正的复杂度集中在第二阶段（场景生成，`scene-generator.ts`，1931 行）**，Phase 1 排期时应该按这个比例分配工作量，不要平均分摊。此外 `outline-generator.ts` 已经原生支持 PDF 文本/图片作为生成输入（`pdfText`/`pdfImages` 参数），这和第 7 章的教学素材接入是天然衔接的——解析出的 PDF 内容不仅能喂给知识检索，也可以直接作为生成大纲时的上下文，两条路径可以共享同一份解析结果。

### Phase 2：家长端重新设计 + 导出能力
- **已确认**：不受现有 785 行家长端代码限制，可自由重新设计功能范围和交互形态
- 导出能力（借鉴 OpenMAIC PPTX/HTML 导出思路，公式导出可参考 mathml2omml）作为家长端的具体功能点一并设计

### Phase 3：白板与语音（范围已精确化）
- 动作集明确为：`wb_draw_text` + `wb_draw_shape` + `wb_draw_latex` + `speech`，直接参考 OpenMAIC playback engine 的状态机结构重写

### Phase 4：证据链可视化增强（可并行，详细任务见第 16 章）
- 补齐 ECOS 现有 Evidence（≈L1）与 CognitiveTwinAgent（≈L3）之间缺失的"L2 摘要层"，而非新建整套三层架构（第 16 章有详细修正说明）

### Phase 5：教学素材接入
- 按 7.2 节，先用轻量解析引擎起步，Protocol+Factory 接口预留 MinerU 升级路径
- 知识片段打标签对齐 Goal Ontology
- LLM 辅助生成素材走可信度分级 + 复核工作流

**明确不做（v1 范围外）**：CogMirror（不纳入本次整合范围）、Partners/IM 集成、多智能体辩论、OpenClaw 生态、十几家供应商适配、LangGraph 引入。

---

## 9. 风险与注意事项

1. **Phase 0 的工作量比之前几版预估的更大**——统一 Runtime 入口 + Flask→FastAPI + SQLite→PostgreSQL 三件事叠在一起，属于一次实打实的架构级改造，不是"清理"量级。建议单独排期评估，不要和 Phase 1 并行启动。

2. **验证主线被稀释的风险依然最高**，且 Phase 0 的技术改造工作量上修后，这个风险更需要警惕——容易以"先把地基打好"为由，把原本该投入验证主线（5-10 学生试点、H1 数据收集）的时间和精力持续后移。

3. **内核内部质量良好这件事，不能成为"整合工作量被低估"的理由**——内核算法本身不需要大改，但"内核之外的接线、框架、存储"这几件事的工作量在这次审查后明显比最初预估更大，两者要分开看待。

   **补充实证**：进一步审查了 LCA 的策略学习模块（`ecos/lca/l4_optimization/pomdp.py` 1139 行 + `pomdp_solver.py` 451 行），确认 PBVI（point-based value iteration）是**真实实现**，不是占位/简化版——α-vector、belief points、backup step 的贝叶斯公式都在代码里，且有清晰的版本演进记录（v0.87→v0.88→v0.89→v0.90 逐步从简化 4x4 转移矩阵升级到依赖型 T/R、再到 PBVI 完整集成），每一步都有"防御性自检 hard block"和"canary 必须 PASS"的回归约束，还能对应到具体的设计文档（`discussions/2026-08-11-v089-design.md`）。**这进一步印证了内核算法层面是整个项目里风险最低、最不需要动的部分**，可以放心地把整合精力集中在接线/框架/存储这几个真正的技术债上。

4. **LLM 生成教学素材的可信度分级仍是硬约束**，不因为解析引擎选型明确了就放松。

5. **家长端重新设计**——现有 785 行代码里可能有一些已经验证过的交互细节或 API 契约（比如 Evidence/Event 的具体展示方式），重新设计时建议先看一眼现状再决定重做多少，避免把已经调对的细节也一起推翻重来。

---

## 10. 待确认/待推进事项

1. ~~项目最终名字~~ ✅ CogEdu
2. ~~Phase 1 最小化范围~~ ✅ 已确认
3. ~~导出能力优先级~~ ✅ 已确认，与家长端并行
4. ~~CogMirror 是否纳入~~ ✅ 已确认：不纳入
5. ~~家长端是否受现状约束~~ ✅ 已确认：不受约束，可自由重新设计
6. **教学素材规模** 仍待 Phase 5 第一步小范围测试后明确
7. ~~Phase 0 三项改造是否合并施工~~ ✅ 已确认：合并（统一 Runtime 入口 + Flask→FastAPI + SQLite→PostgreSQL 一次性完成）
8. ~~审查深度是否足够~~ ✅ 已确认足够，转入详细任务清单阶段（见第 12 章）

---

## 11. 深入代码审查：DeepTutor 与 OpenMAIC 还有哪些功能/思路值得融入 CogEdu

这一章是在前几章"三源项目功能取舍表"（第 3 章）基础上，针对 DeepTutor 和 OpenMAIC 做的第二轮更细的代码走查，挖出几处之前没注意到、但对数理化 K12 场景有直接价值的模块。

### 11.1 来自 DeepTutor 的新发现

**① 可视化能力模块（`deeptutor/visualizers/`）—— 本轮最有价值的发现**

这是一个独立于"呈现引擎叙事讲解"之外的能力：一个可插拔的可视化生成器注册体系（`VisualizerManifest` + 校验器 + 画布），每个可视化类型声明自己适用的 `subjects`（学科）和 `intents`（意图）。已内置的类型里最值得注意的是**支持 GeoGebra**——一个专业的数学动态几何/代数/函数图像工具，此外还支持 SVG、HTML、Chart.js。

**为什么这对 CogEdu 重要**：OpenMAIC 的白板/动作引擎解决的是"AI 老师讲解时怎么画图"，是**讲解型、AI 主导**的呈现；而 DeepTutor 这个可视化模块解决的是"学生可以自己拖动、观察变化的动态图形工具"，是**探索型、学生主导**的交互。这两者在数理化教学里都有刚需，且是互补关系，不是二选一。**建议**：呈现引擎除了叙事场景（Phase 1）和白板讲解（Phase 3）之外，单独规划一个"可视化组件库"能力，接口设计上参考 `VisualizerManifest` 的思路（按学科+教学意图打标签，方便 LCA 检索/选用），优先集成一个 GeoGebra 类工具用于代数/几何/函数图像。

**② 家长/监护人授权模型（`deeptutor/multi_user/guardians.py`）**

一份很干净的"监护人-学生"显式授权记录设计：guardian 和 learner 之间的关系是显式建立的授权记录（而非隐含的角色继承），权限被拆成具体的几项（分配学习材料/管理限制/查看报告/重置凭证）而不是一个笼统的"家长角色"。**这正好是你说"家长端可以重新设计"时最该参考的一份权限设计蓝图**——重新设计家长端时，建议不要做成"家长=只读教师视图"这种简化模型，而是从一开始就按"细粒度、显式关联、可撤销"的方式设计授权。

**③ 生成内容溯源到原文位置的技术（`deeptutor/reading/_grounding.py`）**

一个具体的字符级映射技术：把 AI 生成/引用的内容，精确映射回原始文档的字符位置（哪怕原文经过了空白符归一化处理）。**这把第 7 章一直停留在"分层可追溯"这种抽象层面的设计范式，落到了具体可实现的技术方案上**——Evidence Engine 未来如果要做到"教师点击一条证据，直接跳转高亮到教材 PDF 里的原文位置"，这就是需要的底层技术，而不是只停留在"引用来源标注为教材原文"这种粗粒度。

**④ Book Engine 的区块化生成架构（`deeptutor/book/`）—— 提供了一份现成的"内容类型清单"**

DeepTutor 把生成内容拆成很细的区块类型（`BlockType` 枚举），逐块生成、原子化持久化、流式推送到前端。区块类型清单本身就是一份很好的参考——其中几个和 ECOS 的理念高度契合：
- `RETRIEVAL_PRACTICE`（检索式练习）——呼应学习科学里"测试效应"，和 ECOS 的能力评估直接相关
- `ERROR_DIAGNOSIS`（错因诊断）——本质上就是 ECOS CTA 已经在做的 misconception 检测，只是 DeepTutor 把它做成了一种可以生成呈现的"内容区块"
- `PROGRESS_DASHBOARD`（进度看板）——可以直接对应 ECOS Belief 状态的可视化呈现
- `CONCEPT_GRAPH`（概念图）——数理化知识点关系图谱，可视化 Goal Ontology 的天然形式

**建议**：不需要照搬 DeepTutor 的 15+ 种区块类型，但可以把这份清单当作 CogEdu 呈现引擎"从 Phase 1（文字+图片）逐步往后扩展"时的目标形态参考——尤其是 `ERROR_DIAGNOSIS` 和 `PROGRESS_DASHBOARD` 这两种，因为底层数据（misconception、belief）ECOS 已经有了，只是从来没有被设计成一种"可生成、可呈现给学生/家长的内容单元"，这是一个成本不高但价值明显的新方向。

**⑤ 不建议引入的部分**（这次细看后确认）：`reading/` 模块的双语阅读、词汇、翻译功能明显是面向语言学习场景设计的，和数理化场景不匹配；`video_learning`（YouTube 视频笔记）、`co_writer`（协作写作）场景关联度低，维持第 3 章"不引入"的结论。

### 11.2 来自 OpenMAIC 的新发现

**① 数学文本渲染方案（`lib/quiz/math-text.ts`，基于 KaTeX）**

一段不长但很实用的代码：识别文本里的 `$...$`、`$$...$$`、`\(...\)`、`\[...\]` 这几种数学定界符，用 KaTeX（一个成熟的开源数学渲染库）渲染成网页可显示的公式。**这直接解决了第 7 章一直悬而未决的"网页端怎么显示提取出来的数学公式"这个问题**——不需要自己发明方案，直接用 KaTeX。之前文档提到的 mathml2omml 是另一个场景（生成 Office 文档时公式格式转换），两者不冲突，分别用在"网页实时显示"和"导出 Word/PPT"这两个不同场景。

**② 测验批改的分流逻辑（`lib/quiz/grading.ts`）**

一个轻量的分类规则：按题目的 `type` 字段区分"选择题走精确匹配"还是"开放题走 AI 判分"，逻辑简单但经过了一些边界情况打磨（比如"未作答的选择题不能被误判为走 AI 判分"）。可以直接作为 CogEdu 呈现引擎里"生成练习题→批改→回写 LearningEvent"这条链路中批改环节的参考实现。

**③ 时间常数单一数据源模式（`lib/choreography/timing.ts`）**

一个很小但设计意图很清楚的模块：把"讲解节奏、特效持续时间"这类数值常量抽到一个不依赖任何框架（不依赖 React/DOM）的纯模块里，让"实时播放引擎"和"视频/PPT 导出器"两条完全不同的消费路径共用同一套数字，避免两边各自实现导致"网页上看到的节奏"和"导出的视频节奏"不一致。**这是一个值得直接照搬的小架构模式**，用在 CogEdu 的呈现引擎（Phase 1/3）和导出能力（Phase 2）之间——这两者未来大概率会共享同一份"课堂内容"，靠这种单一数据源可以避免以后出现"网页演示和导出报告对不上"的问题。

**④ 不建议引入的部分**：OpenMAIC 自己的 `lib/rag`（内存词法索引，能力明显弱于 DeepTutor 那套 Protocol+Factory 的多引擎方案，第 7 章已经决定参考 DeepTutor，这里不需要再考虑 OpenMAIC 的版本）；`lib/live` 里课程发布、改名这类教师后台内容管理工作流，和当前 K12 数理化场景的核心诉求关联度低，优先级排在后面。

### 11.3 这一轮新发现对路线图的影响

不改变第 8 章的 Phase 顺序，但建议在以下几个 Phase 里补充具体任务：

| Phase | 新增/细化的任务 |
|---|---|
| Phase 1（呈现引擎最小版） | 数学文本渲染直接采用 KaTeX，不用自己设计方案 |
| Phase 2（家长端重新设计） | 权限模型参考 `guardians.py` 的"细粒度、显式关联、可撤销"设计 |
| Phase 3（白板与语音） | 明确白板讲解（AI 主导）和可视化组件（学生主导探索，如 GeoGebra）是两种互补能力，不要合并成一个需求 |
| Phase 4（证据链可视化） | 落实到具体技术方案：借鉴 `_grounding.py` 的字符级映射，做到"点击证据跳转教材原文位置" |
| Phase 5（教学素材接入） | 无变化，维持第 7 章方案 |
| **新增 Phase 6（远期）** | 可视化组件库（GeoGebra 等探索型工具）+ 区块化内容扩展（`ERROR_DIAGNOSIS`/`PROGRESS_DASHBOARD` 作为可生成呈现的内容单元，直接复用 ECOS 已有的 misconception/belief 数据） |

---

## 12. Phase 0 详细开发任务清单（统一 Runtime 入口 + 框架迁移 + 数据库迁移）

Phase 0 是三件事合并施工：① 补齐状态入口的几处具体缺口（范围已更正，见第 2.2 节，核心路径本身没问题）；② Flask → FastAPI；③ SQLite → PostgreSQL。三者都会touch同一批文件（尤其是 `web/api/belief.py`），合并施工是对的，但需要明确任务顺序和依赖关系，避免三件事互相干扰导致排查问题困难。

### 12.1 任务顺序与依赖关系

```
0-A 建立安全网（必须最先做）
        ↓
0-B 统一状态入口（逻辑改造，风险最高，优先单独做完）
        ↓
0-C Flask → FastAPI（框架迁移，机械改造为主，顺带做）
        ↓
0-D SQLite → PostgreSQL（相对独立，可与 0-C 并行）
        ↓
0-E 回归与灰度
```

理由：0-B（统一入口）是**行为逻辑层面**的改动，最容易引入隐蔽 bug；0-C（框架迁移）大部分是**机械替换**（Flask 路由语法→FastAPI 路由语法），风险相对可控。先把风险最高的逻辑改动做完、测试跑绿，再做机械改造，比两者混在一起改更容易定位问题出在哪一步。

### 12.2 0-A：建立安全网

- [x] 跑通现有全部测试，记录基线：通过数、耗时、是否有 flaky 用例（`python -m pytest tests/ -v --tb=short`）
  - ✅ 2026-09-11 完成：ECOS v0.99.4（commit `9cdacab`）全量 **1623 用例通过，18.92s，零失败零跳过，无 flaky**。内核已复制进 CogEdu（包名 ecos→cogedu，仅 import 重命名），复制后全量测试与基线一致，另新增 4 个安全网测试，**CogEdu 当前 1627 用例全绿**。基线版本从原定的 v0.98.0 改为 v0.99.4（经确认取最新版，增量 7 文件/+159 行已补审，详见 `kernel-baseline-notes.md` 第 1 节）
- [x] 检查 `web/api/belief.py` 当前直连内核的调用路径是否有对应的集成测试覆盖（不只是单元测试内核本身，而是"走 HTTP 请求 → belief.py → 内核 → 返回响应"这条完整链路）。如果集成测试覆盖不足，**先补齐这部分测试**，作为后续两项改造的安全网——这是最容易在迁移中被破坏、又最难靠人工 review 发现的部分
  - ✅ 2026-09-11 完成：评估结论——业务逻辑层覆盖扎实（8 个测试文件直接调用 `submit_answer`，含 `persisted=False` 路径），HTTP 级仅 `test_v0990_signal_collection`（信号采集专项、部分用例 mock 掉了 `submit_answer`）。已补 `tests/test_answer_endpoint_contract.py`（4 用例）：①响应 9 字段契约（含路由层回显的 `reasoning`——函数级返回只有 8 字段，路由层补的第 9 个正是迁移时最容易漏的）②partial credit 派生口径 ③`persisted=true` 正向锚点 ④save 失败必须 `persisted=false` 返回前端 + warning 留痕（v0.47.5 "4 道题没存"事故防线）
- [x] `pyproject.toml` 补齐 mypy/ruff 规则配置（顺手做，成本低）
  - ✅ 2026-09-11 完成：ruff（E/F/W/I/B/UP，line-length 100）+ mypy（lenient 起步，新代码目录后续收紧），见 `pyproject.toml`

### 12.3 0-B：补齐状态入口的具体缺口（范围已更正，比 v0.3 版本小得多）

- [x] **确认理解**：`submit_answer` 的核心 belief 更新（`_update_via_plugin_or_legacy`）在生产环境下已经通过事件总线正确路由到 `PluginRuntime._handle_response_submitted` → `Runtime.update_belief`，这部分**不需要改**，反而应该作为"事件驱动、解耦调用"的参考模式，在新仓库的 FastAPI 实现里原样保留这个设计思路
  - ✅ 2026-09-11 完成：链路已验证——`web/api/belief.py:704` `_update_via_plugin_or_legacy` → `bus.publish("response_submitted")` → `web/api/plugin_runtime.py:190` 订阅者 → `Runtime.update_belief` → `engine.update`。结论成立，不改。
- [x] **逐一评估三处具体缺口**，决定要不要也纳入 Runtime 统一入口：
  - `engine.l2.register_item(item_params)`（注册题目 MIRT 参数，直接改 engine 内部状态）
  - `_get_db().save_student_state(...)`（持久化，可以论证这属于 Runtime 之外合理的 I/O 操作，不一定需要改）
  - `reconcile_for_student(...)`（A2 误概念 reconcile，直接读写数据库）
- [x] 对每一处，判断标准是：这个操作是否构成"改变了学生的认知状态判断"（如果是，应该走 Runtime；如果只是纯粹的 I/O/记录性操作，维持直接调用也可以接受）——不要为了教条式地"全部走 Runtime"而把纯粹的持久化逻辑也强行包一层
  - ✅ 2026-09-11 完成：**三处均维持直接调用，不改代码**。逐处结论：
    - **`register_item` → 维持**。改的是 L2 引擎的题目参数缓存（`item_params[problem_id]`，从 Q 矩阵读的 MIRT 参数，按 problem_id 索引、全学生共享），不触碰任何 `BeliefState` 字段，语义等同于加载 Q 矩阵数据文件，属内容/配置装载。**迁移纪律注记**：它确实影响推断质量（v0.47.4 事故：不注册时 default `[0.8]*5` 等权放大信号，K 暴跌 0.91），0-C 迁 FastAPI 时 `belief.py` 两处调用（DB 恢复路径 + `submit_answer` 路径）绝不能漏——靠 `docs/belief-migration-map.md` 对照表 + HTTP 契约测试防，不靠强行包一层 Runtime 接口（会把"注册题目参数"伪装成"更新认知"，语义更模糊）。
    - **`save_student_state` → 维持**。纯持久化 I/O，序列化已更新完的 state，不改变内存中的认知状态。风险（save 静默失败丢数据）已有正确防线：v0.47.5 后的 `persisted=false` + warning 前端告警，且 12.2 新增的 HTTP 契约测试第 ④ 项锁住了这条路径。
    - **`reconcile_for_student` → 维持，但记录 A2 闭环 tripwire**。写的是 `misconception_evidence` 表的 success/failure 计数；全仓检索确认这些计数和 `quarantined` 状态**今天没有任何消费者进认知内核**——唯一消费方是 `web/api/teacher.py` 的教师展示视图（其 docstring 明确"A2 闭环前不挂 BeliefState，v0.97.2 拍板纪律"），属记录性/可观测性 I/O。**Tripwire**：将来若 A2 闭环——evidence 计数或 `quarantined` 开始参与 misconception 检测/信念更新——该操作即变为状态变更，**必须**改走 Runtime；届时先更新本节，防止后续 Phase 的开发者只看到"这里是直连"就照抄。
- [x] **补一道长期防线**：仿照 ECOS 自己在 Plugin SDK 里"AST 扫描强制零 mutation site"和 POMDP 模块里"防御性自检 hard block"的做法，给"内核状态只能通过 Runtime（或其认可的事件驱动路径）变更"这条规则加一道静态检查，接入 pre-commit/pre-push hook——这一步价值不因为核心路径已经合规而减少，反而更重要：现在的架构是对的，这道检查是用来保证以后新功能开发时不会不小心破坏这个已经做对的设计
  - ✅ 2026-09-11 完成：新建 `githooks/pre-commit`（零 mutation AST 扫描，~1s）+ `githooks/pre-push`（同一扫描 + pytest 全量 ~25s），沿用 ECOS `core.hooksPath` 模式（hook 文件入仓 tracked，克隆后跑 `bash scripts/install-hooks.sh` 启用）。两 hook 已实测通过（扫描 54 文件 + 1627 用例全绿）。**注**：ECOS 的 `check_defensive.sh` 暂未接入——其内部硬编码扫描 `ecos/` 目录（CogEdu 包名已改 `cogedu/`），需先做脚本适配，留待后续按需处理，不在本任务范围。

### 12.4 0-C：Flask → FastAPI

- [x] 建议迁移顺序（从低风险到高风险）：`plugin_runtime.py` → `teacher.py`/`parent.py` → `dual_agent.py` → `app.py`（核心装配）→ `belief.py`（放最后）——**这里不再有"先改造成 Runtime 干净版本再迁移"这层依赖**（因为核心路径本来就是干净的），但 `belief.py` 逻辑最复杂（806 行、大量版本演进注释），仍建议放最后处理
  - ✅ 2026-09-12 完成，按建议顺序分 4 个 commit 递进（每步全绿）：骨架+lifespan 激活 → teacher/parent（9 端点）→ events+dual_agent（5 端点）→ app.py 核心+静态托管（8 API 端点 + 11 静态路由，含 `/api/answer` 主链路放最后）。过渡期 FastAPI 与 Flask 并存，最后一步翻转删除 Flask。`belief.py` 本体未重写（框架无关业务逻辑，只迁了调用它的路由层）；lifespan 启动时 `ensure_started()` 激活 PluginRuntime（对齐 F-14b 口径），`/api/answer` → bus → `PluginRuntime` → `Runtime.update_belief` 事件总线路径有 HTTP 级测试锁定。
- [x] 每个路由文件迁移时，用 FastAPI 的 Pydantic 模型重新定义请求/响应结构，替代原来 Flask 手写的 JSON 解析/校验
  - ✅ 请求侧：`AnswerRequest`/`JudgeRequest`/`InterventionRequest`/`HintRequest` 等。**一处刻意保留手工解析**：`score`/`self_confidence`/`response_time` 用 `Any` 字段而非 `float`——Flask 版的"非数字诚实降级 + warning 留痕"语义（v0.97.2/v0.99.0 拍板）必须保留，Pydantic 422 拒绝整个请求会丢学生答案，比降级更糟（`test_invalid_response_time_defaults_to_zero` 锁定此行为）。
  - ✅ 响应侧：`/api/answer` 的 9 字段契约用 `AnswerResponse`（`response_model` + `exclude_none`，`dual_agent` 字段仅开关开启时出现）在框架层锁定；动态结构（plugin report/POMDP diagnostic）用 `Any` 字段，不强行建模制造虚假精度。
- [x] 规划至少一处 SSE 流式响应的落地（哪怕 Phase 0 阶段还用不上，也要在框架迁移时把这条能力打通，因为 Phase 1 呈现引擎的流式生成马上就要用）
  - ✅ `GET /api/events/stream`（`web/api/routers/stream.py`）：订阅进程内事件总线，LearningEvent 实时转 SSE 推送；线程安全 queue 桥接 sync bus → async 生成器；`max_events`/`idle_timeout` 双终止条件 + 自动 unsubscribe。测试覆盖收事件/不泄漏订阅/空闲超时三态。Phase 1 呈现引擎的流式生成直接复用此模式。
- [x] 迁移完成后跑全部测试 + 手动跑一遍 dual_agent 开关的两条路径（`ECOS_DUAL_AGENT_ENABLED` 相关分支）
  - ✅ 全量 **1640 用例通过**（1627 基线 + 13 新增：8 骨架/SSE + 1 Plugin 路径 `/api/answer` 全链路 + 4 dual_agent HTTP）。开关两条路径由 `tests/test_fastapi_dual_agent.py` 在 HTTP 层自动化锁定（off → `{"enabled": false}` 行为不变 / on → 新生 `has_state: false` / on + 观测后字段完整），函数层 24 用例（`test_dual_agent_integration.py`）迁移零改动。另做了 uvicorn 真实启动冒烟（`python -m web.api.app`：`/api/version` 0.99.4、静态页、OpenAPI 全 200）。

**12.4 迁移过程记录（复盘用）**：布局为 `web/api/app.py`（装配）+ `web/api/routers/`（按域 7 个 router）+ 框架无关业务模块（`belief.py` 等未重写）；`get_llm` 抽到 `web/api/llm.py`、judge 三件套抽到 `web/api/judge.py`（解除业务层对装配模块的反向依赖，测试统一 patch 面）。顺带修复：Flask 版 `/api/version` 与 `/api/report` 的 `import ecos` 重命名漏改（两端点此前恒 500）；两处测试硬编码参考项目绝对路径的硬边界违规（`test_event_stub`/`test_judge_event`）；conftest 隔离加固（PluginRuntime+事件总线无条件重置、`DUAL_AGENT_ENABLED` 每测试归一化，修掉 lifespan 引入的跨测试泄漏）。响应 JSON 形状与 Flask 版逐字段一致，前端零改动。


### 12.5 0-D：SQLite → PostgreSQL

- [x] 依据现有 9 张表（`event_log`/`evidence_log`/`students`/`interventions`/`calibration_log`/`bloom_goals`/`trajectory_snapshots`/`misconception_evidence`/`judge_audit_log`）设计对应的 PostgreSQL schema，注意 SQLite 里可能存在的"用 TEXT 字段存 JSON"的模式，迁移时评估是否改用 `JSONB`（更好的查询能力）
  - ✅ 2026-09-12 完成：`cogedu/persistence/pg_schema.py`，9 张表 + 2 状态表 DDL（AUTOINCREMENT→IDENTITY、REAL→DOUBLE PRECISION、BLOB→BYTEA、主键自增 ID 用 RETURNING 统一取）。**JSONB 评估结论：Phase 0 维持 TEXT**——全仓确认 JSON 列全部整存整取、无 SQL 级查询需求，且 5 个持久化写入口统一传 JSON 字符串（JSONB 会因 text→jsonb 无隐式赋值转换导致全部写失败），跨后端行为一致性优先；无损升级 ALTER 语句已在 pg_schema.py 头部备档。布尔语义列维持 INTEGER 0/1、时间戳维持 TEXT ISO，同理。
- [x] `ecos/persistence/db.py` 目前是原生 `sqlite3` + 手写 SQL，迁移时建议顺带引入一层轻量的数据库适配（比如统一的参数化 SQL 执行封装），不需要上重型 ORM，但要让"换数据库"这件事以后不用再触碰业务逻辑代码
  - ✅ `cogedu/persistence/adapter.py`（~200 行）：占位符翻译（`:name`/`?` → psycopg 格式）、行值归一化（BYTEA memoryview→bytes）、DSN scheme 识别（`ECOS_DB_PATH` 可直接填 `postgres://...` 无缝切库）、executescript 分句、`open_connection` 工厂。业务方法 SQL 全部双后端通用（`RETURNING` 统一取代 `lastrowid`、`INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`、upsert 限定列名——PG 的 `AmbiguousColumn` 教训）。**接入面 = 全部 5 个持久化模块**：db.py Database + DualAgentStore + LCAStore + EventLog.from_sqlite + evidence_engine（比原计划的 db.py 单点多覆盖了 4 个，否则 12.6 灰度必炸）。SQLite 原路径零行为变化（含 Database 专属的 FK pragma 历史语义）。
- [x] 写一个一次性的数据迁移脚本（导出现有 SQLite 数据 → 灌入 PostgreSQL），本地/测试环境先跑一遍验证数据完整性
  - ✅ `scripts/migrate_sqlite_to_pg.py`：FK 依赖序写入、`ON CONFLICT DO NOTHING` 幂等重跑、IDENTITY 序列拨到 max(id)。端到端实测通过：9 张表造数 → 迁移 → 校验（行数逐表核对 / JSON 抽检 / FK 孤儿行 / BYTEA 字节抽检）→ 幂等重跑 → 迁移后继续写入不撞主键。
- [x] 补充 PostgreSQL 连接池、事务边界相关的测试（SQLite 是单文件单写锁，PostgreSQL 引入了新的并发行为，这部分原来的测试可能没覆盖到）
  - ✅ `tests/test_pg_backend.py`（11 用例，无 PG 服务器时 skip）：双后端 CRUD 奇偶校验（同一序列两后端结果一致，时间戳易变字段除外）、事务回滚/提交（SQLite 原语义零回归）、20 线程并发写 + 读写混合并发（PG 共享连接 tx 串行语义，对齐 SQLite 单写者）、psycopg_pool 连接池并发验证、EventLog/双 store/evidence_engine PG 走通。开发机 PostgreSQL 17.11（Homebrew）实测全过。

**环境注记**：PG 连接方式 = `ECOS_DB_PATH` 或 `DatabaseConfig(dsn=...)` 填 `postgres://...` DSN；本地测试库由 fixture 每模块自动创建/删除（admin DSN 可用 `COGEDU_TEST_PG_ADMIN_DSN` 覆盖）。

### 12.6 0-E：回归与灰度

- [x] 全量测试通过
  - ✅ 2026-09-12 完成：全量 **1651 用例通过**（1627 基线 + 13 12.4 新增 + 11 12.5 PG 集成），且每次 push 被 pre-push hook（扫描 + 全量 pytest）强制复验。
- [x] 如果有测试学生/教师账号，先在小范围灰度跑一段时间观察行为一致性，再切换全量
  - ✅ 2026-09-12 完成：真实进程灰度（uvicorn `python -m web.api.app` + PG canary 库），全链路核对通过——答题主链路（9 字段契约 / persisted / theta 演化 0→0.47→0.33 / M8 误概念经 F-10 fallback 触发 / lca_decision passthrough）、真实 LLM judge（判分成功 + reasoning 引用学生原文）、事件落库（hint/reflection → PG event_log）、教师端 7 视图（evidence 链 theta 与 /api/state 一致、校准视图收到自评、misconception_evidence 空符合 A2 未闭环预期）、家长端（含幽灵学生 404）、报告（interpretation 规则引擎）、SSE 真实服务端推流、静态页 no-cache 头、**重启持久化**（theta/theta_cov 真实 SE 恢复、history、answered_ids 记忆防重复出题——v0.47 系列事故场景全数验证）、**dual_agent 开关两路径进程级验证**（OFF → `{"enabled":false}`；ON → 答题响应含 dual_agent 字段 + 互校状态落库 + 抗幻觉 warnings 真实工作）。
  - **灰度发现 1（已修）**：`web/teacher/` 静态页在 12.2 内核复制时遗漏（ECOS 有、CogEdu 没有，`/teacher/` 恒 404，Flask 时代同样）——已按复制自包含原则补入。
  - **灰度发现 2（非缺陷）**：SSE 首测超时为灰度脚本跨进程发布的测试方法错误（事件总线是进程内的，必须在服务进程内 publish），服务端行为本身正确，改用 HTTP 触发服务端发布后验证通过。
- [x] 更新 `CLAUDE.md`/`README.md` 里关于技术栈现状的描述，避免文档和代码再次出现之前发现的那种"README 停留在 v0.96、代码已经到 v0.98"的滞后情况
  - ✅ 制度化：每个任务收尾同步更新 CLAUDE.md 当前状态 / README 当前状态 + 本地运行说明 / CHANGELOG（12.2-12.6 每步都有对应记录），文档滞后问题已在流程上杜绝。

**Phase 0 全部完成（12.2 安全网 → 12.3 状态入口 → 12.4 FastAPI → 12.5 PostgreSQL → 12.6 回归灰度）。** 下一步按方案文档第 13 章细化 Phase 1（呈现引擎最小可用版本）任务清单。

---

Phase 0 做完之后，建议按同样的细化方式处理 Phase 1（呈现引擎最小可用版本），到时候可以直接接着往下推进。

---

## 13. Phase 1 详细开发任务清单（呈现引擎最小可用版本）

范围重申：两阶段生成（intervention → 大纲 → 场景），场景仅"文字 + 图片"，不做白板/语音；全程走 Phase 0 改造后的统一 Runtime 入口。参考对象是 OpenMAIC 的 `packages/@openmaic/generation/`（第一阶段大纲生成简单，233 行；第二阶段场景生成复杂，1931 行——工作量分配要按这个比例，不要平均分摊）。

### 13.1 任务顺序与依赖关系

```
1-A 接口契约设计（先做，其余任务都依赖它）
        ↓
1-B 大纲生成（简单，先打通）
        ↓
1-C 场景生成（复杂，占大头工作量）
        ↓
1-D 生成健壮性（贯穿 1-B/1-C，但建议 1-C 跑通基本流程后再补）
        ↓
1-E 前端渲染
        ↓
1-F 回写事件闭环
        ↓
1-G 端到端验证
```

### 13.2 1-A：接口契约设计

- [x] **1-A-1** 定义 Outline/Scene schema：`cogedu/presentation/types.py`。`Outline` = outline_id + intervention 引用（intervention_id/goal_id/evidence_id，**引用不拷贝**）+ steps 列表；`Scene` = scene_id + outline_id + 同上三个追溯字段 + blocks 列表（Phase 1 仅 `text`/`image` 两种类型）。为 Phase 3 的 `actions` 字段留 schema 扩展点（只留位置，不实现）
  - ✅ 2026-09-12 完成：`GenerationContext`（含 `from_lca_result()` duck-typing 提取——**连 LCAResult 的类型引用都不建立**，防未来顺手调用其内部方法）+ `Outline`/`OutlineStep`/`Scene`（blocks discriminator union，`degraded`/`warnings` 为 1-D-3 预留）。Pydantic 而非 dataclass：schema 同时服务 LLM 输出校验、HTTP 响应模型、落库 payload 三处，且 fastapi 已连带依赖 pydantic
- [x] **1-A-2** 写"呈现引擎 → Runtime 调用映射表"（`docs/presentation-runtime-map.md`，仿 `belief-migration-map.md` 风格）：明确从 `plan()` 返回的 `LCAResult` 里取哪些字段进 LLM prompt（intervention.type/parameters、rationale、bloom_target、clt_level、ca_stage），哪些只记录不进 prompt（expected_gain/expected_risk）
  - ✅ 2026-09-12 完成：进 prompt = intervention_type/target_skills/misconceptions/tcs/difficulty/scaffolding/clt/ca_stage/bloom_target/rationale；**expected_gain/expected_risk 只记录**（LinUCB 内部估计，进 prompt 会诱导 LLM 编造"预期效果"）；goal_id/evidence_id 由 web 调用方显式传入、Phase 1 允许 None
- [x] **1-A-3** 定包边界 + 防线：`cogedu/presentation/` 只读调用 `cogedu.runtime.api`，禁止 import `cogedu.cta/lca/evidence` 内部类——这条规则要和 Phase 0 补的静态检查（12.3 节）覆盖到同一批目录：把 `cogedu/presentation/` 纳入 githooks 零 mutation AST 扫描范围（核对 `scripts/` 扫描器的目录清单）；ruff/mypy 按新代码目录收紧
  - ✅ 2026-09-12 完成：扫描器 glob 加 `cogedu/presentation/**/*.py`（扫描 66 文件通过）；mypy `[[tool.mypy.overrides]]` 对 `cogedu.presentation.*` 启用 strict（顺带修掉 overrides 单表语法错误 + 清理无效配置项 `check_base_classes`）；包边界规则写入 `cogedu/presentation/__init__.py` docstring
- [x] **1-A-4** 定持久化契约：outline/scene 存储与追溯查询形状（按 intervention_id/evidence_id 反查场景），延续 12.5 双后端 adapter 模式。**已决策（2026-09-12）：1-A 即建双后端表**，不先内存后补——追溯字段是第 11 章"错因诊断可视化"的物理前提
  - ✅ 2026-09-12 完成：表结构（`presentation_outlines`/`presentation_scenes`，payload 全文 JSON + 追溯列建索引）与查询形状（`PresentationStore` 六方法，含 `list_scenes_by_evidence` 错因反查）写入 `docs/presentation-runtime-map.md` §4；实现落 1-C-3
- [x] **1-A-5** 定 LLM 依赖注入方式：`presentation/` 是内核子包，**不反向 import `web/api/llm.py`**——engine 构造时注入 LLM client（FastAPI 装配时传 `get_llm()`，测试注入 mock）
  - ✅ 2026-09-12 完成：presentation 侧声明最小 Protocol（`chat_json`），不绑定 `ECOSLLMClient` 具体类型；`chat_json` 已自带 think 块剥离 + 围栏清理 + JSON 解析失败抛 ValueError，1-D 容错层在其之上补合规性修复

> **三个决策点已确认（2026-09-12）**：①图片策略 v1 先静态占位/示意图，接口留出生成/检索位；②Scene/Outline 1-A 即建双后端表；③v1 非流式生成，Phase 3 再上 SSE。

### 13.3 1-B：大纲生成（参考 OpenMAIC outline-generator.ts，233 行体量）

- [x] **1-B-1** 大纲 prompt（`cogedu/presentation/prompts.py`）：输入 = 1-A-2 选定的 LCAResult 字段 + `kb_snippets` 可选参数（Phase 5 前恒空）+ `pdf_text`/`pdf_images` 预留可选参数（照抄 OpenMAIC outline-generator 的思路——它本身就是把 pdfText/pdfImages 作为可选参数，Phase 1 暂时不传）
  - ✅ 2026-09-12 完成：CLT 4 级→铺垫指导、CA 阶段→口吻的映射表内嵌；预留参数传入时生效（有单测锁定）
- [x] **1-B-2** `cogedu/presentation/outline.py` OutlineGenerator：调注入的 LLM client → 解析（先 `json.loads`，1-D 补容错）→ schema 校验（字段缺失/越界的处理策略）→ Outline 对象
  - ✅ 2026-09-12 完成：解析失败原样上抛不吞（重试/降级是 1-D 职责）；结构不合规→`OutlineGenerationError` 含原始输出；step_id 统一重分配（LLM 给的 id 不可信）；`SupportsChatJson` Protocol 注入不绑定具体 client
- [x] **1-B-3** 单元测试（mock LLM）：正常 / 坏 JSON / 缺字段三路
  - ✅ 2026-09-12 完成：`tests/test_presentation_outline.py` 13 用例（含 from_lca_result duck-typing/Enum 转换、prompt 映射表字段进/只记录字段不进、预留参数）
- [x] **1-B-4** HTTP 端点：`web/api/routers/presentation.py` 新 router，`POST /api/presentation/outline` + Pydantic 模型 + HTTP 契约测试
  - ✅ 2026-09-12 完成：`response_model=Outline` 框架层锁契约；错误分级——Runtime 契约不符 500（`RuntimeContractError`，与上游 LLM 失败区分）/ LLM 失败 502 + warning 留痕。`tests/test_presentation_endpoint.py` 5 用例。router 直调 `cogedu.runtime.api.plan`（映射表 §1 唯一入口）。全量 1669 用例通过

### 13.4 1-C：场景生成（参考 OpenMAIC scene-generator.ts，1931 行体量——这是本 Phase 的工作量重心）

- [ ] **1-C-1** 场景 prompt：按大纲单步生成讲解文字，prompt 里明确约束 `$...$`/`$$...$$` 公式格式（交给 1-E KaTeX 渲染）；**单一讲解视角**，多角色讨论/AI 同学插话是 v1 范围外（见第 3/8 章），代码注释里标注
- [ ] **1-C-2** `cogedu/presentation/scene.py` SceneGenerator：每步产出 text block + image block（**已决策：v1 静态占位/示意图，接口留出生成/检索位**）
- [ ] **1-C-3** 追溯关联落地：scene 落库时带 intervention_id/goal_id/evidence_id，双后端实现 + 按 evidence_id 反查的测试（1-A-4 契约的实现）——直接决定后续 Evidence Engine 呈现和第 11 章"错因诊断可视化"能不能做起来
- [ ] **1-C-4** 单元 + HTTP 测试（mock LLM）：场景数与大纲步数一致、公式格式约束命中、追溯字段完整

### 13.5 1-D：生成健壮性（借鉴 OpenMAIC 的 json-repair.ts + generation-retry.ts，1-C 基本流程跑通后补）

- [ ] **1-D-1** 评估 PyPI `json-repair`（license/维护状况），合适直接用，不合适则参考 OpenMAIC `json-repair.ts` 思路用 Python 自写 `cogedu/presentation/json_repair.py`
- [ ] **1-D-2** 重试策略：次数上限/超时/退避，参数进配置，封装在生成入口
- [ ] **1-D-3** 降级行为：重试耗尽 → 模板化 degraded scene，带 `degraded: true` 标记 + **warning 留痕不静默**（对齐 v0.47.5 "宁可明确失败信号也不静默吞异常"的仓库约定），学生端可感知但不空白
- [ ] **1-D-4** 测试：坏 JSON 修复 / 重试耗尽 → 降级标记 + warning 留痕

### 13.6 1-E：前端渲染

- [ ] **1-E-1** 学生端场景页（`web/student/` 扩展）：翻页式交互，按顺序展示 text+image，不需要 Phase 3 的播放状态机（idle/playing/paused/live）
- [ ] **1-E-2** KaTeX 集成（第 11 章的发现，不用自己设计方案）：识别 `$...$`/`$$...$$` 定界符渲染；**内容渲染必须走转义，不裸 innerHTML**——LLM 输出直接进 DOM 是 XSS 面
- [ ] **1-E-3** 图片组件：懒加载 + 加载失败占位
- [ ] **1-E-4** degraded 场景的 UI 提示

### 13.7 1-F：回写事件闭环（这一步是验证"整合真正生效"的关键）

- [ ] **1-F-1** 定义场景行为事件类型（`scene_next`/`scene_dwell`/`scene_question` 之类，对齐现有 LearningEvent 命名约定）
- [ ] **1-F-2** Plugin 形式接入：学生端埋点 + HTTP 端点 → publish 事件 → 事件总线订阅者 → `Runtime.update_belief`（**零 mutation**，复用 12.3 验证过的 `response_submitted` 模式）——走通才算验证"呈现引擎是内核的下游消费方，不是另起一套状态"（第 2 章原则）
- [ ] **1-F-3** 事件落库复用现有 event_log 路径（12.6 灰度已验证 hint/reflection 落库）
- [ ] **1-F-4** HTTP 全链路测试：埋点 → 总线 → belief 变化断言（对齐 12.4 `/api/answer` 全链路测试风格）

### 13.8 1-G：端到端验证

- [ ] **1-G-1** 真实进程端到端 3-5 案例（答错 → CTA → LCA → 大纲 → 场景 → 展示 → 行为回写 → belief 再更新），沿用 12.6 灰度脚本模式 + 真实 LLM；**人工检查内容质量**（讲解对不对、和学生实际薄弱点匹不匹配），不只是"跑通不报错"
- [ ] **1-G-2** 端到端自动化回归纳入 pytest
- [ ] **1-G-3** 收尾：方案文档第 13 章勾选 + CLAUDE.md/README/CHANGELOG 同步 + commit/push

---

Phase 1 做完、验证通过后，可以按同样方式细化 Phase 2（家长端重新设计 + 导出能力）。

---

## 14. Phase 2 详细开发任务清单（家长端重新设计 + 导出能力）

范围重申：不受现有 785 行家长端代码限制，可自由重新设计；导出能力作为家长端的具体功能点一并设计，不是独立旁支。

### 14.1 任务顺序与依赖关系

```
2-A 权限模型设计（先做，是后面所有家长端功能的地基）
        ↓
2-B 功能范围确定（需要你参与决策，不是纯技术任务）
        ↓
2-C 导出能力（技术实现，含公式处理）
        ↓
2-D 前端页面
        ↓
2-E 回归与发布
```

### 14.2 2-A：权限模型设计（借鉴 DeepTutor `guardians.py`，但落地方式不同）

- [ ] 设计 `guardian_learner_link` 关系（不是隐含的角色继承，是显式的授权记录）：谁（家长账号）对谁（学生账号）有什么权限、什么时候建立的、能不能撤销
- [ ] 权限项建议（在 DeepTutor 四项基础上按教育场景调整，`reset_credentials` 这种账户凭证类权限对 K12 场景意义不大，换成更贴近教学场景的项）：
  - `view_progress`（查看学习进度/Belief 概览）
  - `view_evidence`（查看证据链细节，依赖 Phase 4 的可视化增强）
  - `download_report`（下载导出的学习报告）
  - `receive_alerts`（接收异常预警通知，比如同一知识点连续多次出错）
  - `assign_materials`（分配学习材料，可选，视 Phase 5 知识库进度决定要不要在 v1 做）
- [ ] **重要**：既然 Phase 0 已经把数据库迁移到 PostgreSQL，这里不建议像 DeepTutor 那样用 JSON 文件存储授权记录（那是它 MVP 阶段的取舍），直接建关系表，享受关系数据库的完整性约束和查询能力
- [ ] 授权建立流程要考虑：是家长单方面申请就生效，还是需要学生/监护人二次确认？建议至少要有学生本人或系统管理员的确认环节，不能家长单方面绑定学生账号
- [ ] 授权撤销要立即生效（学生撤销后家长端应该马上看不到对应数据，不是等下次登录才刷新）

### 14.3 2-B：功能范围确定（需要你的产品判断，这里先给建议优先级）

| 功能 | 建议优先级 | 依赖 |
|---|---|---|
| 学习进度总览（Belief/Bloom 维度可视化） | **v1 必做** | 无额外依赖，Belief 数据现成 |
| 证据链呈现（点击下钻到具体答题/教材原文） | v1 可做简化版，完整版等 Phase 4 | Phase 4 |
| 学习报告导出（周报/月报） | **v1 必做**（已确认提前） | 14.4 |
| 异常预警通知 | v1 可选，先做规则简单的（比如连续 N 次同一知识点出错） | 无 |
| 分配学习材料 | 建议排到 v2 | Phase 5 知识库 |
| 管理使用限制（时长/难度） | 建议排到 v2 | 无强依赖，但优先级不如前几项 |

- [ ] 需要你确认：v1 的功能范围是否按上表"必做"两项 + 视资源决定的"可选"项来定，还是有别的优先级判断？

### 14.4 2-C：导出能力

- [ ] 导出格式：学习报告优先做 PPTX 和/或 Word（借鉴 OpenMAIC 的导出思路，但用 Python 生态重新实现，比如 `python-pptx`/`python-docx`）
- [ ] **公式导出的处理方式需要决策**：Scene 里的数学公式是 LaTeX 格式文本（第 13 章已定），导出到 PPTX/Word 时有两条路可选：
  1. **渲染成图片嵌入**（简单、可靠，但导出后公式不可编辑）——**建议 v1 先用这个方案**，够用且开发成本低
  2. **转换成原生可编辑公式对象**（参考 OpenMAIC `mathml2omml` 的 LaTeX→MathML→OMML 链路，导出后可在 Word 里编辑公式）——技术上更完整，但需要额外引入转换库和测试，建议排到 v2 视实际需求决定要不要做
- [ ] 报告内容结构：至少包含"本周期学习进度概览 + 关键知识点掌握情况 + 需要关注的薄弱点"，具体版式可以参考 OpenMAIC 导出模板的思路（不照搬代码，因为技术栈不同）

### 14.5 2-D：前端页面

- [ ] 家长账号绑定学生的入口 + 授权管理页（查看/撤销已授予的权限）
- [ ] 学习总览仪表盘（复用学生端已有的 Belief 可视化组件，按家长视角做简化/汇总）
- [ ] 报告下载入口
- [ ] （如果 v1 做证据链简化版）证据链展示页

### 14.6 2-E：回归与发布

- [ ] 测试权限边界情况：学生撤销权限后家长端立即失效、一个学生被多个家长/监护人关联、家长尝试访问未获授权的学生数据应被拒绝
- [ ] 灰度：先找小范围家长用户验证导出报告的可读性和实用性，再全量

---

Phase 2 做完后，按同样方式细化 Phase 3（白板与语音）。

---

## 15. Phase 3 详细开发任务清单（白板与语音）

范围重申：动作集明确为 `wb_draw_text` + `wb_draw_shape` + `wb_draw_latex` + `speech`（第 3/11 章已确认），其余 OpenMAIC 支持的动作类型（spotlight/laser/discussion 辩论/widget_* 系列）明确排除在 v1 外。GeoGebra 类的学生自主探索型可视化工具是另一条能力线（第 11 章新增的 Phase 6），不在本 Phase 范围内，避免混为一谈。

### 15.1 任务顺序与依赖关系

```
3-A 动作模型与协议设计（先做，扩展 Phase 1 的 Scene 对象）
        ↓
3-B 白板渲染组件 ──┐
3-C 播放引擎/状态机 ─┤（可并行）
3-D 语音合成集成  ──┘
        ↓
3-E 时间常数单一数据源（收口，避免三者各自定义时间参数）
        ↓
3-F 生成侧改造（呈现引擎要能产出动作序列，不只是文字+图片）
        ↓
3-G 端到端验证
```

### 15.2 3-A：动作模型与协议设计

- [ ] 在 Phase 1 定义的 `Scene` 对象基础上，新增 `actions` 字段：一个有序的动作序列，每个动作至少包含 `type`（`wb_draw_text`/`wb_draw_shape`/`wb_draw_latex`/`speech` 四选一）、`payload`（具体内容，比如文字内容/图形参数/LaTeX 字符串/语音文本）、时序信息（相对开始时间、预计持续时间）
- [ ] 白板坐标系统设计：参考 OpenMAIC `whiteboard-canvas.tsx` 的思路，确定一套简单够用的坐标/图层模型，不需要 OpenMAIC 全部的复杂度（它要支持十几种动作类型的坐标语义，CogEdu 只需要覆盖文字/图形/公式三种）

### 15.3 3-B：白板渲染组件

- [ ] **渲染技术选型（需要决策）**：SVG 还是 Canvas？SVG 优势是矢量缩放、和 KaTeX 渲染的公式更容易叠加对齐、无障碍访问更好；Canvas 优势是自由绘制/手绘笔触效果更好、性能在复杂图形下更稳。K12 数理化场景以"文字讲解+规整图形+公式"为主，不追求手绘笔触真实感，**建议优先评估 SVG 方案**，但这个决策建议在实际写一个原型对比后再最终确定，不要纯靠讨论拍板
- [ ] 历史记录（撤销/重做）：参考 OpenMAIC `whiteboard-history.tsx` 的设计思路重新实现
- [ ] `wb_draw_latex` 动作的公式渲染**直接复用 Phase 1 已经引入的 KaTeX**，不要在白板组件里单独再实现一套公式渲染逻辑——这是"同一能力只写一次"的具体体现，白板和场景文字共享同一个公式渲染函数

### 15.4 3-C：播放引擎/状态机

- [ ] 参考 OpenMAIC `lib/playback/engine.ts` 的状态机设计（`idle`/`playing`/`paused`/`live` 四态），用 TS 重新实现，规模上参考它的体量（约 900 行），但因为动作类型少很多，实际代码量应该明显小于这个数字
- [ ] 处理动作序列的时序调度：下一个动作什么时候触发（比如"讲完一段话后再开始画下一个图形"），这部分逻辑要和 15.6 的时间常数模块配合

### 15.5 3-D：语音合成集成

- [ ] TTS 供应商选型：不采用 OpenMAIC 的十几家供应商方案，评估 1-2 家中文语音合成服务（可以从现有 LLM 供应商 MiniMax 是否有配套语音能力开始评估，减少新增供应商接入的运维成本），确定后封装成统一接口，方便以后替换
- [ ] 语音生成需要返回时长信息，用于驱动播放引擎的动作时序（比如某段讲解语音生成后有实际的音频时长，后续动作要等这段播完再触发，而不是靠硬编码的估算时长）

### 15.6 3-E：时间常数单一数据源（借鉴 OpenMAIC `choreography/timing.ts` 模式）

- [ ] 把动作持续时间、延迟这类数值常量抽到一个独立、不依赖 React/前端框架的纯模块里，播放引擎和（未来如果做）导出功能共用同一套数字
- [ ] 这一步现在做的直接收益可能不明显（Phase 2 的导出是静态 PPTX/Word，不涉及时长同步），但为未来如果扩展"导出可播放的视频版课堂"预留了正确的架构起点，成本很低、值得现在就做对

### 15.7 3-F：生成侧改造（扩展 Phase 1 的呈现引擎）

- [ ] Phase 1 的场景生成只产出"文字+图片"，这一步要扩展成"文字+图片+动作序列"，Prompt 设计需要让 LLM 输出结构化的动作指令（参考 OpenMAIC `action-parser.ts` 把 LLM 输出解析成具体动作对象的思路）
- [ ] 复用 Phase 1 已经做的 JSON 容错解析/重试机制（第 13.5 节），动作序列本身也是结构化输出，同样会遇到 LLM 输出格式不完全合规的问题

### 15.8 3-G：端到端验证

- [ ] 挑选几个包含数学公式讲解的典型场景（比如"讲解一元二次方程求根公式"），走完整链路：LCA intervention → 生成含动作序列的场景 → 白板渲染+语音播放，人工检查观感是否自然（画图和讲解的节奏是否对得上，公式显示是否清晰）
- [ ] 补充自动化测试：至少验证"动作序列的时序逻辑不出错"（比如不会出现动作乱序、时间重叠导致画面冲突）

---

Phase 3 做完后，按同样方式细化 Phase 4（证据链可视化增强）。

---

## 16. Phase 4 详细开发任务清单（证据链可视化增强）

**范围重新定位（比第 3/8/11 章的描述更精确）**：审查 ECOS 现有代码后发现，"借鉴 DeepTutor L1/L2/L3 分层可追溯设计"这句话需要修正——**ECOS 已经有 L1 和 L3 的对应物**：`Evidence` 统一记录层（`ecos/evidence/evidence.py`，6 种来源统一 schema，支持按学生/来源/知识点查询）相当于 L1（原始事件层）；`CognitiveTwinAgent`（`ecos/cta/cognitive_twin.py`，聚合 belief_state + trajectory + human_feedback + action_history）相当于 L3（跨维度综合画像）。**真正缺的是中间那层**：一个按知识点/能力维度归纳、且显式引用具体 Evidence 记录的"摘要说明层"，以及把这套东西暴露给教师/家长看的可视化界面。Phase 4 应该聚焦在补这个中间层和可视化界面，而不是从零建一套三层架构。

### 16.1 任务顺序与依赖关系

```
4-A 补齐"L2 摘要层"（核心新增）
        ↓
4-B 溯源定位技术占位（为 Phase 5 接教材原文预留）
        ↓
4-C 教师端可视化 API
        ↓
4-D 家长端复用（对接 Phase 2 的证据链呈现需求）
        ↓
4-E 误概念专项视图
        ↓
4-F 验证（结合 ECOS 自身验证主线）
```

### 16.2 4-A：补齐"L2 摘要层"

- [ ] 新增一个摘要生成能力：针对某个 `goal_id`（知识点/能力维度），从 `EvidenceEngine.query_by_goal()` 已经能查到的多条 Evidence 记录，生成一段"当前判断依据"的结构化摘要（比如"最近 5 次相关练习中，正确率从 40% 提升到 75%，但仍有 2 次出现同类型计算错误"）
- [ ] **摘要必须显式列出引用了哪些具体 `evidence_id`**——这是"可追溯"这个词的核心要求，摘要不能是一段模糊的自然语言总结，要能点击摘要里的某个论断、跳转看到具体是哪几条证据支撑的
- [ ] 存储方式：建议做成**按需计算的派生视图**（查询时聚合，可加缓存），而不是像 DeepTutor 那样物理落盘成独立的 L2 文件——ECOS 已经有规范化的关系数据库（Phase 0 迁移到 PostgreSQL 后），没必要引入文件系统式的分层存储，这是 DeepTutor 单机场景的取舍，不适合 CogEdu 现在的架构

### 16.3 4-B：溯源定位技术占位（借鉴 `_grounding.py` 的字符级映射思路）

- [ ] 现在 Evidence 的 payload 大多是结构化数据（答题记录、判分依据），还不涉及"引用教材原文"这种场景（那要等 Phase 5 知识库接入）。这一步**先把字段占位设计好**：如果 Evidence 或摘要未来要引用一段教材原文，需要记录 `source_document_id` + 字符范围（参考 `normalized_with_map` 的思路，做到即使原文经过空白符归一化处理也能精确定位）
- [ ] 具体的映射实现逻辑可以先不写，等 Phase 5 知识库真正有内容可引用时再实现，但字段设计现在做好，避免以后要改 schema

### 16.4 4-C：教师端可视化 API

- [ ] 基于现有 `query_by_goal`/`query_by_student`/`query_by_source` 方法，新增一个面向前端的聚合接口：给定学生+知识点，返回"L2 摘要 + 支撑它的 Evidence 列表 + 每条 Evidence 的可展开详情"
- [ ] 这个 API 走 Phase 0 统一后的 Runtime 入口（新增到 `ecos/runtime/api.py` 或者作为教师端专属的 Runtime 扩展）

### 16.5 4-D：家长端复用

- [ ] Phase 2（14.3 节）里"证据链呈现"这个功能点，v1 简化版可以先直接复用 4-C 的 API，只是前端展示做简化（不需要教师端那么细的每条 Evidence 详情，摘要层的内容对家长可能已经够用）
- [ ] 明确一点：教师端和家长端**共享同一套后端 API**，差异只在前端展示的详略程度，不要做成两套独立实现

### 16.6 4-E：误概念专项视图

- [ ] `ecos/cta/misconception_reconcile.py` 已经在做误概念检测，Evidence Engine 也已经有 `MISCONCEPTION` 这个来源类型可查询。这一步是把这些数据组织成一个专门的"当前活跃误概念列表"视图——呼应第 11 章提到的 DeepTutor `ERROR_DIAGNOSIS` 区块类型思路，但这里更进一步：CogEdu 不是"生成一段错因诊断文字"，而是"把已经结构化存在的误概念证据组织成可视化列表"，数据基础比 DeepTutor 更扎实（DeepTutor 的 ERROR_DIAGNOSIS 是生成式的，CogEdu 这里是基于统计推断的检测结果）

### 16.7 4-F：验证

- [ ] 找几个真实/模拟学生的完整数据案例，从教师视角检查证据链是否真的讲得清楚"系统为什么这么判断这个学生"——**这一步建议直接和 ECOS 自己的验证主线（5-10 学生小规模试点）结合**，不要为了这个 Phase 单独再找一批验证数据，这正好是第 2 章"验证优先于新功能"原则的具体落实：这个 Phase 做的东西本身就是为验证服务的工具，应该反哺主线验证工作，而不是自成一套

---

Phase 4 做完后，按同样方式细化 Phase 5（教学素材接入）。

---

## 17. Phase 5 详细开发任务清单（教学素材接入）

审查 `ecos/goal/goal.py` 和 `ecos/domain/science.py` 后确认了一个需要提前说明的现状：**`Goal`/`Capability` 的字段设计已经就绪**（`Capability(name, description, domain)`、`Goal(goal_id, capability, objective, bloom_level 1-6, metric_dimension, metric_threshold, evidence_ids, status)`，`evidence_ids` 字段现成可以直接复用给 `KnowledgeChunk` 关联），**但现有 `ScienceDomain` 里只注册了三个通用科学方法能力**（`hypothesis`/`experiment`/`analysis`），**不是具体的数理化课纲知识点**。也就是说 Goal Ontology 这套机制是现成的、可以直接用，但内容是空的，Phase 5 要做的第一件实质工作就是把真实教材的知识点注册进去，不是"接入一个已有的数理化知识体系"。

### 17.1 任务顺序与依赖关系

```
5-1 选定试点范围 + 注册 Capability/Goal（先做，是后面所有环节的锚点）
        ↓
5-2 PDF 解析引擎（Protocol + Factory，第 7/11 章已定设计模式）
        ↓
5-3 KnowledgeChunk 数据模型与打标签
        ↓
5-4 检索接口（Plugin 形式接入 LCA）
        ↓
5-5 LLM 生成素材可信度分级与复核工作流
        ↓
5-6 小范围试点验证
```

### 17.2 5-1：选定试点范围 + 注册 Capability/Goal

- [ ] 选 1-2 个数理化章节做试点（比如"一元二次方程"），不要一开始就铺开全学科全学期
- [ ] 把该章节涉及的知识点/能力，按 `Capability(name, description, domain="math")` 的格式逐一注册到 Goal Ontology，每个能力标注合理的 `bloom_level` 预期（比如"求根公式的应用"对应 Bloom L3 Apply）
- [ ] 这一步建议**你和熟悉具体课纲的人**（也可能就是你自己）一起做知识点拆解，这不是纯技术任务，拆得好不好直接决定后面检索/呈现的精确度

### 17.3 5-2：PDF 解析引擎

- [ ] 按第 7.2/11 章确定的 Protocol 设计：
```python
class Parser(Protocol):
    name: str
    def supported_formats(self) -> frozenset[str]: ...
    def parse(self, source_path: Path) -> ParsedDocument: ...
```
- [ ] 先接一个轻量实现（pymupdf4llm 或同等能力方案），跑通规整排版教材的文本+基础公式提取
- [ ] 用试点章节的真实 PDF 教材样本测试，**人工检查公式提取准确率**（这是第 7.2 节强调过的，不能凭经验直接拍板选型）
- [ ] 如果轻量方案在公式密度较高的内容上效果不够，再实现一个 MinerU 的 Parser 子类接入同一个 factory，调用方代码不用改

### 17.4 5-3：KnowledgeChunk 数据模型与打标签

- [ ] 字段设计（在第 4/7 章基础上落到具体 schema）：`chunk_id`、`source_document_id`、字符范围（对接 Phase 4 16.3 节预留的溯源字段占位，这里是真正实现的地方）、`capability`（关联 17.2 节注册的 Capability.name）、`bloom_level`、`embedding`、`credibility_tier`（`official_textbook` / `llm_generated_unreviewed` / `llm_generated_reviewed` 三档）
- [ ] 存储：走第 5.5 节已确认的 PostgreSQL + `pgvector`，不引入独立的向量数据库

### 17.5 5-4：检索接口

- [ ] 以 Plugin 形式接入（只产生 Event，不直接改 Belief，遵守第 2 章"零 mutation site"原则）
- [ ] 提供给 LCA 调用的检索函数：按 `capability` + `bloom_level` 精确匹配 + 语义相似度混合检索（不是纯语义相似度检索，这是第 7.3 节强调过的、比通用 RAG 更贴合 ECOS 架构优势的地方）

### 17.6 5-5：LLM 生成素材可信度分级与复核工作流

- [ ] 落实第 7.4 节的设计：LLM 生成的 `KnowledgeChunk` 默认标记为 `llm_generated_unreviewed`，进入待复核队列，人工确认后才转 `llm_generated_reviewed`，只有这两档之外的 `official_textbook` 默认可被检索使用
- [ ] 生成时优先做检索增强生成（基于已入库的 `official_textbook` 片段做上下文），减少纯自由发挥的生成内容比例

### 17.7 5-6：小范围试点验证

- [ ] 完整跑通链路：解析教材 PDF → 打标签注册 Capability → 检索接口能被 LCA 调用 → 生成的呈现内容（Phase 1/3 的呈现引擎）真的用上了检索到的素材
- [ ] 用试点章节实际花费的人力/时间，倒推如果要覆盖完整数理化课纲，大概需要多少投入——这是回答第 10 章"教学素材规模仍不确定"这个问题的方式：不是先估算，是先做一遍小的，用真实数据倒推

---

到这里，第 8 章列出的 Phase 0-5 已经全部有了详细任务清单（Phase 6 是远期方向，暂不细化）。建议下一步：你可以按这份文档去和实际开发（无论是你自己还是团队）过一遍，如果在实施过程中发现某个 Phase 的判断和实际情况不符，随时可以回来调整对应章节——这份文档本身也应该像 ECOS 自己的 CLAUDE.md 一样，是一个随开发进展持续更新的活文档，而不是一次性写完就不再变的静态说明书。

---

## 18. Phase 6 详细开发任务清单（远期方向：GeoGebra 可视化组件 + 区块化内容扩展）

Phase 6 分两条独立的能力线，可以分开排期，不互相依赖：**A 线**是"学生自主探索型"可视化工具（GeoGebra），**B 线**是呈现引擎产出内容类型的扩展（借鉴 DeepTutor Book Engine 的区块化思路，第 11 章已提过）。

### 18.1 A 线：GeoGebra 可视化组件

审查 `deeptutor/visualizers/builtin.py` 后，GeoGebra 集成的具体机制比第 11 章描述的更清楚了：LLM 被要求输出一段严格 JSON，包含 `app_name`（geometry/graphing/3d 等）、`commands`（一组 GeoGebra 原生命令，如 `A=(0,0)`）、`view`（坐标范围），前端用官方 GeoGebra Applet API 把这些命令"回放"成一个可交互的构造图形。

**这里最有教学价值的一条设计原则**（直接来自 DeepTutor 的 prompt 工程经验，建议原样采纳）：**要求生成的构造是"从独立可拖拽点派生出依赖对象"，而不是一堆写死坐标的静态图形**——这样学生拖动图上的点时，其余依赖对象会跟着联动变化，图形在数学上始终保持一致，这才是 GeoGebra 这类工具真正的教学价值所在（区别于"只是一张会动的图片"）。

#### 任务清单

- [ ] **18.1.1 Visualizer Manifest 协议设计**：借鉴 `VisualizerManifest` 的字段设计（`id`/`subjects`/`intents`/`render_target`/`payload_format`/`prompt`/`priority` 等），用 Pydantic 定义 CogEdu 自己的版本，不需要照搬全部字段，但 `subjects`（学科标签）和 `intents`（教学意图，如 construct/explore/prove/graph）这两个字段要保留——它们是后面 18.1.5 挂钩 Goal Ontology 的关键
- [ ] **18.1.2 GeoGebra 前端集成**：引入 GeoGebra 官方 JS Applet API，封装一个 React 组件，接收 `commands` + `view` 参数完成渲染，支持基本的重置/导出图片交互
- [ ] **18.1.3 Prompt 工程**：直接借鉴 DeepTutor 已经打磨过的 GeoGebra prompt 设计思路（"依赖对象从独立可拖拽点构建，保持数学意义""视图边界要包含整个构造并留出边距""颜色用整数 RGB 不用 CSS/hex"这类具体、经过实践检验的约束），按 CogEdu 实际学科范围（K12 数理，暂不需要 DeepTutor 覆盖的大学向量/微积分等高阶内容）做裁剪
- [ ] **18.1.4 Payload 校验器**：照搬 `_geogebra_validator` 的校验逻辑思路——严格 JSON 格式、命令数量下限（至少 2 条，保证不是空构造）和上限（最多 100 条，防止生成失控）、`app_name` 必须是支持的类型、`view` 四个坐标边界必须都存在且 `x_min < x_max`、`y_min < y_max`
- [ ] **18.1.5 与 Goal Ontology 挂钩**：`subjects`/`intents` 标签要能映射到 CogEdu 自己的 `Capability`/`bloom_level` 体系，这样 LCA 才知道"这个知识点、这个 Bloom 层级，适合用 GeoGebra 探索还是用白板讲解"——这条决策逻辑本身也是一个需要设计的小模块，不是自动就有的
- [ ] **18.1.6（可选，评估后再定）**：DeepTutor 还有一个 `manim_image`（服务端渲染 Manim 数学动画分镜图，静态图片输出）选项，和 GeoGebra 是不同定位（一个是可交互构造，一个是渲染好的动画分镜）。这个需要额外的服务端渲染算力，建议先不做，等 A 线其余部分跑通、看实际教学效果和资源情况再评估要不要加

### 18.2 B 线：区块化内容扩展（呼应第 11 章 DeepTutor Book Engine 的区块清单）

在 Phase 1（文字+图片）和 Phase 3（白板动作）已有的内容类型基础上，扩展呈现引擎能产出的内容类型。**这次审查发现两种区块的底层数据现成、可以优先做；一种区块需要新的建模工作，成本明显更高——三者不要同等对待。**

#### 任务清单

- [ ] **18.2.1 `ERROR_DIAGNOSIS`（错因诊断区块）—— 优先，数据现成**：直接复用 Phase 4（16.6 节）已经做好的"误概念专项视图"数据，包一层"可以嵌入呈现引擎输出流"的展示格式，从"教师查询界面"升级为"可以直接生成给学生/家长看的一段内容"
- [ ] **18.2.2 `PROGRESS_DASHBOARD`（进度看板区块）—— 优先，数据现成**：复用 Belief 状态的可视化组件（学生端/教师端已有），包装成呈现引擎输出流里的一种区块类型，可以嵌在课堂场景的开头/结尾展示
- [ ] **18.2.3 `RETRIEVAL_PRACTICE`（检索式练习区块）—— 中等优先，依赖 Phase 5**：基于 Phase 5 接入的知识库和现有能力评估数据，生成"检索式练习"（呼应学习科学的测试效应，即"回忆"本身就有助于巩固记忆），这个依赖 Phase 5 的知识检索能力已经就绪
- [ ] **18.2.4 `CONCEPT_GRAPH`（知识点概念图）—— 成本明显更高，需要新建模，不要低估**：**审查确认 ECOS 现有的 `Capability`/`Goal` 之间目前没有任何先修/依赖关系建模**（不像 `evidence_ids` 那样有现成字段可以直接用）。要做概念图，第一步不是可视化组件开发，而是先设计一套"知识点之间先修关系"的数据模型并把它填充进去——这本身是一项独立的、有一定工作量的知识工程任务，建议单独评估是否值得投入，或者是否可以先用一个简化版（比如按章节顺序线性排列，不做真正的图结构）过渡

### 18.3 排期建议

不建议 A 线和 B 线同时启动。**建议顺序**：先做 B 线里的 18.2.1/18.2.2（数据现成、成本低、直接复用 Phase 4 的成果），验证"区块化呈现"这个形式本身是否受学生/教师/家长欢迎，再决定要不要投入成本更高的 A 线（GeoGebra，涉及新的前端集成和 prompt 工程）和 18.2.4（概念图，涉及新的知识建模）。这也符合第 2 章"验证优先"的一贯原则——Phase 6 本身已经是远期方向，更没有理由在没验证过用户是否需要之前，就一次性把所有子项都做完。

---

到这里，Phase 0-6 都已经有了详细任务清单，这份技术方案文档已经从最初的"要不要整合"讨论，走到了可以直接指导开发排期的程度。后续如果在实际开发中发现某些判断需要调整，建议随时回来更新对应章节，保持这份文档和实际进展同步。
