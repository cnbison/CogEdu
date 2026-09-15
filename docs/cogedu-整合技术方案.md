# 教育认知操作系统整合方案（CogEdu）

> 版本：v0.6 draft　|　日期：2026-09-12　|　基础项目：ECOS（核心） + DeepTutor（记忆/知识借鉴） + OpenMAIC（呈现层借鉴）
>
> **v0.6 相对 v0.5 的主要变化**：Phase 3（白板与语音）任务清单细化（第 15 章）——动笔前对 OpenMAIC 参考实现与 CogEdu 现状做了双份代码勘察，**修正两处凭印象的表述**（白板渲染并非"SVG vs Canvas"二选一，OpenMAIC 实际是 DOM+SVG path；播放调度不消费音频时长，靠 ended 事件驱动）；四项决策落档（渲染路线 DOM+SVG、增补 `wb_draw_line`、砍撤销/重做换"重播本页"、TTS 异步补齐+播放端降级）。
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
| 动作引擎 | 重新实现最小子集 | `lib/action/engine.ts`（902 行）实际支持的动作类型：`spotlight`/`laser`/`play_video`/`speech`/`discussion`/`widget_highlight`/`widget_setState`/`widget_annotation`/`widget_reveal`，以及一组白板动作 `wb_open`/`wb_draw_text`/`wb_draw_shape`/`wb_draw_chart`/`wb_draw_latex`/`wb_draw_table`/`wb_draw_line`/`wb_draw_code`/`wb_edit_code`/`wb_clear`/`wb_delete`/`wb_close`。**结合数理化场景，Phase 3（白板与语音）的最小必要集可以更精确地定为**：`wb_draw_text` + `wb_draw_shape` + `wb_draw_latex`（公式，数理化刚需）+ `speech`，其余（spotlight/laser/discussion 辩论/widget_* 系列）明确排除在 v1 外（**v0.6 修订**：Phase 3 细化时增补 `wb_draw_line`，见第 15 章） |
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
- **任务清单已细化（2026-09-12，见第 14 章）**：细化时发现仓库完全没有账号体系 → 新增 **2-0 最小账号体系** 作为地基；v1 = 学习进度总览 + Word 报告导出（公式渲染图片嵌入），预警/证据链简化版视资源可选；PPTX 与 mathml2omml 可编辑公式排 v2
- **2-0 已完成（2026-09-12）**：users/sessions 双后端表 + bcrypt + 服务端会话（撤销立即生效）；全量路由角色矩阵接线；前端登录页/守卫/回写带身份；canary 走真实登录。遗留：parent per-student 关系校验随 2-A 落地。全量 1765 用例通过
- **Phase 2 收官（2026-09-12）**：2-A 权限模型（guardian_learner_link 显式授权 + guardian_can_access 单一入口）→ 2-C Word 报告导出（mathtext 公式图片嵌入，spike 88%）→ 2-D 家长端/学生确认页 → 2-E 灰度 14 步通过。全量 1804 用例通过；待小范围真实家长用户验证后全量发布

### Phase 3：白板与语音（范围已精确化）
- 动作集明确为：`wb_draw_text` + `wb_draw_shape` + `wb_draw_latex` + `speech`（v0.6 增补 `wb_draw_line`，见第 15 章），直接参考 OpenMAIC playback engine 的状态机结构重写

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
9. **UI 现代化立项**（2026-09-14 确认）：ECOS v0.99.5 已有现成 React 18 + Vite + TS 前端工程（`ecos/web/frontend/`，echarts/react-query/router，student/parent 页面齐全，src 约 248K），CogEdu 学生端/家长端目前仍是 ECOS 早期静态页。**已拍板：不阻塞 Phase 3 验收发布**，UI 移植单独立项——范围 = 复制 ECOS 前端工程并适配（CogEdu 自建认证体系对接、API 差异审计、Phase 3 白板/播放 vanilla JS 模块 React 化整合），**建议与 Phase 4 证据链可视化合并考虑**（React + echarts 正是可视化需要的栈）。当前静态页此前暴露的三个前端缺陷（sid 解析/API base 写死/api 助手无凭证）已修复并 grep 契约锁定，移植时以契约测试为验收底线。**细化已落档（2026-09-14 勘察）**：三份清单（页面/组件结构盘点、API 差异清单、Phase 3 模块整合方案）+ 施工任务拆分见 §10.1，待维护者确认后施工。
10. **讲解生成等待体验**（2026-09-14 立项，Phase 3 验收暴露；**同日 ①② 已落地**）：原状为生成全程 10~25 分钟黑盒等待——串行逐场景生成 + 个别场景吃满超时重试，且全部场景生成完才一次性落库/返回。**已完成**：① 逐场景落库（`generate_for_outline` 加 `on_scene` 回调）+ POST /scenes 非阻塞化（202 + 后台 daemon 线程，进程内防重入注册表）+ `GET /scenes/{id}/status` 进度端点（generated/total/status 三态：ready/generating/not_started 可幂等重触发）+ 前端轮询显示"n / m"进度；② 生成结果服务端复用（同大纲已有落库场景 → POST 直接 200 ready 返回，幂等不重复生成计费）。**剩余**：③ 重试/超时策略按耗时数据收紧；渐进显示目前是进度文字，逐场景边生成边渲染的完整形态留给 UI 现代化（#9）一并做。灰度脚本（1/3 两代）已同步接入轮询助手 `_wait_scenes`。

### 10.1 UI 现代化（#9）细化落档（2026-09-14 勘察，待维护者确认后施工）

**勘察范围**：ECOS 参考工程 `../ecos/web/frontend/`（只读，React 18.3 + Vite 6 + TS 5.6，src 约 248K）+ CogEdu `web/` 层现状逐文件核对。本节是施工依据，**四项决策已于 2026-09-14 拍板（10.1.7），施工开始**。**总体结论：API 差异比预估小**——ECOS 前端调用的 17 个端点中，教师端 7 条与 CogEdu `/api/teacher` **同名同义 1:1 对齐**，学生端 8 条 CogEdu 也全部同名存在；真正要新写的是认证层、presentation 全新域、parent 权限扩展三块。

#### 10.1.1 清单 a：ECOS 前端页面/组件/路由结构盘点

**工程形态**：三入口多页 SPA（`index.html`=教师端 / `student.html` / `parent.html`），各自独立 `main.tsx` + **HashRouter** + QueryClientProvider（staleTime 15s、refetchOnWindowFocus off）。无 axios、无 zustand/redux、无 Tailwind、无 UI 组件库；纯 fetch 封装；echarts 5.5 唯一封装在 `components/EChart.tsx`（init/resize/dispose + setOption）。

**路由表**：

| 入口 | 路由 | 页面 |
|---|---|---|
| 教师端 index.html | `/`；`/students/:id` | RosterPage（桌面表格/移动卡片双形态）；StudentDetailPage（474 行，内含 5D radar / EvidenceChain 下钻 / CalibrationView / POMDP 诊断 / MisconceptionsCard 子组件） |
| 学生端 student.html | `/`（今天）、`/answer`、`/where`、`/growth`、`/report`、`/settings`；登录门 = 无 sid 时条件渲染 LoginPage（无 /login 路由） | 三卡首页+MotivationPanel；答题主流程（CodeMirror 编辑器、自评 4 档、AI 判分、反思、LCA 决策只读、idle 计时）；5D+Bloom 视图；成长折线；报告+打印；设置 |
| 家长端 parent.html | **无 `<Routes>`**——单页 ParentHomePage，"列表/详情"两态靠 URL query `?student=<id>` 切换 | 四卡：Engagement / Advice（severity 三色）/ FiveDOverview / InterventionHistory |

**组件分组**：`components/`（EChart + `ui/` 原子件：Icon/icons/iconMap/ClickableRow/CollapsibleSection/EmptyState/SectionHeader/uiHelpers/useMediaQuery，跨三端共享）｜`student/`（CodeEditor、MotivationPanel、7 页面）｜`parent/`（Cards 四卡、ui.ts 徽标映射、urlState.ts 纯函数）｜`pages/`（教师端 2 页）。

**状态管理**：无全局 store；react-query queryKey 扁平二元组 `[资源名, sid]`，缓存失效靠手动 `refetch()`（无 invalidateQueries、无轮询）。**样式**：原生全局 CSS + `:root` 主题变量（`index.css`），学生端 787 行专属 CSS 含 `@media print`（`window.print()` 出 PDF）。

**移植注意点**（勘察实录）：① 响应字段类型与后端契约逐字段硬对齐（家长端 InterventionItem 曾因字段名错配显示错位，ECOS 留有注释），移植保留宽类型 + `[key: string]: unknown` 逐步收紧；② 同一端点多形状隐式契约要处理（`/api/report` interpretation 失败降级 `{error}`、`/api/question` 完成态 `{done:true}`、`/api/judge` `judged:false`）；③ ECOS **无认证**——sid 纯前端 localStorage 手输、fetch 无 Authorization 头、完全不处理 401；④ 写路径两步（先 judge 后 answer，answer body 11 字段含 `self_confidence` 四档语义值）。

#### 10.1.2 清单 b：API 调用层与 CogEdu 端点差异清单

