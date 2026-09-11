# belief.py → CogEdu FastAPI 迁移映射表

> 背景说明（重要）：这份文档最初设想是"列出 belief.py 里绕过 Runtime 的调用点，逐条替换"，但核实代码后发现前提不成立——`submit_answer` 的核心状态更新已经通过事件总线正确路由到 Runtime（见 `kernel-baseline-notes.md` 第 2 节）。所以这份文档的实际作用调整为：**把 `belief.py`（806 行，历经多个版本的 bug 修复和功能演进）里积累的具体业务行为逐条列出来，作为在 CogEdu 新 FastAPI 实现里"不能遗漏"的行为对照表**。重写一个复杂度不低的文件时，最大的风险不是"不知道该调用什么 API"，而是"不小心弄丢了某条经过实战检验的边界情况处理"。

## 1. `submit_answer`：完整行为清单

这是学生提交答案的核心入口，以下按代码里出现的顺序列出每个行为点、现在的实现方式，以及新实现时要注意的地方。

| # | 行为 | 现有实现方式 | 新实现时的注意事项 |
|---|---|---|---|
| 1 | 获取/创建学生的 engine+state | `_get_or_create_student(student_id)` | 直接保留逻辑，新版本可以考虑通过 Runtime 提供的统一 factory 方法获取，而不是 Web 层自己维护 |
| 2 | 注册题目的 MIRT 参数 | 查 Q 矩阵（`get_question_detail`），如果有 `a_specialized` 字段，构造 `MIRTItemParams` 并调 `engine.l2.register_item()` | **这是三处需要决策的直接调用之一**（见第 3 节），迁移时要明确决定它是否也要走 Runtime |
| 3 | 缺失 `correct_answer` 时的回填 | 如果调用方没传，从 Q 矩阵读取 | 保留 |
| 4 | Bloom 层级字符串映射 | `"L1"~"L6"` 映射到 `BloomLevel` 枚举，默认 `APPLY` | 保留，注意默认值语义 |
| 5 | Partial credit 派生逻辑 | 优先用 `score`（0.0-1.0）；老调用方只传 `correct=True` 时，fallback 为 `score=1.0`；`score >= 0.6` 派生 `correct=True` | **容易在重写时遗漏的兼容逻辑**，如果 CogEdu 不再需要兼容"只传 correct 不传 score"的老调用方，可以简化，但要主动确认是否还有调用方依赖这个 fallback |
| 6 | 自评置信度采集 | `self_confidence`（0.0-1.0，可选），**只落 history_entry + event_log payload，本期不参与任何引擎更新** | 保留这个"只采集不使用"的现状，不要误以为它应该参与 belief 更新——这是原始代码里明确写的当前范围限制 |
| 7 | 答题时延采集 | `response_time_sec`，标注为"F-09 候选信号，H1 数据依赖" | 说明这个字段是为将来的验证工作（H1）准备的数据基础，保留采集但不要臆测它现在参与了什么计算 |
| 8 | 核心状态更新 | `_update_via_plugin_or_legacy`：事件总线优先，无订阅者时 fallback 直接调用 | **这是设计良好的部分，原样保留这个模式**，见 `kernel-baseline-notes.md` 第 2 节 |
| 9 | 持久化 | `save_student_state`，try/except 包裹，失败时 `_log.warning` 并返回 `persisted=False` 给前端 | **这里有一个历史 bug 的教训**：曾经"silent pass"吞掉保存失败，导致学生数据丢失且前端不知情（注释提到"Bisen 反馈 4 道题没存"的真实事故）。新实现**必须保留"失败要让前端知道"这个行为**，不能图省事直接吞异常 |
| 10 | 误概念读取 | 从 `updated_state.C.misconception_hits` 里找当前 `problem_id` 对应的最新一条 | **也有历史 bug 教训**：曾经在 `belief.py` 末尾独立调用误概念检测，只返回给前端、没有 append 到 state，导致数据库里的误概念历史永远是空的（"BUG 2.2"）。新实现要从 `updated_state` 读，不要自己再调一次独立检测 |
| 11 | A2 误概念 reconcile | 用 session 窗口的历史记录（`engine.feature_extractor.get_history`）构造 `problem_id → misc_id` 映射，按时间戳排序后调 `reconcile_for_student` | **这是三处需要决策的直接调用之一**（见第 3 节）。注意失败时的处理原则："防御性自检"——失败要 warning，但不能阻断主流程、不能污染 evidence_log |
| 12 | 响应构建 | 返回 `correct`（派生）、`score`、`theta`（5 维）、`misc_triggered`/`misc_id`/`misc_confidence`、`c_discount_factor`、`persisted` | 保留字段结构，前端很可能依赖这个具体的响应 shape，改动前确认前端调用方是否也在 CogEdu 里同步重写 |

## 2. `get_student_state`（428-556 行）：完整行为清单

已逐行审查完毕。这是一个**纯只读查询函数**，组装"7 组件完整信念状态"给前端展示用，不涉及任何状态变更，也不涉及"是否要走 Runtime"的决策问题——迁移时可以放心地实现成一个纯查询接口。但里面有两处和 `submit_answer` 同源的"防御性容错"历史教训，具体行为点如下：