| # | 差异点 | ECOS 前端现状 | CogEdu 现状 | 移植动作 |
|---|---|---|---|---|
| 1 | **认证** | 无认证：fetch 只带 Accept/Content-Type，无 401 处理 | Bearer + 服务端会话（token `localStorage["cogedu_token"]`，401 → 清 token 跳 `/login?next=`），语义被 `test_auth_api.py` 锁定 | 三份 client 的 getJson/postJson 统一加 `Authorization: Bearer` 头 + 401 拦截，行为对齐现有 `web/auth.js` authFetch（服务端会话可撤销，不能换 JWT） |
| 2 | **student_id 来源** | 用户手输/最近列表选择，存 localStorage | 登录身份：student 角色绑定 `learning_student_id`（`/api/auth/me` 返回） | 登录门改为真登录：POST `/api/auth/login` → `me` 取 `learning_student_id`；删除手输 sid 逻辑（呼应 3-F-5 修复的语义） |
| 3 | 学生端 8 端点 | `/api/state|report|question|judge|answer|history|event/{hint,idle,goal_change,reflection}|students/recent` | **全部同名存在** | 字段级对齐：`/api/answer` 响应为 9 字段契约（`AnswerResponse` + exclude_none，`persisted=false` 要告警）；`/api/judge` 失败 **422** `{judged:false, error_code:"LLM_JUDGE_FAILED", needs_rejudge:true}`（ECOS 是 200 内 judged:false）；`/api/question` 附加 `lca_decision/is_probe/is_warmup/strategy` 字段（超集，前端按需取） |
| 4 | **presentation 域**（全新） | 无 | 8 端点，router 级 `require_student_access`：POST `/api/presentation/outline`；POST `/scenes`（**非阻塞**：已有落库→200 ready 复用，否则 202 generating）；GET `/scenes/{id}/status`（generated/total/status ∈ ready/generating/not_started，not_started 幂等重触发）；GET `/outline/{id}`、GET `/scenes/{id}`（复看只读）；POST `/event`（scene_viewed/scene_completed）；GET `/audio/{id}`；GET `/timing` | 新增 presentation client：202 轮询协议（3s 间隔、重触发上限 2 次）+ 复看模式 + blob 音频缓存照 scene.js 现逻辑平移；**GET 一律带 `?student_id=` 查询串**（dependency 放行靠它），POST 带 body `student_id` |
| 5 | **parent 域扩展** | 2 端点（students / overview） | 3 端点 + guardian-links 7 端点：overview/report 均按 per-student `guardian_can_access` 校验（无 `view_progress`/`download_report` 授权 403）；授权是 pending→active 状态机、**学生本人确认制** | 加 report 下载（docx，`?period=`）；新增授权管理视图（家长侧申请/撤回/撤销 + 错误语义 400/404/409）；学生 SPA 加确认页路由（对应现 `guardian-links.html`） |
| 6 | 教师端 | 7 GET 端点 | **同名 7 端点已存在**（`require_roles("teacher","admin")`），CogEdu 教师页目前只是占位骨架 | 近乎直移 + Bearer 头；这是移植工作量最小、最先打通全链路的一块 |
| 7 | SSE | 无 | GET `/api/events/stream`（进程内事件总线订阅） | **本期不接**，留给 Phase 4 可视化决策 |
| 8 | API base / CORS | 相对路径 `/api` + vite dev proxy | 同源相对路径（无 CORS 中间件，5173 同端口托管）；grep 锁禁止 JS 出现 `localhost:5173` | 沿用相对 `/api` + dev proxy；不引入绝对 origin |
| 9 | 枚举/值域耦合 | Bloom 枚举名与 L1..L6 两种形状混用；θ 值域 ±2.5；POMDP 英文枚举→中文徽标 | 复用同一内核，契约一致 | 保留 ECOS 映射表原样平移即可 |

#### 10.1.3 清单 c：Phase 3 白板/播放模块 React 整合方案（挂载式宿主，2026-09-14 拍板）

**原则：React 只做宿主，三个 vanilla 模块原样保留**——保住已人工验收的播放行为、tests/js 24 个 node:test 用例（依赖 `module.exports` CommonJS 导出）与 `test_presentation_timing.py` 的数值镜像锁。

- **保留不动**：`web/student/{playback,whiteboard,formula}.js` 三个文件（`window.CogEduXxx` 全局 + `module.exports` 双通道是 node:test `require` 的前提，也是代数令牌/时序语义已验收的载体）。
- **加载**：React 入口 html 以 `<script defer>` 按现有顺序引入三模块（formula → playback → whiteboard），与 scene.html 行为等价；不引 npm katex，继续用本地 vendor `/vendor/katex/`（避免双份实现 + `TestKaTeXLocalVendor` 锁冲突）。
- **宿主组件 ScenePlayer**：`useEffect` 内 `createWhiteboard(containerRef.current, {timing})` + `createPlaybackEngine({actions, renderer: wb.renderer, speechPlayer, scheduler, now, timing, onStateChange, onDone})`；speechPlayer（blob 缓存 + ended 驱动 + 估算兜底）从 scene.js 平移成可注入对象，不改 playback.js；组件卸载必调 `engine.stop()`（代数令牌使旧异步回调失效的语义保留）；翻页/复看切换即 stop + 重建。
- **timing 下发**：GET `/api/presentation/timing` → 同时注入 engine timing 与 renderer timing；playback.js/whiteboard.js 内的兜底镜像常量**一个字不动**（数值锁）。
- **复看模式**：`scene.html?outline_id=` 改为 HashRouter 路由参数（如 `/scene/:outlineId`），走两个只读 GET，不触发生成。
- **安全约定延续**：LLM 文本一律 textContent、innerHTML 仅限 KaTeX 渲染产物——现有 grep 锁改指向宿主组件后同样执行。
- **渐进生成形态**（§10 #10 剩余项）：React 版在轮询 status 时按 `generated` 计数逐场景渲染（场景数据逐个 GET），宿主组件天然适合做，作为 9-D 任务的一部分收掉 #10 的尾巴。

#### 10.1.4 托管与构建衔接（勘察确认：无需改 app.py）

- `web/api/routers/static_pages.py:29` 已预留 `DIST_DIR = web/frontend/dist`，dist 优先、legacy 静态页兜底；入口名约定 `index.html`（教师）/`student.html`/`parent.html` 与 ECOS vite `rollupOptions.input` **天然一致**。
- HashRouter 与 static_pages 的逐文件映射（无 history-fallback）兼容，深链接不碎。
- `.gitignore` 全局忽略 `dist/`——React 构建产物是否入库**待拍板**（见 10.1.7）。
- 开发模式：vite dev proxy `/api → 127.0.0.1:5173`。

#### 10.1.5 契约测试迁移策略（待拍板，移植最大约束面）

约 30+ 条 grep 契约断言指向 `web/student/` 旧文件（`test_whiteboard_wiring.py` 9 例、`test_auth_api.py` 前端接线段、`test_frontend_event_wiring.py`、`test_presentation_events.py`/`test_presentation_timing.py` 的 JS 段）。**推荐：双轨过渡**——React 端某端点验收通过切 dist 后，同步把对应 grep 锁改指向 React 工程源文件（**锁语义不变**：authFetch/Bearer/无写死主机名/textContent 安全/时序镜像/script 顺序），legacy 页保留兜底；全端点切换完成后再删 legacy 页与其专属锁。node:test（tests/js/*.test.cjs）因模块保留而**原样全绿**，不动。

#### 10.1.6 施工任务拆分（参照 Phase 2/3 模式：每任务完成即更新四文档 + commit + push）

- **9-A 工程骨架落地**：✅（2026-09-14 完成）复制 ECOS 工程配置（package.json/vite.config/tsconfig/eslint）到 `web/frontend/`，三入口保留，业务代码先清空保 `build`/`typecheck`/`lint` 绿；提交注明来源 ECOS v0.99.5（只读复制，自包含维护）。**验证**：`npm run build|lint|typecheck` 全绿，TestClient 实测 `/`、`/student/`、`/parent/`、`/teacher/` 四入口均由 dist 接管（static_pages dist 优先逻辑自动生效，app.py 零改动）。
- **9-B 认证与 API 基座**：✅（2026-09-15 完成）`src/shared/auth.ts`（authFetch Bearer + 401 清会话跳 `/login?next=`（hash 回跳）+ login/logout/fetchSession + localStorage 键与 legacy web/auth.js 互操作）+ `session.ts` useSession（服务端权威校验）+ `RequireSession.tsx` 守卫（角色矩阵）+ 三端 main 接 QueryClientProvider + HashRouter；vitest 8 用例锁基座语义。**验证**：真实进程冒烟（建号→login→me→403 矩阵→401→撤销立即失效）全通。
- **9-C 教师端移植**：✅（2026-09-15 完成）RosterPage/StudentDetailPage + EChart/ui 组件（Icon/EmptyState/CollapsibleSection/SectionHeader/ClickableRow/useMediaQuery/uiHelpers）+ api client/types 自 ECOS v0.99.5 前端复制，路由 `/`→roster、`/students/:id`→详情；getJson 换共享 Bearer 基座，响应类型与 CogEdu teacher.py 逐字段核对一致。vitest 31 用例全绿（含 ECOS 原有端点契约/组件测试）；TestClient 冒烟 7 端点（教师 token，空库 404/200 形态符合契约）。
- **9-D 学生端移植 + presentation 集成**：答题主流程字段对齐 + ScenePlayer 宿主 + 202 轮询/复看/音频/时序 + 逐场景渐进渲染（收 §10 #10 尾巴）。
- **9-E 家长端移植**：roster/overview/report 下载 + guardian 授权管理 + 学生端确认页路由。
- **9-F 契约测试迁移**：按 10.1.5 双轨策略改锁 + node:test 回归 + legacy 兜底验证。
- **9-G 灰度验证与收官**：真实进程人工验收（教师/学生/家长/场景/授权五页）+ 四文档收官 + 全量发布。

**与 Phase 4 的边界**：#9 不做证据链新视图（4-C/4-D 的前端部分），但保留 `EChart.tsx` 封装与 react-query 基座供 Phase 4 直接复用；Phase 4 细化可与 9-C..9-E 并行推进。

#### 10.1.7 决策拍板（2026-09-14 维护者确认，按 10.1.6 开工）

1. **契约测试迁移策略**：✅ **双轨过渡**（10.1.5）——React 端点验收切 dist 后逐条改锁，legacy 页保留兜底，全切换后删除。
2. **React dist 产物**：✅ **不入库**——发布/部署时构建；`.gitignore` 维持全局忽略 `dist/`。
3. **login 页**：✅ **保留 `web/login.html` 原样**——三端共用服务端渲染页，本期不 React 化。
4. **SSE**：✅ **本期不接**——留给 Phase 4 可视化决策，本期用 react-query refetch。

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

- [x] **1-C-1** 场景 prompt：按大纲单步生成讲解文字，prompt 里明确约束 `$...$`/`$$...$$` 公式格式（交给 1-E KaTeX 渲染）；**单一讲解视角**，多角色讨论/AI 同学插话是 v1 范围外（见第 3/8 章），代码注释里标注
  - ✅ 2026-09-12 完成：`build_scene_messages`（prompts.py）——公式定界符约束 + 单一视角禁令都在 prompt 里（有单测锁定命中）；输出 JSON 含 `image_concept` 配图意图字段
- [x] **1-C-2** `cogedu/presentation/scene.py` SceneGenerator：每步产出 text block + image block（**已决策：v1 静态占位/示意图，接口留出生成/检索位**）
  - ✅ 2026-09-12 完成：每场景恒为 `[text, image]` 两 block；占位图 `placeholder=True` + `image_concept` 进 alt；`image_provider` 注入点（注入即替换占位图，有单测锁定）。`generate_one` 是 1-D 重试/降级复用的最小单元。**顺带**：`Outline.context` 字段（生成上下文随大纲落库，第二阶段从持久化层恢复后重建 prompt——不存的话 difficulty/clt_level 等 pedagogy 字段会丢）
- [x] **1-C-3** 追溯关联落地：scene 落库时带 intervention_id/goal_id/evidence_id，双后端实现 + 按 evidence_id 反查的测试（1-A-4 契约的实现）——直接决定后续 Evidence Engine 呈现和第 11 章"错因诊断可视化"能不能做起来
  - ✅ 2026-09-12 完成：`cogedu/persistence/presentation_store.py`（PresentationStore，LCAStore/DualAgentStore 同模式：独立表 + adapter 双后端 + 幂等 ON CONFLICT + `degraded` 落库列）；索引含 `idx_scenes_evidence` 错因反查。路由编排：`/outline` 生成即落库（落库失败 warning 不中断呈现）+ `web/api/presentation_service.py`（框架无关编排层）/ `POST /api/presentation/scenes`（404/502 分级）。conftest 补 presentation 单例归一化
- [x] **1-C-4** 单元 + HTTP 测试（mock LLM）：场景数与大纲步数一致、公式格式约束命中、追溯字段完整
  - ✅ 2026-09-12 完成：`tests/test_presentation_scene.py`（13 用例）+ `tests/test_presentation_store.py`（双后端参数化奇偶 12 用例，PG 无服务器 skip）+ `/scenes` HTTP 契约 4 用例。全量 **1696 用例通过**

### 13.5 1-D：生成健壮性（借鉴 OpenMAIC 的 json-repair.ts + generation-retry.ts，1-C 基本流程跑通后补）

- [x] **1-D-1** 评估 PyPI `json-repair`（license/维护状况），合适直接用，不合适则参考 OpenMAIC `json-repair.ts` 思路用 Python 自写 `cogedu/presentation/json_repair.py`
  - ✅ 2026-09-12 完成：**直接采用**（MIT、纯 Python 无传递依赖、活跃维护）。`parse_llm_json` 流水线 = `clean_llm_output`（复用 `cogedu/llm_client.py` 既有清理，think 块+围栏）→ `json.loads` → 失败 `json_repair.repair_json`（warning 留痕）→ 彻底修不了 ValueError 含原文。**连带**：生成器 Protocol 从 `chat_json` 改为 `chat`（raw text 拿在生成层手里才能修复，不从异常 message 反解）；pyproject 加 `json-repair>=0.61`
- [x] **1-D-2** 重试策略：次数上限/超时/退避，参数进配置，封装在生成入口
  - ✅ 2026-09-12 完成：`cogedu/presentation/retry.py` `RetryPolicy`（from_env：`COGEDU_PRESENTATION_MAX_ATTEMPTS`/`_BACKOFF_SEC`，非法值 warning 兜底）+ `call_with_retry(retry_on=...)`。**职责切分**：传输层失败 client 内部已重试（max_retries=3 指数退避 + timeout 30s），生成层只重试解析失败（ValueError/结构不合规）；RuntimeError 立即上抛不重复重试
- [x] **1-D-3** 降级行为：重试耗尽 → 模板化 degraded scene，带 `degraded: true` 标记 + **warning 留痕不静默**（对齐 v0.47.5 "宁可明确失败信号也不静默吞异常"的仓库约定），学生端可感知但不空白
  - ✅ 2026-09-12 完成：`_degraded_scene`（模板内容引用大纲 step 的 title/key_points/objective，不依赖失败的 LLM 输出；`degraded=True` + `warnings` 留痕 + 落库 `degraded` 列可统计降级率）；**传输层失败不降级**（网络问题不伪装成"内容生成好了"，上抛 502）。`policy=None` 保留 1-C 严格模式（任一步失败整体上抛）
- [x] **1-D-4** 测试：坏 JSON 修复 / 重试耗尽 → 降级标记 + warning 留痕
  - ✅ 2026-09-12 完成：`tests/test_presentation_robustness.py` 17 用例（修复/重试/降级/strict 对照/传输层不降级）+ HTTP 语义更新（解析失败→200 degraded scenes；传输失败→502）。**教训记录**：`ruff --fix` 误扫全仓波及 136 文件，已按范围外 revert——autofix 永远不带目录白名单之外的路径。全量 **1714 用例通过**；mypy python_version 3.11→3.12（numpy 新存根 type 语句经 json_repair→llm_client 链路暴露）

### 13.6 1-E：前端渲染

- [ ] **1-E-1** 学生端场景页（`web/student/` 扩展）：翻页式交互，按顺序展示 text+image，不需要 Phase 3 的播放状态机（idle/playing/paused/live）
- [ ] **1-E-2** KaTeX 集成（第 11 章的发现，不用自己设计方案）：识别 `$...$`/`$$...$$` 定界符渲染；**内容渲染必须走转义，不裸 innerHTML**——LLM 输出直接进 DOM 是 XSS 面
- [ ] **1-E-3** 图片组件：懒加载 + 加载失败占位
- [ ] **1-E-4** degraded 场景的 UI 提示

### 13.7 1-F：回写事件闭环（这一步是验证"整合真正生效"的关键）

- [x] **1-F-1** 定义场景行为事件类型（对齐现有 LearningEvent 命名约定）
  - ✅ 2026-09-12 完成：`scene_viewed`（翻离场景页，payload 含 dwell_sec）+ `scene_completed`（看完）。**语义决策（偏离原案，已记录）**：不伪造作答 Observation 进 `update_belief`——那会污染 CTA 的 MIRT/BKT 推断；走内核 v0.91.0-b 确立的 human feedback 通道（`LearningEvent` → `PluginRuntime` 订阅者 → `HumanFeedbackEntry` → `LCAEngine.append_human_feedback` → 影响后续 `plan()`）。内核 additive 扩展（enum +2 / 白名单 +2 / 新 factory，算法零改动），记录进 `kernel-baseline-notes.md` §8 + `presentation-runtime-map.md` §6。"belief 再次更新" 由端到端链路中"看完讲解后重新答题"实现
- [x] **1-F-2** Plugin 形式接入：学生端埋点 + HTTP 端点 → publish 事件 → 事件总线订阅者 → 内核（**零 mutation**，复用 12.3 验证过的事件驱动模式）——走通才算验证"呈现引擎是内核的下游消费方，不是另起一套状态"（第 2 章原则）
  - ✅ 2026-09-12 完成：`POST /api/presentation/event`（复用 `event_stub._emit_event`）+ `PluginRuntime._handle_scene_viewed/_handle_scene_completed` + `scene.js trackSceneEvent`（best-effort，keepalive 保证跳转前送达，console.warn 不静默）+ 前端接线 grep 契约测试
- [x] **1-F-3** 事件落库复用现有 event_log 路径（12.6 灰度已验证 hint/reflection 落库）
  - ✅ 2026-09-12 完成：`_emit_event` 内含 event_log 持久化（F-11 fail-open + warning 语义原样复用），全链路测试断言落库
- [x] **1-F-4** HTTP 全链路测试：埋点 → 总线 → 内核消费断言（对齐 12.4 `/api/answer` 全链路测试风格）
  - ✅ 2026-09-12 完成：`tests/test_presentation_events.py` 11 用例——真实 PluginRuntime + 真实 LCAEngine，断言 `twin.human_feedback.count_by_type("scene_viewed") == 1` + event_log 落库 + 非法 event_type 400。既有 `len(LearningEventType)==10` / `subscription_count==8` 断言随 additive 扩展更新为 12/10（6 个测试文件）。全量 **1727 用例通过**

### 13.8 1-G：端到端验证

- [x] **1-G-1** 真实进程端到端 3-5 案例（答错 → CTA → LCA → 大纲 → 场景 → 展示 → 行为回写 → belief 再更新），沿用 12.6 灰度脚本模式 + 真实 LLM；**人工检查内容质量**（讲解对不对、和学生实际薄弱点匹不匹配），不只是"跑通不报错"
  - ✅ 2026-09-12 完成：`scripts/canary_phase1_presentation.py`（真实 uvicorn 进程 + 真实 MiniMax LLM，3 案例）。**全部通过**：每案例 5 场景零 degraded；行为回写 200；答对后 theta K 全部上移（-0.331 → -0.113）；overall_confidence 0.52/0.416。内容质量人工复核：大纲 5 步结构 + 例题递进 + 口诀 + 易错提醒 + 代回验证，算术全部验算无误；Bloom 目标体现在讲解形态（REMEMBER 层→记忆口诀型）；公式 LaTeX 规范。**灰度发现并修复 1**：MiniMax-M3 thinking 块计入 max_tokens，默认 1024 被推理耗尽 → strip 后空文本（LLM 输出为空的 502）——生成器显式 `max_tokens=4096`（`GENERATION_MAX_TOKENS`）。**灰度发现 2（边界注记，非缺陷）**：canary 用合成 skill_id（无 Q 矩阵数据），target_skills 为空 → 生成主题由 LLM 自选，与 skill_id 字面不对应；"内容-薄弱点匹配度"的完整评估要等真实题库/Phase 5 知识库接入，链路本身正确。**运维注记**：场景请求 = 步数次串行 LLM 调用，客户端超时需 ≥900s
- [x] **1-G-2** 端到端自动化回归纳入 pytest
  - ✅ 2026-09-12 完成：`tests/test_presentation_e2e.py`——答错×2 → outline(带 evidence_id) → scenes（追溯字段完整）→ scene_viewed×n + scene_completed 回写（lifespan 激活真 PluginRuntime 消费）→ 再答对 theta K 上移 → `list_scenes_by_evidence` 反查。全链路 HTTP 级确定性（脚本化 LLM mock）
- [x] **1-G-3** 收尾：方案文档第 13 章勾选 + CLAUDE.md/README/CHANGELOG 同步 + commit/push
  - ✅ 2026-09-12 完成：Phase 1 全部收官（本节 + CLAUDE.md + README + CHANGELOG 同步更新）。全量 **1728 用例通过**

---

Phase 1 做完、验证通过后，可以按同样方式细化 Phase 2（家长端重新设计 + 导出能力）。

---

## 14. Phase 2 详细开发任务清单（家长端重新设计 + 导出能力）

范围重申：不受现有 785 行家长端代码限制，可自由重新设计；导出能力作为家长端的具体功能点一并设计，不是独立旁支。

**细化时的新发现（2026-09-12）**：仓库现状核查发现 CogEdu **完全没有账号/身份体系**——`pg_schema.py` 无 users 表、全仓无登录/鉴权逻辑、现有家长端接口无鉴权直接枚举全部学生（`routers/parent.py` 的 `/students` 返回库内所有学生），方案文档此前也没有账号体系的设计章节。而 2-A 的 `guardian_learner_link`、家长端灰度发布、"撤销立即生效"验收点全部以真实账号为前提。因此本清单在 2-A 之前新增 **2-0 最小账号体系**（经维护者确认）。

**已确认决策（2026-09-12，维护者拍板）**：

1. 新增 2-0 最小账号体系（username + password、guardian/student/teacher/admin 三四种角色、服务端会话），作为 2-A 与所有家长端功能的地基；
2. v1 功能范围按 14.4 建议表：必做 = 学习进度总览 + 报告导出；可选视资源 = 异常预警简化版、证据链简化版；分配材料/使用限制排 v2；
3. 报告导出格式 v1 先做 **Word（docx）**，公式渲染成图片嵌入；PPTX 与 mathml2omml 可编辑公式链路排 v2。

### 14.1 任务顺序与依赖关系

```
2-0 最小账号体系（先做，2-A 与所有家长端功能的地基）
        ↓
2-A 权限模型设计（guardian_learner_link 显式授权，借鉴 DeepTutor guardians.py）
        ↓
2-B 功能范围确定（✅ 2026-09-12 已确认，见 14.4）
        ↓
2-C 导出能力（Word docx + 公式图片嵌入）
        ↓
2-D 前端页面 ──┐
2-E 回归与发布 ─┘（2-D 基本可用后并行推进）
```

### 14.2 2-0：最小账号体系（✅ 2026-09-12 完成）

- [x] **2-0-1** 账号 schema（`cogedu/persistence/pg_schema.py` 新增迁移）：`users` 表（`user_id` PK、`username` 唯一、`password_hash`、`role`（`guardian`/`student`/`teacher`/`admin`）、`created_at`、`disabled_at`）。**学生账号与学习数据的关联要显式设计**：`students` 表是学习状态表（`student_id` 是学习记录键，不是账号），学生角色账号需一列关联 `learning_student_id`（1:1），家长端所有取数走这条链路。凭证哈希用 bcrypt（`bcrypt` 库，最小依赖），**绝不存明文/可逆形式**
  - ✅ 2026-09-12 完成：`cogedu/persistence/auth_store.py`（AuthStore，LCAStore/PresentationStore 同款双后端模式，**独立 DDL 不动 kernel 镜像的 SCHEMA_SQL**）；users 表含 `display_name`/`learning_student_id`（1:1，无 FK——学习记录懒创建，账号可先建）；sessions 表 token 只存 SHA-256 哈希；`reset_auth_store` 单例重置进 conftest 隔离
- [x] **2-0-2** 认证与会话：`POST /api/auth/login`（登录发会话 token）+ `POST /api/auth/logout` + `GET /api/auth/me`。**会话选服务端存储**（`sessions` 表：token 哈希 + `user_id` + `expires_at` + `revoked_at`），不用 JWT——2-A 的"撤销立即生效"验收要求会话可即时失效，JWT 无状态做不到。FastAPI dependency 注入 `current_user`，路由声明式标角色要求
  - ✅ 2026-09-12 完成：`web/api/auth.py`（服务 + dependencies 一体；TTL 默认 7 天，`COGEDU_SESSION_TTL_HOURS` 可配；登录统一 401 不区分用户不存在/密码错——防用户名枚举；禁用账号即撤销全部活跃会话）+ `routers/auth.py` 三端点。**真实进程冒烟验证**：登录 → 带 token 200 → logout → 同一 token 立即 401
- [x] **2-0-3** 存量接口纳入保护：家长端/教师端 0-C 迁移来的路由补鉴权（未登录 401、角色不符 403）。**存量测试与灰度脚本的出路要先想好**：现有 HTTP 契约测试、12.6 灰度脚本、1-G canary 大量裸调接口，加鉴权后会全挂——提供测试专用登录 helper（测试内直接造用户+会话），canary 脚本走真实登录链路；**不做"环境变量关鉴权"的后门**（灰度环境正是要验证鉴权的地方）
  - ✅ 2026-09-12 完成：角色-路由矩阵经 router-level `dependencies` 接线（teacher/staff、parent/guardian+staff、student+event+presentation/学生本人 via `require_student_access` 路径参数或 body 取 student_id、stream/任意已登录、dual_agent/staff、`/api/students/recent` 收紧为已登录）。**存量测试零破坏**：conftest autouse `auth_bypass` patch `web.api.auth._resolve_request_user`（dependencies 唯一取数点，patch 面约定见模块 docstring）——测试层设施非生产后门，鉴权语义本身由 `real_auth` marker 测试负责。canary 脚本已接真实开户（直连灰度 DB）+ 真实登录（HTTP）。**遗留缺口（记录在案）**：parent 接口做到"已认证 guardian 角色"粒度，per-student 的 `guardian_learner_link` 关系校验在 2-A 落地
  - ✅ 开户 CLI：`scripts/manage_users.py`（create/list/disable/enable，v1 无自助注册——K12 由管理员/教师开户）
- [x] **2-0-4** 前端登录态：学生/家长/教师静态页加登录页 + 401 跳转；`scene.js` 回写事件携带学生身份（当前匿名可写是越权面）
  - ✅ 2026-09-12 完成：`web/auth.js`（token 存取/authFetch/requireLogin 守卫/logout，Bearer + localStorage 方案不用 cookie——避免 CSRF 面与 SameSite 复杂度）+ `web/login.html`（按角色跳转，`?next=` 仅站内路径防 open redirect）+ `/login`、`/auth.js` 静态路由；学生端 app.js 统一走 authFetch、scene 页守卫 + 回写带 Authorization、teacher/parent 占位页同样接守卫；scene 页 sid 优先取登录账号绑定的 `learning_student_id`。前端接线有 grep 契约测试锁定
- [x] **2-0-5** 测试：登录/登出/过期/撤销会话、角色-路由矩阵（如 guardian 访问教师接口 403）、密码哈希正确性
  - ✅ 2026-09-12 完成：`tests/test_auth_api.py` 37 用例（服务层哈希/账号规则/会话生命周期含撤销立即生效与 token 明文不落库、HTTP 三端点、9 域 401 矩阵、学生越权 body/路径双路 403、前端接线契约）。全量 **1765 用例通过**（2-0 前 1728）

### 14.3 2-A：权限模型设计（✅ 2026-09-12 完成，借鉴 DeepTutor `guardians.py`，但落地方式不同）

- [x] **2-A-1** 设计 `guardian_learner_link` 关系（不是隐含的角色继承，是显式的授权记录）：谁（家长账号）对谁（学生账号）有什么权限、什么时候建立的、能不能撤销。字段：`id`、`guardian_user_id`、`learner_user_id`、`permissions`、`granted_at`、`revoked_at`、`revoked_by`、`revocation_reason`（撤销留痕对齐 DeepTutor）。**存储否决 DeepTutor 的 JSON 文件方案**（那是它 MVP 阶段的取舍），直接建 PG 关系表，享受完整性约束和查询能力：同 (guardian, learner) 对唯一活跃关系（partial unique index `WHERE revoked_at IS NULL`）、不能自己绑定自己、learner 角色账号不能当 guardian（照搬其 `_require_ordinary_user` 每次重查角色的防御思路）。持久化延续 12.5 双后端 adapter 模式（SQLite 跑单测、PG 集成测试无服务器 skip 的既有惯例）
- [x] **2-A-2** 权限项（在 DeepTutor 四项基础上按教育场景调整，`reset_credentials` 这类账户凭证权限对 K12 意义不大，不设）：
  - `view_progress`（查看学习进度/Belief 概览）
  - `view_evidence`（查看证据链细节，完整版依赖 Phase 4 的可视化增强）
  - `download_report`（下载导出的学习报告）
  - `receive_alerts`（接收异常预警通知，v1 可选项，enum 先留位）
  - `assign_materials`（**不进 v1**，等 Phase 5 知识库，enum 先留位）
- [x] **2-A-3** 授权建立流程：家长发起申请 → **学生本人确认**（学生端登录后看到待确认申请）才生效，不能家长单方面绑定学生账号；流程状态 `pending → active / rejected`。无学生账号在用的低龄场景由管理员代确认（admin 最小实现）
- [x] **2-A-4** 校验入口单一化：`guardian_can_access(guardian_user_id, learner_user_id, permission)` 一个函数管所有家长端取数授权，**每个数据接口每次请求都现查**——校验时重查双方当前角色（角色变更后旧授权自动失效，防"前学生变家长"类越权路径）。**不做授权缓存**："撤销立即生效"靠无缓存实现，家长端 QPS 低，现查无性能压力
- [x] **2-A-5** 测试：一个学生被多个家长关联互不干扰、撤销后家长端下一次请求即失效、未授权学生数据 403、角色变更后旧授权失效、pending 未确认不可见任何数据

  - ✅ 2026-09-12 完成（2-A 全部项）：表落 `cogedu/persistence/auth_store.py`（与 users/sessions 同库；状态机 `pending → active / rejected / revoked` + partial unique index `WHERE status IN ('pending','active')`，比原案 `revoked_at IS NULL` 更贴合申请流——撤销/拒绝后同对可重申）。服务层 `web/api/guardian.py`（五权限项常量 + 流转 + `guardian_can_access`/`guardian_can_access_student` + `list_active_linked_student_ids` 家长 roster 数据源）。端点 `routers/guardian.py`（家长申请/列表/撤回撤销；学生查看/确认/拒绝/撤销；admin 可代确认/拒绝）。**家长端数据接口已接 per-student 校验**：roster 只列 active 关联学生、overview 过 `view_progress` 权限（未授权 403；staff 全量视图不变——存量契约测试零破坏）。**语义注记**：roster 只显示"已授权且有学习记录"的学生（学习记录懒创建，无记录行跳过）；目标学习记录不存在但已授权时 overview 走 404（防幽灵学生语义不变）。测试 `tests/test_guardian_links.py` 21 用例。全量 **1786 用例通过**。授权管理前端页归 2-D（14.6）

### 14.4 2-B：功能范围（✅ 2026-09-12 已确认，按建议表）

| 功能 | v1 决定 | 依赖 |
|---|---|---|
| 学习进度总览（Belief/Bloom 维度可视化） | **v1 必做** | Belief 数据现成 |
| 学习报告导出（Word docx，周报/月报） | **v1 必做** | 2-C |
| 证据链呈现（简化版：答题/场景记录下钻列表） | v1 可选，视资源 | 完整版等 Phase 4 |
| 异常预警通知（简化规则版，如连续 N 次同一知识点出错） | v1 可选，视资源 | 无 |
| 分配学习材料 | v2 | Phase 5 知识库 |
| 管理使用限制（时长/难度） | v2 | 无强依赖，优先级低 |

### 14.5 2-C：导出能力（✅ 2026-09-12 完成，格式已决策：Word 优先，公式图片嵌入）

- [x] **2-C-1** 公式渲染 spike（先验证再写主链路）：候选 matplotlib mathtext（离线、无 headless browser、numpy 系依赖已入库）渲染 LaTeX → PNG。**已知风险：mathtext 不是完整 LaTeX**（不支持 `\begin{...}` 环境和部分宏），先拿 Phase 1 灰度真实产出的公式样本批量试渲染、统计失败率，再定主方案；单条渲染失败降级为 LaTeX 原文嵌入 + warning 留痕（对齐仓库"宁可明确降级不静默"约定），不让整份报告失败
- [x] **2-C-2** 内容结构层（框架无关模块 `web/api/report.py`，不绑 docx）：周期（周/月）→ 数据聚合（答题量/正确率、Belief theta 走势、Bloom 分布、薄弱知识点 top-N、interventions 摘要）→ 结构化 `ReportDocument`（段落/表格/公式占位/图片位）。聚合逻辑与 overview 接口**同源取数**（不各算各的），有单测锁定
  - ✅ 2026-09-12 完成：`web/api/report.py` — `ReportDocument`（Pydantic：paragraph/table/formula 三种 block，聚合层 warnings 留痕不静默）；聚合同源 teacher/parent helpers（roster/overview 同一批）；周期 = week(7d)/month(30d) 按 response_history timestamp 过滤（naive 本地 ISO 口径，aware 剥 tzinfo）；薄弱点 = 周期内维度正确率 <0.6 且答题 ≥2 取 top-3 + 最近误概念
- [x] **2-C-3** docx 渲染器：`ReportDocument` → docx（`python-docx`，纯 Python，依赖纪律通过）；公式占位 → mathtext PNG 嵌入（按公式串缓存渲染结果，同一报告内重复公式不重复渲染）；报告头尾带生成时间 + 数据截止时间（家长看到的数字要能对上"哪天的状态"）
  - ✅ 2026-09-12 完成：`web/api/docx_renderer.py`（只做翻译不算数；公式 → mathtext PNG 居中嵌入，`lru_cache` 按公式串去重；**单条公式失败降级 LaTeX 原文段落 + 附注 warning，报告整体不失败**；文本内 `$...$`/`$$...$$` 混排经 `extract_formulas` 拆块）；`web/api/formula_render.py`（预检 spike 实证的不支持构造：环境/mhchem/`\operatorname`/CJK——避免产出错误内容图）
- [x] **2-C-4** HTTP 端点：`GET /api/parent/students/{student_id}/report?period=week|month`，过 `download_report` 权限校验（2-A-4 单一入口），返回文件流；学生不存在 404、无权限 403
  - ✅ 2026-09-12 完成：`GET /api/parent/students/{sid}/report?period=week|month`；guardian 过 `download_report` 权限（2-A 单一入口）；**语义决策：guardian 对未知学生 → 403（权限检查在前不泄漏存在性），404 防幽灵学生语义由 staff 路径承载**；依赖 python-docx + matplotlib 入 pyproject
- [x] **2-C-5** 测试：聚合正确性、公式渲染失败降级、docx 最小 smoke（段落/图片数断言，能被 `python-docx` 重新打开）、越权拒绝
  - ✅ 2026-09-12 完成：`tests/test_parent_report.py` 18 用例（公式渲染含缓存/预检拒绝/混排拆分；聚合含周期过滤/薄弱点/warnings 留痕；docx 重开 smoke 含 inline_shapes 与降级附注断言；HTTP 权限矩阵）。**真实进程冒烟**：开户 → 答题 → 授权（download_report）→ 下载 200（docx 重开正常）→ 学生撤销 → 再下载**立即 403**。全量 **1804 用例通过**
  - ✅ 2026-09-12 完成：`scripts/spike_mathtext_formula.py` 33 样本（样本来源诚实注记：1-G 真实产出在 tmp canary 库未存档，按 Phase 1 prompt 锁定的公式形态 + K12 典型构造 + 已知风险构造构建；Phase 5 接真实题库后应重跑）。**结果 88%（29/33）**：prompt 约束形态 5/5、K12 典型 21/21 全过；失败 = `\begin{}` 环境 / `\ce{}` mhchem / 未剥离 `$$`。**spike 踩坑两个**（已写进 formula_render.py 头注）：① `math_to_image` 必须保留 `$...$` 定界符——剥离后整串按普通文本渲染，**不报错但内容错误**（仅查 PNG 大小会全绿假象，需目检图像）；② mathtext 对不支持命令有的抛异常有的静默按字面输出——生产渲染器**预检优先于依赖解析异常**。主方案定为 mathtext，失败降级 LaTeX 原文
- [x] **2-C-2** 内容结构层
- [ ] **2-C-6**（v2 预留，不在本 Phase 实现）PPTX 格式与 LaTeX→MathML→OMML 可编辑公式链路（参考 OpenMAIC `mathml2omml` 思路），视 v1 报告的实际使用反馈决定做不做

### 14.6 2-D：前端页面（✅ 2026-09-12 完成）

- [x] 家长登录 + 绑定入口 + 授权管理页（发起绑定申请/查看已授权限/撤销）
- [x] 学生端确认页（待确认的家长绑定申请，确认/拒绝）
- [x] 学习总览仪表盘（复用学生端已有的 Belief 可视化组件，按家长视角做简化/汇总）
- [x] 报告下载入口（周报/月报选择）

  - ✅ 2026-09-12 完成：`web/parent/index.html` 重写为真实家长端（此前是占位页）——「我的孩子」roster 卡片 + 学习概览下钻（5D theta/Bloom 表，家长视角简化汇总）+ 报告下载（authFetch blob 下载带 Authorization）；「授权管理」发起申请（权限勾选）/状态列表/撤回撤销。`web/student/guardian-links.html` 学生端确认页（待确认申请确认/拒绝 + 全部授权记录撤销），入口挂在学生端设置页。**范围注记**：①学生端已有 Belief 可视化是 index.html 内联 JS 非组件，无可复用单元——家长端按"家长视角简化/汇总"要求直接写表格版（theta/Bloom），未强行抽象共享组件；②证据链展示页/预警通知位为 v1 可选项，按 14.4 确认范围**未启用**（待 Phase 4/资源评估）
- [x] （如果 v1 做预警简化版）站内预警通知位 —— **按 14.4 确认范围 v1 未启用**（可选项目，待 Phase 4 证据链增强/资源评估后重估）

### 14.7 2-E：回归与发布（✅ 2026-09-12 完成，全量发布待维护者）

- [x] 权限边界回归：学生撤销权限后家长端**下一次请求**立即失效、一个学生被多个家长/监护人关联互不干扰、家长尝试访问未获授权的学生数据被拒绝、pending 状态不可见任何数据
- [x] 灰度：`scripts/canary_phase2_*.py`（延续 12.6/1-G 模式：真实进程 + 真实登录链路），重点人工复核**导出报告的可读性和实用性**（版式、公式是否清晰、数字家长能否看懂），先小范围家长用户验证，再全量
  - ✅ 2026-09-12 完成：`scripts/canary_phase2_parent.py` 14 步真实进程全链路通过（开户→申请→学生确认→答题→roster/overview 可见→报告下载+内容打印→家长 B 越权 403→学生撤销→家长 A 下一请求立即 403）。**灰度发现并修复 1**：主导 Bloom 层级用 L1-L6 映射表查枚举名 "APPLY" 落空，报告出现 "APPLY（）" → 新增 `_DOMINANT_NAMES` 枚举名映射。**报告可读性人工复核**：版式（标题/四节/表格/附注）与数字口径清晰；当前题库无 LaTeX 公式内容，公式图嵌入路径由合成样本单测锁定，Phase 5 接入数理化题库后应重跑灰度复核公式清晰度。**待维护者执行**：小范围真实家长用户验证后再全量发布（脚本级灰度已完成，人工用户验证无法自动化）
- [x] 收尾：方案文档勾选 + CLAUDE.md/README/CHANGELOG 同步 + commit/push
  - ✅ 2026-09-12 完成（本次提交；README 未涉及 Phase 2 内容变更，未动）

---

**Phase 2 收官（2026-09-12）**：2-0 账号体系 + 2-A 权限模型 + 2-B 范围确认 + 2-C Word 报告导出 + 2-D 前端页面 + 2-E 灰度（脚本级）全部完成；全量 1804+ 用例通过。唯一待办 = 小范围真实家长用户灰度验证（人工步骤，维护者执行）。

---

Phase 2 做完后，按同样方式细化 Phase 3（白板与语音）。

---

## 15. Phase 3 详细开发任务清单（白板与语音）

范围重申（v0.6 修订）：动作集 = `wb_draw_text` + `wb_draw_shape` + **`wb_draw_line`（本节细化时增补，两点式线段——数理化画坐标轴/数轴/辅助线的刚需，三种图形覆盖不了）** + `wb_draw_latex` + `speech`（第 3 章动作引擎行的"四动作"结论由此修订），其余 OpenMAIC 支持的动作类型（spotlight/laser/discussion 辩论/widget_* 系列）明确排除在 v1 外。OpenMAIC 播放引擎的第四态 `live`（discussion/AI 同学追问模式）同样不在本 Phase 范围。GeoGebra 类的学生自主探索型可视化工具是另一条能力线（第 11 章新增的 Phase 6），不在本 Phase 范围内，避免混为一谈。

### 15.1 任务顺序与依赖关系（细化后）

```
3-A 动作模型与协议设计（先做：Scene.actions 从预留字段落成正式 schema + 版本机制）
        ↓
3-B 白板渲染组件 ────┐
3-C 播放引擎/状态机 ──┼（可并行；3-B/3-C 开发期可用 3-E 常量的占位值，3-E 最后收口定值）
3-D 语音合成集成 ────┘
        ↓
3-E 时间常数单一数据源（收口：Python 生成侧与 JS 播放端必须同一套数字）
        ↓
3-F 生成侧改造（SceneGenerator 产出动作序列 + TTS 异步补齐编排）
        ↓
3-G 端到端验证
```

3-F 依赖 3-A（动作 schema）与 3-D（TTS 接口）；3-B/3-C 依赖 3-A 的 schema 与 3-E 的常量。

**细化时的新发现（2026-09-12，双份代码勘察：OpenMAIC 参考实现 + CogEdu 仓库现状）**

*OpenMAIC 侧（动笔前逐文件核实，修正 v0.5 两处凭印象的表述）：*

1. **白板渲染不是"SVG 还是 Canvas"二选一**（15.3 原文作废）：`whiteboard-canvas.tsx`（456 行）实际是 **DOM 绝对定位 + 图形内嵌 SVG path + CSS/framer-motion 动画**——文字/公式是 HTML（KaTeX `renderToString` 产出直接嵌入），只有 shape 元素内部是 SVG path。它的目标场景是"教师实时编辑"，CogEdu v1 学生是观众，需求面更窄。
2. **播放调度不消费音频时长**（15.5 原文"返回时长驱动播放引擎"修正）：`lib/playback/engine.ts`（902 行）是**事件驱动 + setTimeout，无 rAF、无绝对时间轴**——speech 等音频 `ended` 回调，无预生成音频才退到估算计时器；音频时长是**入库时**字节嗅探测一次（WAV RIFF / MP3 Xing），存 IndexedDB 供**视频导出**用，播放链路不读它。全引擎最核心的并发正确性机制是 `playbackGeneration` 代数令牌（pause/stop/跳转使旧异步回调失效）。
3. 可直接抄的事实清单：坐标系 = 固定虚拟画布宽 1000（16:9 高 562.5）、原点左上、非归一化非百分比；`wb_draw_shape` 仅 rectangle/circle/triangle 三种；白板历史 = 快照栈（20 上限、无 redo、只在破坏性操作前压栈）；TTS 统一接口 `{audio: bytes, format}` **不含时长**；超长 speech 按 `。！？` → `，` → 硬切三级降级拆成多个独立动作；时间常数实测值见 15.6。

*CogEdu 现状侧（扩展点与缺口）：*

1. `Scene.actions` 字段已预留（`cogedu/presentation/types.py` 尾部，`list[dict[str, Any]] | None`，Phase 1 恒 None）——3-A 要把它落成真正的 Pydantic discriminator union。
2. 前端零播放基础设施：scene 页是纯翻页 + 全量重建 DOM，无任何定时器/动画队列；KaTeX 走 CDN，渲染函数 `appendFormula`（`scene.js:130`）可直接提为共享模块。
3. 无 schema 版本机制：payload 是裸 `model_dump_json()` 落库，无版本列/修订列——actions 是新增嵌套结构，需要补版本字段。
4. `POST /api/presentation/scenes` 鉴权缺口：请求体只有 `outline_id` 没有 `student_id`，router 级 `require_student_access` 实际只验"已认证"。
5. `GENERATION_MAX_TOKENS = 4096` 是 outline/scene 共享硬编码常量；动作序列会让 scene 输出显著变长。
6. 场景生成是逐 step 串行 LLM 调用（1-G 灰度实测达数分钟），同步端点、无异步任务机制——TTS 预生成不能再叠进同一条同步链路。

**已确认决策（2026-09-12，维护者拍板）**：

1. 白板渲染走 **DOM 元素 + 图形内嵌 SVG path** 路线（OpenMAIC 实证路线；v1 无学生自由绘制，否决 Canvas）；
2. v1 动作集在四动作之外**增补 `wb_draw_line`**（两点式线段，见范围重申）；
3. **砍掉白板历史（撤销/重做）**，代之以"重播本页"——白板内容是动作序列的确定性重放，学生没有编辑入口，快照栈没有消费方；
4. **TTS 异步补齐 + 播放端降级**：`POST /scenes` 不等 TTS，后台任务补生成回填 `audio_id`，播放时无音频走估算计时器静音推进。

### 15.2 3-A：动作模型与协议设计

- [x] **3-A-1** 动作 schema：`Scene.actions` 从 `list[dict]` 落成 Pydantic discriminator union（参照 `SceneBlock` 的 `Annotated[..., Field(discriminator=...)]` 模式）：`WbDrawTextAction`（`content`/`x`/`y`/`width=400`/`font_size=18`/`color`）、`WbDrawShapeAction`（`shape ∈ rectangle|circle|triangle`/`x`/`y`/`width`/`height`/`fill_color`）、`WbDrawLineAction`（`x1`/`y1`/`x2`/`y2`/`color`/线宽）、`WbDrawLatexAction`（`latex`/`x`/`y`/`width`/`color`）、`SpeechAction`（`text`/`voice`/`speed=1.0`/`audio_id` 回填位）。字段与默认值对齐 OpenMAIC `packages/@openmaic/dsl/src/action.ts` 的 payload 定义。**action_id 由生成侧统一重分配**（LLM 给的 id 不可信，对齐 Phase 1 `step_id` 惯例）；`ALLOWED_ACTION_TYPES` 白名单常量 + 穷尽性校验（Pydantic union 天然获得运行时版本，对齐 OpenMAIC `isActionType` + 编译期穷尽检查的意图）
  - ✅ 2026-09-13 完成：`cogedu/presentation/types.py` 新增动作模型段（`ActionBase` 公共字段 + 五动作 + `SceneAction` union + `ALLOWED_ACTION_TYPES`/`is_allowed_action_type`）；五动作统一继承 `ActionBase`；坐标为必填（LLM 不给坐标宁可失败走 retry，不出幽灵位置）；测试锁定 union 成员 ↔ 白名单一一对应
- [x] **3-A-2** 坐标系统：固定虚拟画布宽 1000、高 562.5（16:9），原点左上，数值用像素（OpenMAIC 同款，非归一化/百分比）。LLM 输出越界值 **clamp 进画布 + warning 留痕**，不拒绝整场
  - ✅ 2026-09-13 完成：`WB_CANVAS_WIDTH=1000`/`WB_CANVAS_HEIGHT=562.5` 常量 + `clamp_canvas_point` 纯函数；warning 留痕由 3-F 解析侧负责（本层只提供纯助手，不做 IO/日志）
- [x] **3-A-3** 时序模型修正（对 15.2 原文）：每个动作带 `estimated_duration_ms`（生成侧按 3-E 常量估算），**不做绝对时间轴**——调度是顺序事件驱动（3-C-2），预计时长只服务时间轴预览与未来导出
  - ✅ 2026-09-13 完成：`estimated_duration_ms: int | None` 进 `ActionBase`（None = 尚未估算，3-F/3-E 估算回填）
- [x] **3-A-4** schema 版本机制：`Outline`/`Scene` 顶层加 `schema_version: int`（Phase 1 存量 = 1，含 actions = 2），随 payload 自动落库；前端按版本/`actions` 是否为空分支——**`actions=None` 的 Phase 1 旧场景必须继续以纯翻页模式可渲染**（回归锁定）
  - ✅ 2026-09-13 完成：`SCHEMA_VERSION_V1=1`/`V2=2`；Scene 的 after-validator 在 actions 非空时自动升 v2（版本号是派生事实，单点维护在模型内，生成侧手动传 v1 也被纠正）；无 `schema_version` 字段的 Phase 1 存量 payload 读回走默认值 v1（回归锁定）；store round-trip（SQLite）验证 actions 类型化恢复。新增 `tests/test_presentation_actions.py` 21 用例，全量 **1828 通过**

### 15.3 3-B：白板渲染组件（技术路线已拍板：DOM + SVG path）

- [x] **3-B-1** 画布组件 `web/student/whiteboard.js`（新文件，与 scene.js 解耦）：虚拟坐标 1000×562.5 → 屏幕的等比缩放（ResizeObserver 测容器 + `containerScale = min(cw/1000, ch/562.5)`，参考 OpenMAIC `whiteboard-canvas.tsx`；它的 456 行里视口交互占大头，CogEdu v1 是观众场景，**滚轮缩放/拖拽平移/双击复位不做**，只做自适应等比缩放）。元素按 actions 数组顺序渲染，单层平面无图层模型（OpenMAIC 同款）。LLM 文本一律 `textContent`/受控节点构建（沿用 scene 页安全约定；KaTeX 产出的 HTML 是唯一例外——来源是本地渲染不是 LLM 原文）
  - ✅ 2026-09-13 完成：`createWhiteboard(container)` 返回 3-C 引擎的 renderer 接口（`clear()`/`execute(action)`）；虚拟层固定 1000×562.5 + `transform: scale()` 等比缩放（字号/线宽随画布缩放）；wb_draw_line 用整幅虚拟画布 SVG 覆盖层（两点式坐标即画布坐标）；`elementSpec` 纯函数（动作→元素规格，node 可测）与 DOM 组装分离；渲染侧坐标 clamp 兜底（3-F 解析侧之外的第二道）
- [x] **3-B-2** `wb_draw_latex` 公式渲染复用：把 `appendFormula`（`scene.js:130`）提为 `web/student/formula.js` 共享模块，scene 文字块与白板公式动作共用同一函数（"同一能力只写一次"的落点；KaTeX 暂维持 CDN，vendor 本地化可顺带做掉 scene.html 里既有的 TODO）。`throwOnError: false` + 渲染失败降级等宽原文
  - ✅ 2026-09-13 完成：`formula.js`（`renderFormulaInto`）双通道导出（window.global + node）；scene.js 私有 `appendFormula` 已删除，grep 契约锁定 `renderToString` 全仓前端只在 formula.js 出现。**vendor 本地化未做**（涉及 CDN 资产落库与字体文件，独立小任务），TODO 留在 scene.html
- [x] **3-B-3** 交互 = 播放/暂停/重播本页（已拍板砍掉撤销/重做）。OpenMAIC `whiteboard-history.tsx` 的快照栈设计**记录在案不实现**——未来若做教师端编辑场景再启用
  - ✅ 2026-09-13 完成：scene 页白板区「播放讲解/暂停/继续/重新播放」单按钮 + 「重播本页」按钮（开播后出现）；3-C 引擎的 `stop()`/`pause()`/`resume()`/`replay()` 全部接上；**3-C-4 翻页联动同步落地**（`showScene` 开头 `stopPlayback()`：引擎 stop + 令牌失效 + 字幕复位，grep 契约锁定）；静态资源缺失时守卫退回纯翻页（Phase 1 行为兜底）
- [x] **3-B-4** 元素入场动画：CSS transition（参考 OpenMAIC 的 450ms 入场 + 50ms stagger 级联），参数进 3-E 常量
  - ✅ 2026-09-13 完成：keyframes 在 scene.css，duration/delay 由 whiteboard.js 按时序常量内联设置（当前 450/50ms 对齐 OpenMAIC，JS 侧镜像标注 3-E 收口）
  - ✅ **测试**：`tests/js/whiteboard.test.cjs` 10 用例（常量镜像/clamp/图形 path/缩放/四类动作规格映射/非法动作拒绝——DOM 组装不进 node 单测，行为由 3-G 灰度人工复核）；`tests/test_whiteboard_wiring.py` 9 用例 grep 契约（脚本加载顺序/翻页联动/共享公式/LLM 文本安全约定）。全量 **1838 用例通过**

### 15.4 3-C：播放引擎/状态机

- [x] **3-C-1** 状态机**三态 `idle`/`playing`/`paused`**（纯 JS 模块，不依赖框架）——OpenMAIC 第四态 `live`（discussion/AI 同学追问）不在 Phase 3 范围。转移：start（idle→playing）/ pause / resume / stop（任意→idle）
  - ✅ 2026-09-13 完成：`web/student/playback.js`（`createPlaybackEngine`，无 DOM 依赖，renderer/speechPlayer/scheduler/now 全部依赖注入——3-B 白板与 3-D 音频未就位也能独立测试）
- [x] **3-C-2** 调度：**事件驱动 + setTimeout，不用 rAF**（OpenMAIC 同款）：speech 动作等音频 `ended`（无音频 → `estimate_speech_duration_ms` 估算计时器）；`wb_*` 动作执行（含 `WB_DRAW_MS` 级动画等待）后推进下一个。**核心并发机制照抄 `playbackGeneration` 代数令牌**：pause/stop/翻页使令牌失效，所有旧异步回调先查令牌再执行——没有它，"暂停后旧 setTimeout 又画出下一个图形"这类 bug 必现
  - ✅ 2026-09-13 完成：代数令牌（generation）贯穿全部异步续点；wait 记录 startedAt/durationMs 支持 pause 剩余时间语义（不重播已播动作、不跳动作）；三个"promise 在暂停期间定局"的边界显式建模——音频 ended/失败于暂停中（settled/outcome 状态，resume 接管推进）、wb execute 于暂停中 resolve（inFlightExecute 标志，resume 补 0 等待）；未知动作类型告警跳过（引擎侧白名单镜像，3-F 过滤的兜底）
- [x] **3-C-3** 语音同步优先级（对齐 OpenMAIC）：有 `audio_id` 且加载成功 → `ended` 事件驱动；否则估算计时器（字幕同步推进）。**音频时长不参与调度**（15.5 原文已修正）
  - ✅ 2026-09-13 完成：三级路径 = audio_id 且 play 成功 → ended 驱动 / play 失败或显式 false → 估算兜底 / 无 audio_id → 估算；`estimateSpeechDurationMs` 内置（CJK 占比>0.3 → max(2000, 字数×150)，否则按词 240ms，除以 speed，对齐 OpenMAIC timing.ts）——3-E 收口后由服务端下发同源常量覆盖，JS 内置值标注为过渡态
- [x] **3-C-4** 翻页联动：actions 是 scene 级，翻页 = stop + 令牌失效 + 音频停止；重播本页 = stop 后从头重放
  - ✅ 2026-09-13 完成：引擎侧 `stop()`/`replay()`（replay = stop + start + renderer.clear）已就绪并测试锁定；scene.js 翻页接线已在 3-B 落地（`showScene` 开头 `stopPlayback()`）
  - ✅ **测试基建（本任务新增决策）**：时序正确性用 **node:test 零依赖真测试**锁定（`tests/js/playback.test.cjs` 14 用例：乱序/重叠/令牌失效/剩余时间暂停恢复/语音三级路径/重播/渲染失败跳过/估算函数），`tests/test_playback_engine_js.py` pytest 包装进 pre-push 门禁（无 node skip，对齐 PG 集成测试惯例）——grep 契约测试锁不了行为，这是仓库首个 JS 行为测试

### 15.5 3-D：语音合成集成

- [x] **3-D-1** 供应商：**MiniMax TTS 单供应商**（事实依据：OpenMAIC 注册表内已有 `minimax-tts`，speech-2.8-hd 等模型；CogEdu LLM 已用 MiniMax，**零新增供应商**）。封装 Protocol 接口（对齐 presentation 包 LLM 注入同款模式，不绑具体 SDK）：`generate(text, *, voice, speed) -> TTSResult{audio_bytes, format}`——**不含时长**（OpenMAIC 同款，理由见 3-D-2）；v1 不做多供应商注册表
  - ✅ 2026-09-13 完成：`cogedu/presentation/tts.py`（`TTSConfig.from_env`（COGEDU_TTS_API_KEY/BASE_URL/MODEL/VOICE）+ `SupportsTTS` Protocol + `MiniMaxTTSClient`（T2A v2，hex 回传解码，httpx transport 可注入供 MockTransport 测试）；API 形态参考 OpenMAIC `tts-providers.ts` generateMiniMaxTTS，Python 重写零运行时引用）
- [x] **3-D-2** 时长获取：入库时**字节嗅探测一次**（WAV RIFF chunk 走查 / MP3 Xing/Info 帧数优先 + CBR 估算兜底；靠 magic bytes 不信任 format 声明；失败返回 `None` 优雅降级——OpenMAIC `audio-duration.ts` 约 330 行的思路，Python 重写），存库供记录/未来导出；播放调度不消费（3-C-2）
  - ✅ 2026-09-13 完成：`cogedu/presentation/audio_duration.py`（`measure_audio_duration(bytes) -> int|None`；WAV 截断/空 data 不猜数返回 None）；测试样本全合成（struct 拼 RIFF / 手工 MP3 帧头 + Xing tag），无音频资产依赖
- [x] **3-D-3** 长文本拆分：MiniMax 单次合成限长查官方文档后定常量；超限按 `。！？!?；;：:\n` → `，,、` → 硬切三级降级，拆成多个连续 speech 动作（`{action_id}_{i}`，各自独立音频、不做字节拼接，OpenMAIC `splitLongSpeechActions` 同款）
  - ✅ 2026-09-13 完成：`split_speech_text` + `split_speech_action`；限长常量默认 2000 字符（`COGEDU_TTS_MAX_TEXT_CHARS` 可配，**官方限长未在线核实**——保守值 + env 口径，3-G 灰度时以真实长文本核实修正）
- [x] **3-D-4** 存储与幂等：`presentation_audio` 表（`audio_id` PK、`scene_id`、`action_id`、`audio` BLOB、`duration_ms` 可空、`format`、`created_at`，双后端模式入 `presentation_store.py` + `pg_schema.py`）；`audio_id = tts_{scene_id}_{action_id}` 幂等键，已存在跳过（留 force 重生成口）
  - ✅ 2026-09-13 完成：表入 `PRESENTATION_SCHEMA_SQL`（BLOB 列经 `_schema_sql(backend)` 按后端翻译 SQLite BLOB / PG BYTEA——两方言通用其余不动）；`AudioRecord` dataclass + `save_audio`（幂等覆盖，对齐 save_scene 口径）/`get_audio`（adapter dict 行取值）/`get_scene`（归属校验数据链）；store 双后端奇偶测试通过。**端点同步落地**：`GET /api/presentation/audio/{audio_id}`（async，audio→scene.student_id → `require_student_access` 单一入口权威校验；孤儿音频 404；media type 映射 mp3→audio/mpeg）
  - ✅ 前端半环（3-D 播放侧）：scene.js `createSpeechPlayer()`（audio_id → 带 Bearer + student_id 的 GET → blob 会话内缓存 → `<audio>` ended 事件驱动；失败 reject → 引擎回落估算计时器）注入 3-C 引擎
- [x] **3-D-5** 降级链（对齐"宁可明确降级不静默"约定）：无音频 → **静音 + 估算计时器**（字幕推进，UI 明示"语音生成中/不可用"）；**v1 不做浏览器 Web Speech API 兜底**——OpenMAIC 为此写了约 350 行（Chrome 15s 截断需分句、`voiceschanged` 竞态、Firefox 暂停恢复），K12 校园设备兼容性参差，收益不抵复杂度
  - ✅ 2026-09-13 完成：引擎三级路径（3-C）+ 前端 speechPlayer 失败回落 + 字幕位（3-B）齐备，Web Speech API 未引入
  - ✅ **3-F-5 提前落地（2026-09-13，随 3-D 一并提交）**：实施中查 `require_student_access` 实现发现 `/scenes` 缺口比 v0.6 记录的更严重——不止"只验已认证"，**真实学生 UI 会 403**（scene.js 的 body 不带 student_id，dependency 拿不到 target 即拒绝；灰度脚本恰好带了才没暴露）。已修：`ScenesRequest.student_id` 必填 + 端点内 outline 归属校验（outline.student_id ≠ 请求者 → 403）+ scene.js 补带 student_id；real_auth 测试锁定（本人 200 / 他人 outline 403 / 身份不一致 403）

### 15.6 3-E：时间常数单一数据源（借鉴 OpenMAIC `choreography/timing.ts` 模式）

- [x] **3-E-1** **跨语言单一数据源**（OpenMAIC 没有的问题，CogEdu 特有）：Python 生成侧要算 `estimated_duration_ms`，JS 播放端要用同一套数字，两份手抄常量必然漂移。方案：常量定义在 `cogedu/presentation/timing.py` 纯模块（不 import web/fastapi，对齐 `timing.ts` "不依赖 React/DOM" 的边界纪律），随 `POST /scenes` 响应（或 `/api/presentation/timing` 端点）下发给前端，**JS 侧不硬编码**。这同时为未来"导出可播放的视频版课堂"保留正确起点（OpenMAIC 的设计动机：app 运行时与导出器必须同一组数字，否则导出视频静默漂移）
  - ✅ 2026-09-13 完成：`cogedu/presentation/timing.py` 纯模块（权威源）+ `GET /api/presentation/timing` 端点下发（snake_case payload）+ scene.js `fetchTiming()` 注入 engine/whiteboard（失败 console.warn 不阻塞讲解）。**JS 兜底镜像的取舍**：下发失败时页面仍需可用，playback.js/whiteboard.js 保留内置默认值，但镜像数值被 `test_presentation_timing.py` 与 Python 权威值逐一锁定（drift-lock）——允许镜像，不允许漂移
- [x] **3-E-2** 常量初值（参考 OpenMAIC `timing.ts` 实测值，收口时可调）：`WB_DRAW_MS=800`、元素入场 450ms / stagger 50ms、`estimate_speech_duration_ms`（CJK 占比 >0.3 → `max(2000, 字数×150)`；否则按词 240ms/词）等；纯常量与按内容长度计算的函数型常量分列
  - ✅ 2026-09-13 完成：7 常量 + `estimate_speech_duration_ms`（与 3-C 引擎 JS 侧同口径，node 测试与 pytest 测试断言同一组期望值）+ `estimate_action_duration_ms`（3-F 填 `estimated_duration_ms` 的直接入口；wb_* → WB_DRAW_MS，speech → 估算）；测试 17 用例（payload 契约/估算口径/镜像漂移锁定/端点/前端接线 grep）。全量 **1904 用例通过**

### 15.7 3-F：生成侧改造（扩展 Phase 1 的呈现引擎）

- [x] **3-F-1** prompt 扩展：`build_scene_messages` 增加动作序列输出段——LLM 在 Scene JSON 内输出 `actions` 数组，few-shot 给含 `wb_draw_latex`/`wb_draw_line` 的完整示例（参考 OpenMAIC `system.md` 的 "MUST output JSON array + 完整示例" 模式）；动作类型说明独立成 prompt snippet 便于迭代
  - ✅ 2026-09-13 完成：system prompt 增加五动作字段口径 + 坐标系（1000×562.5 原点左上）+ 禁输出 action_id/estimated_duration_ms/audio_id（服务端统管）+ 求根公式 few-shot 示例；speech 按 50~150 字讲述节奏分段
- [x] **3-F-2** 容错：整体 parse 失败走现有 `call_with_retry` → `_degraded_scene` 路径不变；**动作级容错新增**——白名单外动作类型丢弃 + warning 留痕（不整场失败）、坐标 clamp（3-A-2）、`audio_id` 回填不参与重试比对。`parse_llm_json`（json_repair 管线）对内嵌数组同样生效，直接复用
  - ✅ 2026-09-13 完成：`_parse_actions` 管线（白名单过滤 → TypeAdapter 校验失败丢弃 → 坐标 clamp+warning → action_id 重分配 `f"{scene_id}_a{n}"` → duration 按 timing.py 估算 → 超长 speech 三级拆分（拆出子动作 `_0/_1` 时长逐段重估））——管线内 warning 全部进 `scene.warnings` 留痕；降级场景不带动作（模板路径不受影响）；`text` 为空仍整场失败走 retry
- [x] **3-F-3** TTS 异步补齐编排（已拍板）：`generate_scenes_for_outline` 返回后，对含 speech 的 scene 起**进程内后台任务**（asyncio task，低并发逐条）预生成回填 `audio_id` 并更新落库。**诚实注记**：进程重启丢任务 = 该场景永久走降级路径，v1 接受（播放端降级兜底完整）；不做持久化任务队列
  - ✅ 2026-09-13 完成：`presentation_service.backfill_scene_audio`（幂等键已存在跳过合成 / 合成失败该动作保持 None 不中断 / 落库失败不回填 / `save_scene` 幂等覆盖回填 payload）+ `_maybe_spawn_tts_backfill`。**实现注记**：计划写 asyncio task，但 `/scenes` 是同步端点（线程池无事件循环），改用 daemon 线程——语义等价（进程内/逐条/重启丢失可接受），已记录。未配置 `COGEDU_TTS_API_KEY` 时 `get_tts()` 返回 None 静默跳过（speech 走降级链）。端到端集成测试：POST /scenes 响应后轮询到 audio 落库 + scene payload 回填
- [x] **3-F-4** `GENERATION_MAX_TOKENS` 拆分：scene 生成器独立常量 + env 可配（动作序列让输出显著变长，4096 共享值需重估）
  - ✅ 2026-09-13 完成：`_scene_max_tokens()`（`COGEDU_PRESENTATION_SCENE_MAX_TOKENS` 覆盖，默认沿用全局 4096；非法值 warning+兜底对齐 RetryPolicy 口径）。默认值是否上调留 3-G 灰度实测输出长度后决定
  - ✅ 测试：`tests/test_scene_actions.py` 17 用例 + `tests/test_tts_backfill.py` 7 用例。全量 **1928 用例通过**
- [x] **3-F-5** 顺手补鉴权缺口：`POST /scenes` 改为按 outline 归属校验（取 outline 的 `student_id` 过 `require_student_access` 同款语义），消除"任何已登录用户可为任意 outline 生成场景"的越权面
  - ✅ 2026-09-13 已提前落地（随 3-D 一并提交，实施中发现真实学生 UI 403 问题，见 15.5 3-D-5 注记）

### 15.8 3-G：端到端验证

- [x] 自动化测试（延续 `tests/test_presentation_*` 布局）：动作 schema 穷尽性/白名单过滤/坐标 clamp；**时序正确性**（不乱序、不重叠、pause/stop/翻页后令牌失效无残留回调）；TTS 拆分边界/字节嗅探失败降级/幂等键；`actions=None` Phase 1 旧场景兼容回归；`/scenes` 鉴权矩阵（含 outline 归属越权 403）；timing 常量下发契约
  - ✅ 2026-09-13 完成并随各任务铺开（test_presentation_actions / playback.test.cjs + whiteboard.test.cjs 24 例 JS 行为测试 / test_presentation_audio_* / test_tts* / test_scene_actions / test_tts_backfill / test_presentation_timing / test_whiteboard_wiring）
- [x] 灰度：`scripts/canary_phase3_whiteboard.py` 照 1-G/2-E 骨架（真实进程 + 真实登录 + 汇总布尔退出码 + stdout 人工复核）。**TTS 真实调用可配置跳过**（环境开关走估算路径，验证时序主干），真实 TTS 另做 2-3 条小样本验证（音质/时长嗅探正确性/中文与数学符号读法）
  - ✅ 2026-09-13 通过：2 案例（math.quadratic / physics.motion）真实 LLM 全链路——10 场景全部 schema v2 + 含动作序列、零降级零 warning、timing 下发正常、`/scenes` 走新鉴权契约、行为回写回归通过、theta K 上移（-0.331→-0.113）。**TTS 段 skipped**（未配置 `COGEDU_TTS_API_KEY`，降级链即默认路径）。**灰度发现并修复 2**（均已落码）：① 4096 max_tokens 被 thinking 耗尽产出空文本 → scene 默认上调 16384；② 长输出超共享客户端 30s 超时 → scene 独立 120s 超时（chat kwargs 透传 SDK）。另修脚本自身 3 处（模块路径/二进制响应解析/theta 证据量口径）
- [x] 人工复核验收点：挑 2-3 个含公式讲解场景（如"一元二次方程求根公式"）走全链路 LCA intervention → 含动作序列的场景 → 白板渲染+语音播放——画图与讲解节奏对齐、公式清晰度、静音降级路径观感
  - ✅ 2026-09-14 全部完成（维护者实测）：① 真实 TTS 小样本（配 key 后合成/播放/读法通过，顺带抓出时长嗅探采样率 bug）；② 页面观感 5 页逐页通过（白板渲染/播放暂停/重播/翻页/字幕），期间连续暴露并修复 4 个测试环境无法触及的真缺陷——sid 解析未接登录身份、前端 API base 写死主机名、scene api 助手无凭证、KaTeX CDN 失败致公式源码直出（均已修复 + 契约锁定 + CHANGELOG 记录）；③ 复看通道补齐（只读端点 + `?outline_id=`，生成结果不再因页面中断浪费）。**Phase 3 具备全量发布条件，2026-09-14 全量发布**
- [x] 回写扩展决策：v1 **不加 action 级埋点**，`scene_viewed`/`scene_completed` 粒度够用（行为信号最小化，对齐 1-F 语义决策）
  - ✅ 2026-09-13 确认（灰度行为回写按现有粒度回归通过）

---

**Phase 3 收官（2026-09-13，全量发布 2026-09-14）**：3-A 动作模型 + 3-B 白板渲染 + 3-C 播放引擎 + 3-D 语音合成 + 3-E 时间常数收口 + 3-F 生成侧改造 + 3-G 端到端验证全部完成；全量 **1949 用例通过**（含 node:test JS 26 例）。三项人工验收（动作序列复核 / 真实 TTS 小样本 / 页面观感）均由维护者完成，期间发现并修复 6 个测试环境无法触及的真缺陷（时长嗅探采样率位、sid 解析、API base 写死、api 助手无凭证、大纲 30s 超时、KaTeX CDN 失败 + latex 定界符）。**灰度实证的生成参数修正已落码**（scene max_tokens 16384 + 大纲/场景独立 120s 超时）。**已知体验债务**（待办，§10 #10）：生成全程 10~25 分钟黑盒等待（串行生成 + 超时重试），需逐场景渐进落库/渲染；生成结果暂无服务端缓存复用（每次点讲解重新生成）。

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