| # | 行为 | 现有实现方式 | 新实现时的注意事项 |
|---|---|---|---|
| 1 | 5 维（K/P/S/C/X）的 confidence/se | 遍历 `state.{K,P,S,C,X}`，从 `DimensionState` 读 `confidence`/`se` | 保留 |
| 2 | TC（阶段性变革）状态列表 | 从 `state.C.tc_states` 读，含 `status`/`progress`/`confidence`/`irreversible` | 保留 |
| 3 | LearningDNA | 有默认值 fallback：`input_preference` 缺省"示例驱动"，`feedback_preference` 缺省"即时反馈" | 保留这两个具体的中文默认值文案，不要改成别的占位符——前端可能已经依赖这个默认展示 |
| 4 | Trajectory 全量历史 | `state.trajectory.last_n(500)`，**注意是全量（上限 500），不是早期版本的 last_n(10)** | **历史教训**：早期版本只显示最近 10 条，用户反馈"应该按实际数量显示"才改成 500 上限的全量。新实现不要图省事又退回到"只显示最近几条" |
| 5 | Trajectory 序列化容错 | 包在 try/except 里，失败时 `_log.warning` + 返回空列表，**不是静默吞掉** | **历史教训**：早期版本是 `except: pass` 静默吞异常，同样是"Bisen 反馈答了题没存也看不到"这类问题的根源之一。新实现必须保留"失败要 warning，不要静默"这个约定 |
| 6 | Warm-up 状态机字段 | `engine.warmup_progress(student_id)`，纯只读代理到 `ObservationEngine` | 已确认无状态变更，可以放心实现成查询接口 |
| 7 | Bloom 距下一层距离 | `bloom.distance_to_next_layer()` | 保留 |
| 8 | 探针题状态机字段 | `engine.probe_progress(student_id)`，同样是纯只读代理 | 已确认无状态变更 |
| 9 | Motivation Profile 序列化容错 | 同样包 try/except，失败时 fallback 到中性值（`frustration=0.0`/`engagement=0.5`/`confidence=0.5`），而不是报错或返回空 | 保留这个"失败时给中性默认值而不是报错"的具体处理方式——这是一个产品体验上的选择（前端总能拿到一个可展示的值），不只是技术容错 |
| 10 | 响应字段命名 | `theta`/`theta_cov_diag`/`theta_confidence`/`theta_se`/`bloom_profile`/`bloom_layer_distance`/`tc_states`/`learning_dna`/`trajectory`/`misc_history`（固定空数组，说明写着"在 trajectory snapshots 中"）/`overall_confidence`/`motivation`/`c_discount_factor`/`**warmup`/`**probe` 展开合并 | 前端很可能直接按这些字段名取值，重写时字段名建议原样保留，除非确认前端也在同步重写且愿意改字段名 |

**这里有个跨函数的共性模式值得单独强调**：`submit_answer` 和 `get_student_state` 里一共出现了三次"try/except + 记录 warning + 返回安全默认值/明确失败标志"的写法（持久化失败、trajectory 序列化失败、motivation 序列化失败），而且**至少两次是从"早期版本静默吞异常导致用户数据看似丢失"这个真实事故里改过来的**。这应该被当作 CogEdu 新代码库的一条通用编码约定，建议写进 `CLAUDE.md` 的协作规范里：**任何可能失败的序列化/持久化操作，宁可返回明确的失败信号或安全默认值并记录 warning，也不要静默吞掉异常**。

## 3. 三处需要决策的直接调用

这三处是 `kernel-baseline-notes.md` 第 2 节提到的、真正意义上"没有经过 Runtime"的操作，每一处都需要在 CogEdu 重写时明确做一个决定，不要不假思索地照抄现状，也不要不假思索地"一刀切全部改成走 Runtime"：

| 操作 | 现状 | 决策要点 |
|---|---|---|
| `engine.l2.register_item(item_params)` | 直接改 engine 内部的题目参数注册表 | 这算不算"改变认知状态判断"？如果只是注册题目的静态参数（MIRT 区分度/难度），更接近"配置加载"而非"状态变更"，可以论证不需要走 Runtime。但如果同一题目的参数会被多次注册、存在覆盖顺序问题，可能需要更严谨的处理 |
| `_get_db().save_student_state(...)` | 直接写数据库 | 这是纯持久化 I/O，Runtime 的职责边界通常是"业务逻辑"而不是"落盘"，可以论证维持直接调用是合理的架构分层，不强行套进 Runtime |
| `reconcile_for_student(...)` | 直接读写数据库的误概念证据 | 这个更接近"状态相关的推断结果写入"，比前两者更值得认真评估要不要纳入 Runtime 统一入口——它实际上是在更新一种"证据"，和 Evidence Engine 的职责有重叠 |

## 4. 建议的新实现结构（供参考，不是唯一方案）

```python
# web/api/belief.py (FastAPI 版本，示意)

@router.post("/answer")
async def submit_answer(payload: SubmitAnswerRequest) -> SubmitAnswerResponse:
    student = await get_or_create_student(payload.student_id)
    # 题目参数注册——决策：是否经 Runtime，见第 3 节
    await register_item_params_if_needed(payload.problem_id)
    obs = build_observation(payload)  # 封装第 4-7 行为点的转换逻辑
    updated_state = await update_belief_via_event_bus(student, obs)  # 保留事件驱动模式
    persisted = await persist_state_with_explicit_failure_signal(student, updated_state)  # 保留"失败要暴露"教训
    latest_misc = extract_latest_misconception(updated_state, payload.problem_id)  # 从 state 读，不重复检测
    await reconcile_misconceptions_if_needed(student, payload.problem_id)  # 决策：是否经 Runtime
    return build_response(updated_state, payload.score, latest_misc, persisted)
```

这只是示意结构，实际实现时每个函数内部要对照第 1 节的完整清单，确认没有遗漏任何一条已经过实战检验的行为。
