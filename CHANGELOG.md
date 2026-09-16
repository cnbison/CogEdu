# Changelog

本文件记录 **CogEdu 自身**的版本演进。内核代码复制自 ECOS（v0.99.4，commit `9cdacab`，2026-09-11），ECOS 的历史版本记录不在本文件范围内——如需追溯内核的历史设计决策，见 `discussions/` 收录的设计文档与 ECOS 仓库。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

### 2026-09-16 — UI-R-1 SidebarShell 工作台壳层完成（维护者验收通过，启动 UI-R-2）

学生端骨架一次换：底部 5-Tab 退役，左侧栏三形态接管。设计稿见 `docs/ui-r-0-信息架构设计稿.md` §11 UI-R-1，硬边界（Phase 3 vanilla 三模块零改动 / 路由表不变 / 纯前端无后端改动 / dist 不入库）全部守住。

**新增文件**：

- `web/frontend/src/student/components/navTree.ts` — 单一导航源。学习 / 工具 / 报告 / 账户 四组，8 个现有路由全部升一级导航（修复 Scene/Report/GuardianLinks 栏外不可达）；工具组含 4 个 Phase 4-6 槽位（诊断 / 资源 / 探索 / 练习，`enabled: false` 占位不渲染可点链接）——上线时改常量即可点亮侧栏与抽屉，不需改组件代码。
- `web/frontend/src/student/components/SidebarShell.tsx` — 工作台容器。`useMediaQuery` 派生三形态：`wide (≥1024px)` 220px 展开侧栏 + 文字 label；`narrow (768-1023px)` 64px 图标栏（title/aria-label 替代文字）；`drawer (<768px)` 侧栏隐藏，顶条汉堡按钮唤出抽屉。顶条跨三形态常驻：hamburger（仅 drawer）+ brand + 当前页 title（最长前缀匹配的 NavItem label）+ username + 退出按钮（设计稿 §3 顶条形态落地）。
- `web/frontend/src/student/components/DrawerNav.tsx` — 移动抽屉。复用 navTree，同一棵导航树；Esc 关闭 / 遮罩关闭 / 链接点击自动关闭；打开时 body 锁滚动。Phase 4-6 槽位渲染为 `<span aria-disabled>` 不进 router。

**修改文件**：

- `web/frontend/src/student/App.tsx` — 删 `<header className="student-topbar">` 与 `<nav className="bottom-nav">`；Routes 整段用 `<SidebarShell username={username}>` 包；路由表（8 项 + 复看参数路由）零改动。
- `web/frontend/src/student/index.css` — 删旧 `.student-topbar` / `.bottom-nav` / `@media (max-width: 720px)` / `@media (min-width: 721px)`；新增 sidebar shell 三形态 grid 布局 + drawer 样式 + 新断点 768 / 1024；`.shell-content` 用响应式 padding 不带 max-width，让各页自管宽度。
- `web/frontend/src/components/ui/icons.ts` — 单点扩 `Menu`（汉堡按钮），既有边界不动。
- `tests/test_frontend_react_wiring.py` — 新增 `TestSidebarShellWiring` 8 例：单源 / 8 路由全列 / 4 槽位 disabled / 旧 .bottom-nav & .student-topbar 已退役 / SidebarShell 包住 Routes / 断点 768/1024 非 720/721 / shell-content 不带 max-width / Phase 3 vanilla 挂载继续生效。

**未在本步范围（明确边界）**：教师端 / 家长端 Shell（设计稿 §9 D4 拍板：Phase 4 评估）；scene.css `.wrap { max-width: 720px }`（白板破版心留 UI-R-2）；答题页双栏（UI-R-3）；其他页面宽幅适配（UI-R-4）；Phase 4-6 槽位点亮。

**测试**：全量 **1963 用例通过**（pytest + 1 skip；前一次 1955 → +8 新契约锁）；前端 vitest 55 例；node:test 25 例（playback 14 + whiteboard 11，Phase 3 vanilla 时序锁原样全绿）；构建产物三入口正常生成（dist 不入库）。

**下一步**：维护者在 iPad 横屏（≥1024）+ iPad 竖屏（768-1023）+ 手机（<768）三形态过一遍骨架；之后启动 UI-R-2 讲解场景页桌面布局（白板破 720 版心）。

### 2026-09-16 — UI-R-0 五项决策全部拍板（设计稿锁定，待启动 UI-R-1 施工）

**决策记录**（维护者逐项确认，见 `docs/ui-r-0-信息架构设计稿.md` §9）：

- **D1** 侧边栏分组：✅ 采用「学习 / 工具 / 报告」三组（学习组今天/答题/讲解/我在哪/成长 + 工具组诊断/资源/探索/练习预留 Phase 4-6 + 报告 + 授权/设置）
- **D2** 讲解页辅栏：✅ 字幕 + 大纲双栏（大纲缩略图便于跳页复看；768-1023px 时大纲折叠为抽屉）
- **D3** 手机降级形态：✅ 抽屉导航（与桌面同一套导航树，维护一套；底部 Tab 后续按需找回）
- **D4** 教师端 / 家长端：✅ 本轮不动（Phase 4 可视化时再评估统一 Shell）
- **D5** 一级导航命名：✅ 「讲解」（扩展性最好——涵盖生成、播放、复看三种用法）

设计稿状态由「待确认」升为「已拍板」。下一步：UI-R-1 SidebarShell 壳层（侧栏 + 断点切换 + 抽屉降级）——全站骨架一次换，按施工拆分 §11 UI-R-1..R-5 推进，每步独立可验收。本条目为决策记录，未动代码。

### 2026-09-16 — P0-1a 内容起草（三学科试点 Q 矩阵 + 误概念库，AI 起草待教师复核）+ UI-R-0 信息架构设计稿

**内容包（纯数据，6 个文件，未动代码，未接运行时）**：

- 三学科试点 Q 矩阵各 20 题（Bloom L1×4/L2×6/L3×6/L4×4，难度 0.20-0.85 爬坡）：数学「一元一次方程」七年级 / 物理「质量与密度」八年级 / 化学「物质的变化与性质」九年级（人教版口径）——每题 17 字段全量标注，含**逐题定制的 partial_credit_rubric 四档**（LLM judge 4 档判分依赖，原为空）、5D a_specialized、MIRT 参数、误概念触发、teacher_notes；
- 误概念库三份：物理/化学各 8 条新库（密度概念/单位换算/实验误差；变化判别/现象与结论等）+ 数学增补 M31-M33（去分母漏乘/去括号负号分配/同侧移项变号，顺延既有数学库 M1-M30），字段对齐 `MisconceptionEntry` 便于入库；
- **`verified` 全部 false**——AI 起草内容默认待教师复核（P0-2 可信度分级思想的落地姿态）；每条误概念均有 ≥1 道真陷阱探测题覆盖；全量结构独立校验通过（字段完备性/rubric 键位/MIRT 取值域/引用合法性）；
- 说明文档 `docs/p0-1a-试点内容说明.md`：文件清单、教师复核清单（含起草方自报的把握不足项，如化学 Q13 缓慢氧化超纲风险、物理 Q12 需配图）、接线 TODO 四项（qmatrix 加载器多学科化 / **judge prompt 硬编码"Python 老师"须学科化** / 误概念库入 MisconceptionEntry 模块 / Capability 注册）。

**UI-R-0 信息架构设计稿**（`docs/ui-r-0-信息架构设计稿.md`，待维护者确认后施工）：桌面优先 SidebarShell 工作台（≥1024px 侧栏+宽内容、768-1023 图标栏、<768 抽屉降级）——8 个现有路由全部升一级导航（修复 Scene/Report/GuardianLinks 栏外不可达）、Phase 4-6 扩展槽位（诊断/资源/探索/练习分组）、讲解页白板 16:9 全幅主舞台（尺寸策略反转为"先给高度反推宽度"）、答题页题答同屏双栏；硬边界：Phase 3 vanilla 三模块零改动、路由表不变、纯前端无后端改动。

### 2026-09-16 — 方向修正拍板：内容层复盘落地，Phase 4/5/6 顺延，启动 P0 内容验证冲刺 + UI 桌面优先重设计（双轨）

基于 `docs/cogedu-复盘与方向修正-2026-09.md`（代码级复盘：内容层是空的——Q 矩阵 32 题全占位、`DEFAULT_CAPABILITIES_LIST` 为 Python 5 条测试占位、呈现引擎无内容校验，系统从未用真实数理化内容跑过端到端）+ 深度复核（复盘 §7），与维护者确认四项拍板：

- **学科口径修正**：标准课标下初一无独立物理/化学课，"初一三门"改为按学科起始年级——数学「一元一次方程」（七年级）/ 物理「密度」（八年级）/ 化学「物质的变化与性质」（九年级）；
- **学生端设备口径**：横屏平板/电脑为主（手机次要）；
- **UI 路线**：桌面优先重设计（UI-R 独立立项，SidebarShell 工作台形态，参考 DeepTutor 只读借鉴）——依据：底栏 5 Tab 到信息架构上限（Scene/Report/GuardianLinks 已在栏外）、白板 16:9 画布被压在 720px 竖排版心、Phase 4-6 新功能无处安放；
- **P0 排期**：P0-1（内容闭环）先行、P0-2（呈现内容闸门）紧随。

深度复核的三处修正（代码级）：① P0-2 闸门**不能直接接** `dual_agent` belief_check（校验对象是 BeliefState 分布健康度，非生成内容），正确做法 = 借 HumanReviewTrigger 模式新建内容级校验器（LaTeX/数值/量纲程序化校验 → LLM 交叉校验 → 低置信教师复核队列）；② 内容工程量补充——LLM judge 4 档判分依赖 Q 矩阵逐题 `partial_credit_rubric`（现为空），试点内容三件套 = 真题 + 逐题 rubric + 误概念标注；③ judge 判分质量列为 P0-1b 同级评估对象（belief 更新建立在 judge 输出之上，垃圾进垃圾出）。

排期落档：方案文档新增**第 19 章**（P0-1a/UI-R 双轨并行 → P0-1b 汇合评估 → P0-2 闸门 → Phase 5 主体规模化 → Phase 4 → Phase 6；原 16/17/18 章任务清单不变仅时点后移，17.2 节 5-1 并入 P0-1a）；第 8 章路线图加修正注记；CLAUDE.md 当前状态同步。本条目为方向决策记录，未动代码。

### 2026-09-16 — UI 现代化全量发布：人工验收通过，删除 legacy 静态页（双轨终点）

维护者完成教师/家长端验收（学生端与讲解场景此前已过），四项决策拍板落地：

- **删除 legacy 静态页**：`web/student/{index,scene}.html`、`app.js`、`scene.js/css`、`guardian-links.html`、`web/parent/index.html`、`web/teacher/index.html`；**保留** `formula/playback/whiteboard.js` 三模块（React 挂载式整合的依赖，node:test 26 例继续锁行为）、`web/auth.js` + `web/login.html`（登录链路）、KaTeX vendor。**克隆后须先 `cd web/frontend && npm run build`**（dist 不入库，无构建时页面入口 404）——README 已标注；
- **契约测试双轨合并**：约 20 条 legacy grep 锁删除或迁移——`test_whiteboard_wiring.py` 重写（只锁幸存三模块的安全约定 + vendor）、`test_frontend_event_wiring.py` 重写（React AnswerPage 四事件接线）、`test_auth_api.py` / `test_parent_api.py` / `test_presentation_events.py` / `test_presentation_timing.py` / `test_presentation_endpoint.py` 的 scene.js/app.js/legacy 页锁逐条迁移到 React 源文件等价断言（锁语义不变）；`test_frontend_react_wiring.py` 19 例为主锁；
- 全量 **1955 用例通过**（1 skip：styles.css 孤儿文件测试自动跳过，该文件随下次清理）；
- **下一步：Phase 4**（证据链可视化增强，echarts/react-query 基座已就绪）。

### 2026-09-15 — 讲解记录入口（人工验收反馈）：/scene 改为"讲解记录 + 显式生成"，修复重复生成计费缺口

维护者验收提问暴露的缺口：复看只读端点早已存在但学生端**没有列表入口**——每次点"看 AI 讲解"都静默生成一份新大纲（重复计费），旧讲解没有任何入口可达。修复：

- **后端**：新增 `GET /api/presentation/outlines?student_id=`（router 级 `require_student_access` 查询串放行，学生仅本人）+ `PresentationStore.list_outline_summaries_by_student`（摘要形状：outline_id/title/created_at/scene_count，created_at 倒序，失败 → [] + warning）；pytest 4 例（空列表/缺参 400/摘要形状与排序/OpenAPI 注册）；
- **前端**：`/scene` 改为入口页——讲解记录列表（点行进 `/scene/:outlineId` 复看，0 页显示"未生成"）+ 显式"生成新讲解"按钮（点按钮才开始生成流程）；HomePage 入口按钮文案不变，落地即见记录页；vitest URL 契约 1 例；
- 生成页/复看页行为不变。已重建 dist。

### 2026-09-15 — 讲解页等待体验改进（人工验收反馈）：spinner + 预期时长 + 渐进出页完整形态

维护者验收反馈"选择 AI 讲解后只有一行静态文字，容易误以为没反应"（大纲阶段的同步 LLM 调用最长 120s）。三项改进：

- **等待态加 spinner + 预期时长提示**：大纲阶段提示"通常需要 1~2 分钟"；场景阶段提示"逐场景生成，已完成的会先显示"；
- **渐进渲染补成完整形态**（§10 #10）：此前生成期间只显示计数，现在大纲就绪且有落库场景即出页——已生成的页面可直接翻看，顶部横幅提示"后续页面生成中，完成后自动出现"，末页未生成完时"完成学习"按钮置为"生成中…"并禁用（防误触 scene_completed 回写）；
- 顺带确认：0 题冷启动学生可正常生成讲解（与做题数据无关，慢在同步 LLM 大纲调用）。

已重建 dist。

### 2026-09-15 — 修复：学生端 React 页整页裸排版（漏引学生端样式表）

维护者人工验收发现学生端首页无样式（三卡/底部 Tab/顶栏全部裸排版）。根因：`src/student/main.tsx` 只引了全局 `../index.css`，未引学生端专属的 `./index.css`（三卡 `.home-cards`、底部导航 `.bottom-nav`、顶栏 `.student-topbar`、答题页样式都在其中）——移植 ECOS 时该表自带 `@import "../index.css"`，引它即同时拿全局基础，但 9-D 搭学生端 shell 时漏了。修复引入 + `test_frontend_react_wiring.py` 加接线锁防回归。已重建 dist。

### 2026-09-15 — UI 现代化 9-G：真实进程灰度通过，四文档收官（待维护者人工验收）

- **真实进程灰度**：真实端口起服（FastAPI 5173）逐项通过——React dist 三入口托管（/ /student/ /parent/ /teacher/ 全部由 dist 接管）、vanilla 三模块 script 回落 `web/student/` 解析、KaTeX vendor CSS 服务、student SPA bundle（519KB）加载、/login /auth.js /api/version 正常；
- **四文档收官**：方案文档（§10 #9 施工完成 + #10 渐进渲染收尾 + 10.1.6 全任务标记）、CLAUDE.md 当前状态、README 当前状态段、本文件；
- 全量 **1964 用例通过**（pytest，含新增 React 接线锁 15 例）+ 前端 vitest 49 例 + node:test 26 例；
- **待维护者人工验收**（自动化不可替代部分）：教师/学生/家长/场景/授权五页真实观感 + 真实 LLM/TTS 链路的讲解生成与渐进渲染体验；验收通过后删除 legacy 兜底页（10.1.5 双轨终点）并全量发布，随后按第 16 章细化启动 Phase 4。

### 2026-09-15 — UI 现代化 9-F：契约测试双轨迁移（React 接线锁落档）

- 新增 `tests/test_frontend_react_wiring.py`（15 例）：legacy 锁语义逐条迁移到 React 工程源文件——
  - script 装载顺序 formula→playback→whiteboard + defer（挂载式整合前提）；
  - KaTeX 本地 vendor + 全源文件禁 CDN；
  - **React 源禁 `dangerouslySetInnerHTML`**（LLM 文本安全约定在 React 侧升级：legacy 锁 innerHTML 用途，React 侧连用都不用）；
  - auth 基座：Bearer 头 + `cogedu_token`/`cogedu_user` 键名互操作 + 401 → `/login?next=`；
  - sid 来源 = `learning_student_id`，禁 `prompt(` 手输 / 禁 `ecos_last_student_id`；
  - 无写死主机名（扫 ts/tsx/html）；presentation client 路径字面量（`?student_id=` 查询串约定）+ 1-F 回写事件 + 复看路由 `/scene/:outlineId`；parent 三块接线（roster/links/report）；
- 双轨并存：legacy 锁语义不变继续执行（兜底页接线完整），node:test 24 例原样全绿；
- **验证**：auth/whiteboard/event/presentation/timing/playback + React 接线合计 **110 契约用例通过**。

### 2026-09-15 — UI 现代化 9-E：家长端移植 + 学生端授权确认页（2-A/2-C 能力 React 化）

- **家长端**：ECOS 单页形态移植（roster 选择 + Engagement/Advice/FiveDOverview/InterventionHistory 四卡 + `?student=` URL 持久化，含原 ui/urlState 测试）；api 换共享 Bearer 基座。CogEdu 扩展两块：
  - **授权管理卡**（2-A）：发起绑定申请（5 项权限词汇表多选）、pending 撤回 / active 撤销；400/404/409 错误语义透出为用户可读文案；
  - **Word 报告下载**（2-C）：week/month/all 三档，`download_report` 授权语义（403 = 无权/已撤销）透出。
- **学生端**：新增 `/guardian-links` 路由（确认/拒绝/撤销，学生本人确认制）+ 设置页入口；对应 legacy `guardian-links.html` 的 React 化。
- vitest 49 用例全绿（新增 parent ui/urlState 移植测试）；build/lint/typecheck 全绿；
- **冒烟（正确隔离后）**：2-A 全状态机 pending→confirm→active→revoke 通过；active + 学习记录缺失 → 404、撤销后 → 403，权限语义正确。
- **过程修正**：早期冒烟误用不存在的 `COGEDU_DB` 环境变量导致 8 个冒烟用户 + 2 条授权记录写入真实开发库 `web/ecos.db`——已全部清理（保留维护者原有 `stu01`），正确环境变量为 `ECOS_DB_PATH`（auth_store.py:406）。

### 2026-09-15 — UI 现代化 9-D：学生端移植 + presentation 集成（挂载式白板宿主 + 渐进渲染）

- **学生端 6 页移植**（ECOS v0.99.5 前端）：Home/Answer/Where/Growth/Report/Settings + CodeEditor/MotivationPanel + types；api 适配三点：共享 Bearer 基座、`/api/judge` 422 结构化降级还原为 `JudgeResult`（CogEdu 契约是 HTTP 422 + `{judged:false, error_code, needs_rejudge}`）、`/api/answer` 9 字段响应契约（`persisted===false` 告警语义保留）；
- **presentation 集成（§10.1.3 挂载式拍板落地）**：vanilla 三模块 `formula/playback/whiteboard.js` **原样保留**（node:test 24 例与时序数值锁不动），经 `student.html` `<script defer>` 注入（顺序 = legacy 契约 formula→playback→whiteboard），React 只写宿主——`ScenePlayer.tsx`（createWhiteboard + createPlaybackEngine 依赖注入，speechPlayer 从 scene.js 平移为 blob 缓存 + ended 驱动，卸载必 stop 保代数令牌语义，模块缺失退回纯翻页）；KaTeX 继续本地 vendor；
- **ScenePage.tsx**：生成数据链平移（outline → scenes 202 → 3s 轮询 → not_started 幂等重触发 ≤2）+ 复看模式（`/scene/:outlineId` 路由参数，两个只读 GET）+ 1-F 回写（scene_viewed dwell / scene_completed，keepalive）+ **渐进渲染**（generating 期间每次轮询同步拉取已落库场景，边生成边出页——§10 #10 剩余项收尾）；
- `presentation/api.ts` 契约测试 6 例锁 URL/请求体形状（?student_id= 查询串、202 复用、blob 缓存、回写 body）；vite dev proxy 补 /student、/vendor；共享 auth 基座补 ApiError（status/body，供端点级降级契约）；
- **验证**：vitest 36 用例全绿；build/lint/typecheck 全绿；TestClient 冒烟（timing 7 字段、跨学生 403、无 token 401、缺失大纲 404）。

### 2026-09-15 — UI 现代化 9-C：教师端移植（7 端点 1:1，React 全链路首次打通）

- 自 ECOS v0.99.5 前端复制：`pages/RosterPage.tsx`（桌面表格/移动卡片双形态）+ `pages/StudentDetailPage.tsx`（5D radar / EvidenceChain 下钻 / CalibrationView / POMDP 诊断 / MisconceptionsCard）+ `components/EChart.tsx`（echarts 单封装，Phase 4 可视化复用）+ `components/ui/` 原子件（Icon/icons/iconMap/ClickableRow/CollapsibleSection/EmptyState/SectionHeader/uiHelpers/useMediaQuery，含原 vitest 测试）+ `api/types.ts`（响应契约，与 `web/api/routers/teacher.py` 逐字段核对一致）；
- `api/client.ts` 适配：getJson 换 CogEdu 共享 auth 基座（Bearer + 401 跳登录），端点路径不变；`TEACHER_ENDPOINTS` 契约测试原样保留；
- 路由：`/`→roster、`/students/:id`→详情（HashRouter），外层 RequireSession（teacher/admin）；
- **验证**：vitest 31 用例全绿（8 auth 基座 + 23 移植）；`build/lint/typecheck` 全绿；TestClient 冒烟 7 端点（教师 token，空库 404/200 形态符合契约）。

### 2026-09-15 — UI 现代化 9-B：认证与 API 基座（React 端接入 CogEdu 自建认证）

- `web/frontend/src/shared/auth.ts`：authFetch 统一请求入口（自动附 `Authorization: Bearer`，401 → 清会话 + 跳 `/login?next=`，next 含 HashRouter hash 回跳）+ login/logout/fetchSession + getJson/postJson helper；**localStorage 键名沿用 `cogedu_token`/`cogedu_user`，与 legacy `web/auth.js` 互操作**（双轨期两栈共享登录态）；
- `session.ts`（useSession，服务端权威校验 GET /api/auth/me，不只信本地缓存——legacy requireLogin 语义）+ `RequireSession.tsx` 会话守卫（角色矩阵：student/guardian/teacher/admin）；
- 三端 main 接 QueryClientProvider（staleTime 15s）+ HashRouter（家长端单页无 Routes，沿用 ECOS 形态）；三端 App 为会话守卫 + 占位内容，页面随 9-C/D/E 移植；
- **sid 来源切换**：React 学生端从登录身份 `learning_student_id`（/api/auth/me）取 sid，删除手输 sid 通路（清单 b #2，3-F-5 语义在 React 侧延续）；
- vitest 8 用例锁基座行为（Bearer 头/401 跳转/错误文案/登录往返/键名锁定）；
- **验证**：真实进程冒烟（建号→login→me→student 打 teacher 域 403→坏 token 401→logout 后同 token 401）全通；`npm build/lint/typecheck/test` 全绿。

### 2026-09-14 — UI 现代化（§10 #9）开工：9-A 前端工程骨架落地

- `web/frontend/` 新增 React 18.3 + Vite 6 + TS 工程（配置移植自 ECOS v0.99.5 前端，`../ecos/web/frontend/` commit `9cdacab` 工作树，只读复制自包含维护，无任何运行时/构建引用）：package.json（react/react-router/@tanstack/react-query/echarts/codemirror/lucide-react）、vite.config（三入口 teacher=index.html / student.html / parent.html 对齐 static_pages DIST_DIR 约定；dev 5174 proxy /api → 5173；`__APP_VERSION__` 编译期注入）、tsconfig 三件套、eslint flat config、index.css 全局样式（ECOS 原样）。
- 业务代码为骨架占位（三端各一个 AppShell 占位页），随 9-B..9-E 分任务移植。
- **验证**：`npm run build / lint / typecheck` 全绿（vite 6.4.3，dist 三入口产物正确）；TestClient 实测 `/`、`/student/`、`/parent/`、`/teacher/` 均由 `web/frontend/dist` 接管——`static_pages.py` 预留的 dist 优先逻辑零改动生效，legacy 静态页自动降为兜底。
- dist 构建产物不入库（`.gitignore` 维持全局忽略 `dist/`，拍板记录见方案文档 §10.1.7）。
- **契约测试双轨适配（3 处，锁语义不变）**：① `no_hardcoded_host` 扫描排除 `node_modules/` 与 `dist/`（本锁针对自有源文件，第三方依赖与构建产物不属扫描对象）；② 家长页两条内容锁改为"路由 200 + React 壳断言 + legacy 兜底文件接线完整性"——dist 存在后路由自动由 dist 接管，legacy 页降为兜底但须保持接线完整（直至 9-E 切换）。全量 **1949 用例通过**。

### 2026-09-14 — UI 现代化（§10 #9）细化落档（勘察完成，待确认后施工）

只读勘察 ECOS React 前端工程（`../ecos/web/frontend/`，React 18.3 + Vite 6 + TS）+ CogEdu web 层逐文件核对，三份清单写入方案文档 §10.1：

- **清单 a（结构盘点）**：三入口多页 SPA（HashRouter）+ react-query 扁平 key + echarts 单封装；教师 2 页/学生 7 页/家长单页四卡的完整组件分组与移植注意点（响应字段硬对齐、同端点多形状契约、ECOS 无认证等）；
- **清单 b（API 差异）**：**总体差异比预估小**——教师端 7 端点与 CogEdu `/api/teacher` 同名同义 1:1，学生端 8 端点全部同名存在；真正要新写的只有认证层（Bearer + 401 拦截 + `learning_student_id` 登录身份）、presentation 全新 8 端点（202 轮询协议/复看/音频/时序）、parent 权限扩展（guardian-links 状态机 + report 下载）三块；
- **清单 c（Phase 3 模块整合）**：拍板挂载式宿主——`playback/whiteboard/formula.js` 三个 vanilla 模块原样保留（保住 node:test 24 例与时序数值锁），React 写 ScenePlayer 宿主组件做依赖注入，KaTeX 继续本地 vendor；
- **托管衔接**：`static_pages.py` 预留的 dist 三入口约定与 ECOS vite 入口名天然一致，**无需改 app.py**；
- **施工拆分**：9-A 骨架 → 9-B 认证基座 → 9-C 教师端（最小风险先打通）→ 9-D 学生端+presentation → 9-E 家长端 → 9-F 契约测试双轨迁移 → 9-G 灰度收官；Phase 4 前端（echarts 证据链）不在本期范围但保留基座复用；
- **待拍板 4 项**：契约测试双轨过渡 vs 一次性替换、dist 产物是否入库（推荐不入库）、login 页是否 React 化（推荐保留）、SSE 是否本期接（推荐不接）。

纯文档变更，无代码改动。

### 2026-09-14 — 讲解生成非阻塞化 + 进度轮询 + 结果复用（§10 #10 ①② 落地）

Phase 3 验收暴露的"生成黑盒等待 10~25 分钟"改造（当日立项当日落地）：

- **逐场景落库**：`generate_for_outline` 新增 `on_scene` 回调，每个场景生成完（含降级）立即持久化——页面中断/进程重启不再浪费已生成部分；
- **POST /scenes 非阻塞化**：归属校验后起后台 daemon 线程生成，立即 `202 {"status": "generating"}`；进程内防重入注册表防重复触发；线程内失败记录留痕、状态回"未生成"可幂等重触发（传输层失败不再 502 给前端，也不伪装成内容）；
- **结果复用**：同大纲已有落库场景 → POST 直接 `200 {"status": "ready", "scene_count": n}`，幂等不重复生成计费；
- **进度端点**：`GET /scenes/{id}/status`（generated/total/status 三态）；scene.js 轮询并显示"正在生成讲解场景… n / m"；
- 灰度脚本（1/3 两代）同步接入 `_wait_scenes` 轮询助手（phase1 顺带补上 3-F-5 要求的 student_id 请求体——此前遗漏，现跑会 422）。

全量 **1949 用例通过**。剩余：重试/超时策略按耗时数据收紧；逐场景边生成边渲染的完整形态随 UI 现代化（§10 #9）实现。

### 2026-09-14 — Phase 3 全量发布（人工验收全部完成）

三项人工验收由维护者完成：① 真实 TTS 听音（合成/播放/读法通过，顺带抓出时长嗅探 bug）；② 页面观感 5 页逐页通过（白板渲染/播放暂停/重播/翻页/字幕/公式）；③ 灰度动作序列复核。整个验收期共发现并修复 **6 个测试环境无法触及的真缺陷**（时长嗅探采样率位 / sid 解析 / API base 写死 / api 助手无凭证 / 大纲 30s 超时 / KaTeX CDN + latex 定界符），全部有契约锁定 + 独立 CHANGELOG 条目。配套补齐讲解复看只读通道。**已知体验债务**立项待办：生成黑盒等待 10~25 分钟（方案文档 §10 #10，建议 UI 现代化动工前先做渐进落库/渲染）。全量 **1949 用例通过**。Phase 3 正式全量发布；下一步细化 Phase 4。

### 2026-09-14 — 维护者验收发现：白板公式源码直出（KaTeX 本地 vendor + latex 定界符治理）

页面观感验收发现白板上公式全部以 LaTeX 源码直出（`$$+5^{\circ}\text{C}$$` 等宽字体）。双根因：① 公式渲染依赖 jsdelivr CDN（1-E 起挂着的 vendor TODO），加载失败即全量降级；② LLM 把 `$` 定界符和中文标注混进 latex 字段（`'$+5^{\circ}\text{C}$（零上）'`）——few-shot 旧示例本身带 `$$`，LLM 有样学样。

修复三层：① **KaTeX 本地 vendor**（npmmirror 拉取 katex@0.16.11 dist 原样拷贝至 `web/vendor/katex/`，静态路由挂载含路径穿越防护，去掉 CDN/SRI 依赖，测试锁定文件存在 + 可服务 + 穿越拒绝）；② prompt few-shot 示例去掉定界符 + 明确"latex 只放公式本体，中文标注另用 wb_draw_text"；③ 定界符剥离双层——服务端 `_strip_latex_delimiters`（新数据，warning 留痕）+ whiteboard.js `stripLatexDelimiters`（渲染侧兜底，覆盖已落库旧数据）。**旧数据无需重新生成**，硬刷新即可正常渲染。全量 **1949 用例通过**（含 JS 26 例）。

### 2026-09-14 — 讲解复看只读端点 + scene 页 `?outline_id=` 复看模式

3-G 页面验收中一次成功生成（5 场景 87 动作零降级）因等待过久险些浪费——页面没有"复看已生成讲解"的入口，每次点讲解都重新生成（数分钟且计费）。补齐只读读路径：`GET /api/presentation/outline/{id}` 与 `GET /api/presentation/scenes/{id}`（不触发生成，按 outline 归属权威校验，与 POST 生成端点区分）；scene.js 支持 `?outline_id=` 参数走复看模式。测试 6 用例（200/404/空列表/越权 403）；全量 **1944 用例通过**。此读路径同时是第 11 章"错因→场景反查"（`idx_scenes_evidence`）的前置设施。

### 2026-09-14 — 维护者验收发现：大纲生成超时（30s 默认对 thinking 模型过紧）

页面验收时点「讲解」报 `大纲生成失败: LLM 调用失败（重试 3 次后仍失败）：Request timed out`——场景生成在 3-G 灰度实证后已有 120s 独立超时，但**大纲生成**仍挂共享客户端默认 30s。超时是概率性的（灰度两次全过说明偶尔够用），thinking 时长波动下会连续失败。修复：大纲生成对称补独立超时（`COGEDU_PRESENTATION_OUTLINE_TIMEOUT_SEC`，默认 120s，chat kwargs 透传 SDK，与 scene 同机制）；测试 4 用例（默认/env 覆盖/非法兜底/接线锁定）。全量 **1939 用例通过**。

### 2026-09-14 — 维护者验收发现：scene 页 api 助手不带登录凭证（修复，2-0-4 遗漏第三处）

sid 与 API base 修复后维护者继续验收，点「讲解」报 `HTTP 401`。根因：`scene.js` 的 `api()` 助手（outline/scenes/timing 三个主要请求的公共路径）是页面内唯一裸 fetch 不带 Authorization 的请求——2-0-4 只给行为回写和音频导出加了凭证。测试环境 auth_bypass 掩盖，真实鉴权下"点击讲解"必 401。修复：走 `CogEduAuth.authFetch` 统一带 Bearer + 401 自动跳登录；grep 契约锁定。全量 **1935 用例通过**。

### 2026-09-14 — 维护者验收发现：前端 API base 写死主机名（修复）

sid 解析修复后维护者继续验收，换报错 `state 加载失败: Failed to fetch`——网络层失败而非 HTTP 错误。地址栏显示页面从 `0.0.0.0:5173` 打开，而 `app.js:6` 写死 `http://localhost:5173/api`：主机名不同即跨源，浏览器直接拒绝请求（登录页正常是因为 auth.js 用相对路径）。全仓排查仅此一处写死。

修复：`const API = '/api'`（源相对路径——静态页由 FastAPI 自身托管，同源路径在任何主机名/局域网 IP 下都正确）；grep 契约测试全仓锁定前端 JS 不得写死主机名（`test_frontend_api_base_no_hardcoded_host`）。全量 **1934 用例通过**。

### 2026-09-14 — 维护者验收发现：学生端首页 sid 解析未接入登录身份（修复）

维护者做 Phase 3 页面观感验收（3-G ③）时，登录后首页报"数据加载失败"，页面头部显示 `python_student_001`——Phase 1 时代的硬编码兜底学生 ID。诊断链：后端接口全正常（库副本复现三接口 200/毫秒级），异常在浏览器 localStorage 残留的 `ecos_last_sid`（Phase 1 匿名时代的旧学生）被 auto-start 直接采用，而登录身份是新建的 stu01 → 请求他人数据 → 服务端 `require_student_access` 正确 403。

根因与 scene.js 同款：**2-0-4 只修了 scene.js 的 sid 解析（登录绑定优先），index 页 app.js 漏了**——硬编码 `python_student_001` 兜底在登录态下必然 403。修复：`start()` 与 DOMContentLoaded auto-start 的 sid 解析改为「登录账号绑定的 `learning_student_id` 优先于 localStorage 旧值」，删除硬编码兜底；无 sid 时留在登录入口提示输入（不发必 403 的请求）。grep 契约测试锁定（`test_app_js_sid_resolves_to_bound_identity`）。全量 **1933 用例通过**。

### 2026-09-14 — 维护者验收发现：音频时长嗅探采样率位读错（修复）

维护者按 3-G 验收手册做真实 TTS 小样本听音时发现时长系统性偏短 1.378 倍（10.684s 的文件实际播放 14.76s，两样本比例完全一致）。逐位诊断确认：MP3 帧头的采样率字段在 **byte2 的 bit 3-2**，嗅探器误读为 byte3 的 bits 3-2（那是 padding/私有位区域）——MiniMax T2A 返回的 32000 Hz MP3 被算成 44100 Hz。此前测试全绿的根因是"错对错"：测试夹具用同样错误的位布局构造 44100 样本，与旧嗅探器互相印证（vacuously passing）。

修复：`audio_duration.py` 采样率/padding 位提取改到正确位置；测试夹具帧头构造与解析同源对齐；新增 32000 Hz Xing 回归用例（409 帧 = 14724ms，与 macOS `afinfo` 实测一致）。对灰度库 8 段真实 MiniMax 音频重算全部命中 afinfo 值。教训进 CLAUDE.md 协作规范的姊妹条目：**测试夹具与被测代码不要共享同一处理解**——同源错误互相印证是全绿假象的典型来源。全量 **1932 用例通过**。

### 2026-09-13 — Phase 3 收官 / 3-G 端到端灰度（通过）

`scripts/canary_phase3_whiteboard.py`（真实进程 + 真实登录 + 真实 LLM）2 案例全链路通过：10 场景全部 schema v2 且含动作序列、零降级零 warning、timing 下发正常、`/scenes` 新鉴权契约生效、行为回写回归通过、theta K 上移（-0.331→-0.113）。动作质量抽查：177 动作（speech 62 / text 66 / latex 33 / line 9 / shape 7）结构零问题。

**灰度实证修正 2**（均落码 + 测试）：① scene `max_tokens` 默认上调 **16384**——thinking 模型推理 token 计入 max_tokens，动作序列 + 正文在 4096 下被推理耗尽产出空文本（解析必失败）；② scene 独立 **120s 超时**——长输出超共享客户端 30s 默认，经 `chat(**kwargs)` 透传 openai SDK per-request timeout，不动共享客户端。全量 **1931 用例通过**（含 node:test JS 24 例）。**待维护者**：过目灰度 stdout 动作序列质量 → 配 `COGEDU_TTS_API_KEY` 跑真实 TTS 小样本 → 页面观感验证后全量发布。

### 2026-09-13 — Phase 3 / 3-F 生成侧改造（3-F-5 已随 3-D 落地）

**prompt 扩展**（3-F-1）：scene system prompt 增加 `actions` 输出段——五动作字段口径（snake_case 对齐 3-A schema）、虚拟画布坐标系（1000×562.5 原点左上）、禁输出 action_id / estimated_duration_ms / audio_id（服务端统管）、求根公式 few-shot 完整示例。

**动作级容错管线**（3-F-2，`_parse_actions`）：白名单外丢弃 + warning（不整场失败）→ TypeAdapter 校验失败丢弃 → 坐标越界 clamp + warning（3-A-2）→ action_id 统一重分配 `f"{scene_id}_a{n}"` → 时长按 timing.py 权威源估算 → 超长 speech 三级拆分（子动作时长逐段重估）；warning 全部进 `scene.warnings` 留痕；整体 parse 失败仍走 retry → `_degraded_scene`（降级场景不带动作）。

**TTS 异步补齐**（3-F-3，`backfill_scene_audio` + 后台 daemon 线程）：幂等键已存在跳过合成 / 合成失败该动作保持 None 不中断 / 落库失败不回填 / `save_scene` 幂等覆盖回填。实现注记：计划为 asyncio task，但 `/scenes` 是同步端点（线程池无事件循环），daemon 线程语义等价。未配置 `COGEDU_TTS_API_KEY` 时 `get_tts()` 返回 None 静默跳过。**max_tokens 拆分**（3-F-4）：`COGEDU_PRESENTATION_SCENE_MAX_TOKENS` env 可配。

### 2026-09-13 — Phase 3 / 3-E 时间常数单一数据源

`cogedu/presentation/timing.py` 纯模块（不依赖 web/fastapi，对齐 OpenMAIC timing.ts 边界纪律）：7 常量（`WB_DRAW_MS=800` / 入场 450 / stagger 50 / 语音下限 2000 / CJK 150ms·字 / 英文 240ms·词 / CJK 占比阈值 0.3）+ `estimate_speech_duration_ms`（播放兜底与生成侧 `estimated_duration_ms` 同源）+ `estimate_action_duration_ms`。前端经 `GET /api/presentation/timing` 下发，scene.js 注入播放引擎与白板；**JS 兜底镜像被 pytest drift-lock 测试与 Python 权威值逐一锁定**（允许镜像，不允许漂移）。测试 17 用例，全量 1904 通过。

### 2026-09-13 — Phase 3 / 3-D 语音合成集成（含 /scenes 鉴权缺口修复）

**MiniMax TTS 单供应商**（3-D-1，`cogedu/presentation/tts.py`）：`SupportsTTS` Protocol（对齐 SupportsChat 注入模式）+ T2A v2 客户端（hex 音频解码，httpx transport 可注入测试）+ 长文本三级拆分（句级 → 子句级 → 硬切，子动作独立合成）；限长默认 2000 字符 env 可配（官方限长未在线核实，3-G 灰度核实——注记保留）。

**时长字节嗅探**（3-D-2，`audio_duration.py`）：WAV RIFF 走查 / MP3 Xing 帧数优先 + CBR 兜底 / ID3 跳过；截断与垃圾输入返回 None 不猜数；入库时测一次存库（播放调度不消费，3-C ended 事件驱动）。

**存储与端点**（3-D-4）：`presentation_audio` 表（BLOB 列按后端翻译 SQLite BLOB / PG BYTEA）+ 幂等键 `tts_{scene_id}_{action_id}`；`GET /api/presentation/audio/{audio_id}` 按 audio→scene.student_id 权威校验。前端 `createSpeechPlayer`（blob 会话缓存 + `<audio>` ended 驱动，失败回落估算计时器）；Web Speech API 按 v0.6 拍板不引入（3-D-5）。

**3-F-5 提前落地**：核实 `require_student_access` 发现 `/scenes` 缺口比 v0.6 记录的更严重——不止"只验已认证"，**真实学生 UI 会 403**（scene.js body 不带 student_id，灰度脚本恰好带了才没暴露）。修复：`ScenesRequest.student_id` 必填 + outline 归属校验（他人 outline → 403）+ scene.js 补带字段，real_auth 测试锁定越权矩阵。

### 2026-09-13 — Phase 3 / 3-C 播放引擎 + 3-B 白板渲染

**播放引擎**（3-C，`web/student/playback.js`，无 DOM 依赖）：三态 idle/playing/paused（live 排除）+ 顺序事件驱动调度 + **generation 代数令牌**（照抄 OpenMAIC playbackGeneration，stop/replay 后旧异步回调全部失效）+ pause 剩余时间语义；语音三级路径（音频 ended 优先 / 播放失败估算兜底 / 无 audio_id 估算，`estimateSpeechDurationMs` 对齐 OpenMAIC timing.ts）；重播本页；renderer/speechPlayer/scheduler 全部依赖注入。**测试基建新决策**：时序正确性用 node:test 零依赖真测试锁定（FakeClock 手动时钟，14 用例），pytest 包装进 pre-push 门禁（无 node skip）——仓库首个 JS 行为测试；写测试暴露并修复 3 个真实卡死/错序路径（ended 后忘推进 / 暂停中 promise 定局 / 音频暂停期 ended）。

**白板渲染**（3-B，`web/student/whiteboard.js`）：DOM + SVG path 路线（v0.6 拍板，OpenMAIC 实证），虚拟画布 1000×562.5 transform scale 等比缩放；实现 renderer 接口（clear/execute）；`elementSpec` 纯函数与 DOM 组装分离（node 可测）；渲染侧坐标 clamp 二道兜底。**formula.js 共享模块**（3-B-2）：`appendFormula` 从 scene.js 提取，scene 文字块与白板公式共用同一 KaTeX 封装（"同一能力只写一次"，grep 契约锁定 renderToString 全仓前端唯一）。**scene 页接线**：白板讲解区（仅 actions 非空显示，Phase 1 旧场景纯翻页不变）+ 播放/暂停/重播控件 + 语音字幕 + 翻页联动（`showScene` 开头 `stopPlayback()`，3-C-4 落地）；播放组件缺失守卫退回纯翻页。

### 2026-09-13 — Phase 3 / 3-A 动作模型与协议设计

`Scene.actions` 从预留裸 `list[dict]` 落成 Pydantic discriminator union：`WbDrawTextAction` / `WbDrawShapeAction`（仅矩形/圆/三角）/ `WbDrawLineAction`（v0.6 增补的两点式线段）/ `WbDrawLatexAction` / `SpeechAction`（含 audio_id 回填位），统一继承 `ActionBase`（action_id 生成侧重分配 + `estimated_duration_ms` 预留）。坐标系统：虚拟画布 1000×562.5（16:9，OpenMAIC 同款）+ `clamp_canvas_point` 纯函数。**schema 版本机制**：`SCHEMA_VERSION_V1/V2`，Scene after-validator 在 actions 非空时自动升 v2（版本号单点维护在模型内）；Phase 1 存量 payload（无版本字段）读回走 v1，兼容回归锁定。新增 `tests/test_presentation_actions.py` 21 用例。顺手修复 `llm_client.py` 两处存量 mypy 错误（失效 type: ignore + messages cast 收口）。

### 2026-09-12 — Phase 3 任务清单细化（方案文档 v0.6 第 15 章）

动笔前对 OpenMAIC 参考实现与 CogEdu 现状做双份代码勘察，**修正 v0.5 两处凭印象表述**：① 白板渲染并非"SVG vs Canvas"二选一（OpenMAIC 实际是 DOM 绝对定位 + shape 内嵌 SVG path）；② 播放调度不消费音频时长（ended 事件驱动，时长仅入库时字节嗅探供导出用）。四项决策落档（维护者拍板）：DOM+SVG 渲染路线；增补 `wb_draw_line`（第 3/8 章动作集结论同步修订）；砍撤销/重做换"重播本页"；TTS 异步补齐 + 播放端降级。15.1–15.8 展开为编号子任务。

### 2026-09-12 — Phase 2 / 2-D 前端页面 + 2-E 灰度（完成，Phase 2 收官）

**家长端**（`web/parent/index.html` 从占位页重写）：「我的孩子」roster 卡片 + 学习概览下钻（5D theta/Bloom 表，家长视角简化汇总——学生端可视化是内联 JS 非组件，未强行抽象共享）+ 报告下载（authFetch blob 下载带 Authorization）；「授权管理」发起申请（权限勾选）/状态列表/撤回撤销。

**学生端授权确认页**（`web/student/guardian-links.html`）：待确认申请确认/拒绝 + 全部授权记录撤销，入口挂学生端设置页。证据链展示页/预警通知位为 v1 可选项，按确认范围未启用。

**2-E 灰度**：`scripts/canary_phase2_parent.py` 14 步真实进程全链路通过——申请→学生确认→答题→数据可见→报告下载（内容完整打印人工复核）→家长 B 越权 403→学生撤销→家长 A 下一请求立即 403。**灰度发现并修复**：主导 Bloom 层级枚举名 "APPLY" 落空 L1-L6 映射表（报告出现 "APPLY（）"）→ 新增 `_DOMINANT_NAMES`。全量 **1804 用例通过**。

**Phase 2 收官**：2-0 账号体系 + 2-A 权限模型 + 2-B 范围确认 + 2-C 报告导出 + 2-D 前端 + 2-E 灰度（脚本级）全部完成。**待维护者执行**：小范围真实家长用户灰度验证后全量发布。

### 2026-09-12 — Phase 2 / 2-C 学习报告导出（Word，完成）

**公式渲染 spike**（2-C-1，`scripts/spike_mathtext_formula.py`）：33 样本 88% 通过——Phase 1 prompt 约束形态 5/5、K12 典型公式 21/21 全过；失败集中在 `\begin{}` 环境 / `\ce{}` / 未剥离 `$$`。主方案定 matplotlib mathtext。**spike 踩坑两枚（已固化进渲染器）**：`math_to_image` 必须保留 `$...$` 定界符（剥离后整串按普通文本渲染，不报错但内容错误——仅查 PNG 大小会出现全绿假象，需目检图像）；mathtext 对不支持命令有的抛异常有的静默按字面输出 → 生产渲染器预检优先于依赖解析异常。

**三层结构**（2-C-2/3）：`web/api/formula_render.py`（LaTeX→PNG，预检已知不支持构造，lru_cache 按公式串去重）→ `web/api/report.py`（`ReportDocument` paragraph/table/formula 三种 block；聚合同源 teacher/parent helpers，与 overview 接口数字一致；周期 week/month，薄弱点 = 周期内维度正确率 top-3 + 最近误概念；warnings 留痕不静默）→ `web/api/docx_renderer.py`（只做翻译不算数；公式 PNG 居中嵌入，**单条失败降级 LaTeX 原文 + 附注 warning，报告整体不失败**；报告头带生成时间 + 数据截止时间）。

**端点**（2-C-4）：`GET /api/parent/students/{sid}/report?period=week|month`，guardian 过 `download_report` 权限（2-A 单一入口现查）；guardian 对未知学生 403（权限在前不泄漏存在性），404 防幽灵学生语义由 staff 路径承载。新依赖 python-docx + matplotlib。

**验证**（2-C-5）：`tests/test_parent_report.py` 18 用例；真实进程冒烟：开户 → 答题 → 授权 → 下载 200（docx 重开正常）→ 学生撤销 → 再下载**立即 403**。全量 **1804 用例通过**。

### 2026-09-12 — Phase 2 / 2-A 家长-学生权限模型（完成）

**guardian_learner_link 显式授权**（2-A-1/2，`auth_store.py` 增表）：状态机 `pending → active / rejected / revoked`，partial unique index `WHERE status IN ('pending','active')` 保证同对唯一活跃关系（撤销/拒绝后可重申）；撤销留痕（revoked_by / revocation_reason，对齐 DeepTutor）。权限项五档：view_progress / view_evidence / download_report / receive_alerts（留位）/ assign_materials（留位）。

**服务层**（`web/api/guardian.py`）：`guardian_can_access` 单一校验入口，**每次现查双方当前角色**（角色变更/禁用后旧授权自动失效）+ 无缓存（撤销下一请求即失效）；家长按学生 username 发起申请（自绑禁止 / 非 student 角色拒绝 / 权限白名单）。

**授权流程端点**（`routers/guardian.py`，2-A-3）：家长申请/列表/撤回撤销；学生查看待确认/确认/拒绝/撤销；低龄场景 admin 可代确认。错误分级 400/404/409。

**家长端数据接口接入 per-student 校验**（2-A-4）：roster 只列 active 关联学生的学习记录（学习记录懒创建语义不变）；overview 过 `view_progress` 权限，未授权 403；staff 全量视图不变（存量契约测试零破坏）。

**验证**：`tests/test_guardian_links.py` 21 用例（全流程/申请规则/撤销立即生效/角色变更失效/权限粒度/多家长互不干扰/staff 视图）。全量 **1786 用例通过**。授权管理前端页归 2-D。

### 2026-09-12 — Phase 2 / 2-0 最小账号体系（完成）

**背景**：Phase 2 任务清单细化时发现仓库完全没有账号/身份体系（无 users 表、无鉴权，家长端接口无鉴权枚举全部学生），而 2-A 权限模型与灰度验收都以此为前提，故 2-0 作为地基先行。

**持久化**（2-0-1）：`cogedu/persistence/auth_store.py` — users 表（bcrypt 凭证哈希、guardian/student/teacher/admin 四角色、学生账号经 `learning_student_id` 关联 students 学习记录 1:1，无 FK——学习记录懒创建）+ sessions 表（**token 只存 SHA-256 哈希**；服务端会话刻意不用 JWT——"撤销立即生效"是 2-A 验收点）。双后端沿用 LCAStore/PresentationStore 模式，独立 DDL 不动 kernel 镜像的 SCHEMA_SQL。

**认证服务与端点**（2-0-2）：`web/api/auth.py`（bcrypt 校验、会话签发/现查/撤销、禁用账号即撤全部活跃会话；TTL 默认 7 天 `COGEDU_SESSION_TTL_HOURS` 可配；登录统一 401 防用户名枚举）+ `routers/auth.py`（login/logout/me，Bearer header 方案）。

**路由角色矩阵**（2-0-3）：teacher→staff、parent→guardian+staff、student 数据/事件回写/呈现引擎→学生本人（路径参数或 body 的 student_id 与 `learning_student_id` 一致性校验）或 staff、stream→已登录、`/api/students/recent` 收紧。存量 ~1700 契约测试零破坏：conftest autouse `auth_bypass` patch `_resolve_request_user`（测试层设施，非生产后门）；鉴权语义由 `real_auth` marker 下的测试覆盖。canary 脚本接真实开户+登录；`scripts/manage_users.py` 开户 CLI（v1 无自助注册）。**遗留（记录在案）**：parent per-student 的 `guardian_learner_link` 校验随 2-A 落地。

**前端登录态**（2-0-4）：`web/auth.js`（token 存取/authFetch/页面守卫/logout）+ `web/login.html`（按角色跳转，防 open redirect）+ 学生端 authFetch 统一带 Authorization、scene 回写带身份、teacher/parent 页接守卫。

**验证**：新增 `tests/test_auth_api.py` 37 用例；真实进程冒烟（CLI 开户 → 登录 → 带 token 200 → logout → 旧 token 立即 401）。全量 **1765 用例通过**。

### 2026-09-12 — Phase 1 / 呈现引擎最小可用版本（完成，1-A~1-G 收官）

**两阶段生成**（`cogedu/presentation/`，Phase 1 新写包）：Runtime `plan()` → `GenerationContext`（duck-typing 提取，不建立 LCAResult 类型引用）→ `OutlineGenerator`（大纲）→ `SceneGenerator`（场景，每步 text+image 两 block）。契约 schema（Outline/Scene/GenerationContext）用 Pydantic，同时服务 LLM 输出校验 / HTTP 响应模型 / 落库 payload；契约映射表见 `docs/presentation-runtime-map.md`。包边界：只读调用 `cogedu.runtime.api`，LLM client 注入不绑 web 层；纳入零 mutation 扫描 + mypy strict。

**生成健壮性**（1-D）：`json-repair`（PyPI，MIT）容错解析（think 块剥离 + 围栏清理 + 不合规 JSON 修复）；`RetryPolicy` 环境变量可配，生成层只重试解析失败（传输层由 client 内部重试）；重试耗尽 → 模板化 degraded scene（`degraded=true` + warnings 留痕，学生端不空白）。**灰度发现**：MiniMax-M3 thinking 块计入 max_tokens，默认 1024 会被推理耗尽 → 生成器显式 4096。

**回写事件闭环**（1-F，语义决策偏离 13.7 字面并已记录）：场景行为不伪造作答 Observation 进 `update_belief`（会污染 CTA 推断），走 v0.91.0-b 确立的 human feedback 通道——内核 additive 扩展 `scene_viewed`/`scene_completed` 事件类型（算法零改动，见 `kernel-baseline-notes.md` §8）→ `POST /api/presentation/event` → PluginRuntime → `append_human_feedback` → 影响后续 `plan()`。

**前端**：学生端新增"讲解"标签 + `scene.html|js|css` 独立场景页（翻页式，KaTeX 公式渲染——LLM 文本一律 textContent 进 DOM 不裸 innerHTML；图片懒加载 + 失败占位；degraded 提示条）。

**持久化**：`PresentationStore` 双后端（SQLite/PG 奇偶校验测试），`presentation_outlines`/`presentation_scenes` 两表，追溯列索引含 `idx_scenes_evidence` 错因反查（第 11 章可视化的物理前提）。

**端到端验证**（1-G）：真实进程灰度 3 案例（真实 MiniMax LLM）全部通过——5 场景零降级、行为回写 200、答对后 theta K 上移、内容质量人工复核（算术全对、Bloom 目标体现于讲解形态）；`tests/test_presentation_e2e.py` 全链路 HTTP 级回归。全量 **1728 用例通过**（Phase 0 收官时 1651）。

### 2026-09-12 — Phase 0 / 12.6 回归与灰度（完成，Phase 0 收官）

**全量回归**：1651 用例通过，pre-push hook 持续复验。

**真实进程灰度**（uvicorn + PG canary 库）：答题主链路（9 字段契约 / theta 演化 / M8 误概念 F-10 触发 / lca_decision passthrough）、真实 LLM judge、事件落库、教师端 7 视图、家长端（幽灵学生 404）、报告 interpretation、SSE 真实服务端推流、静态页 no-cache、重启持久化（theta_cov 真实 SE 恢复 / history / answered_ids 防重复出题）、dual_agent 开关两路径进程级验证——全部通过。

**灰度发现并修复**：`web/teacher/` 静态页为 12.2 内核复制遗漏（ECOS 有、CogEdu 无，`/teacher/` 自复制起恒 404），已按复制自包含原则补入。

### 2026-09-12 — Phase 0 / 12.5 SQLite → PostgreSQL（完成，双后端化）

**轻量适配层**（`cogedu/persistence/adapter.py`）：占位符翻译 / 行值归一化 / DSN scheme 识别 / executescript 分句 / 连接工厂。不上 ORM，"换数据库不触碰业务逻辑"落到全部 5 个持久化模块（db.py Database + DualAgentStore + LCAStore + EventLog.from_sqlite + evidence_engine，比原计划 db.py 单点多覆盖 4 个）。

**PostgreSQL schema**（`pg_schema.py`）：9 表 + 2 状态表 DDL。JSONB 评估结论：Phase 0 维持 TEXT（整存整取无 SQL 级查询需求 + 5 写入口统一 JSON 字符串契约优先，升级 ALTER 已备档）；布尔语义列 INTEGER 0/1、时间戳 TEXT ISO。

**双后端行为统一**：`RETURNING` 统一取代 `lastrowid`（SQLite ≥3.35）、`INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`、upsert 限定目标表列名（PG AmbiguousColumn 教训）、PG 事务 = autocommit 连接 + `transaction()` 块 + RLock 串行（对齐 SQLite 单写者语义）。

**数据迁移脚本**（`scripts/migrate_sqlite_to_pg.py`）：FK 依赖序写入、幂等重跑、IDENTITY 序列对齐；四重校验（行数逐表 / JSON 抽检 / FK 孤儿行 / BYTEA 字节）。端到端实测通过。

**PG 集成测试**（`tests/test_pg_backend.py`，11 用例，无 PG 服务器 skip）：双后端 CRUD 奇偶校验、事务回滚/提交（SQLite 原语义零回归）、20 线程并发写 + 读写混合、psycopg_pool 连接池并发验证、全部持久化模块 PG 走通。

**验证**：SQLite 路径全量 **1651 用例通过**（零回归）；开发机 PostgreSQL 17.11 实测 PG 用例全过。

### 2026-09-12 — Phase 0 / 12.4 Flask → FastAPI（完成，Flask 删除）

**迁移策略**：过渡期 FastAPI 与 Flask 并存（`web/api/fastapi_app.py` + `web/api/routers/`），按方案文档 12.4 建议顺序分 4 个 commit 递进（每步全量测试绿），最后一步翻转：`fastapi_app.py` 更名 `app.py` 替换 Flask 版，剥离 teacher/parent/event_stub 的 Blueprint 路由层（helpers 保留），pyproject 移除 flask 依赖。

**新布局**：`web/api/app.py`（装配 + lifespan 激活 PluginRuntime + `__main__` uvicorn 启动）+ `web/api/routers/`（student/teacher/parent/events/dual_agent/stream/static_pages 7 域）+ 框架无关业务模块（belief/lca/qmatrix/interpretation/dual_agent/plugin_runtime 未重写）+ 新抽出的 `web/api/llm.py`（get_llm 单例）与 `web/api/judge.py`（judge 三件套，解除业务层对装配模块的反向依赖）。

**关键决策**：
- `/api/answer` 9 字段契约用 `AnswerResponse`（response_model + exclude_none）框架层锁定
- `score`/`self_confidence`/`response_time` 保留"非数字诚实降级 + warning 留痕"语义（Any 字段 + 手工解析，Pydantic 422 会丢整份学生答案）
- SSE 能力打通：`GET /api/events/stream` 订阅事件总线实时推送（Phase 1 呈现引擎流式生成复用此模式）
- 响应 JSON 形状与 Flask 版逐字段一致，前端零改动

**顺带修复**：
- Flask 版 `/api/version` 与 `/api/report` 的 `import ecos` 重命名漏改（两端点此前恒 500）
- 硬边界违规 ×2：test_event_stub / test_judge_event 硬编码参考项目绝对路径 `/Users/loubicheng/project/ecos/...`，改为项目内相对路径
- conftest 隔离加固：PluginRuntime + 默认事件总线无条件重置、`DUAL_AGENT_ENABLED` 每测试归一化（修复 TestClient lifespan 引入的跨测试泄漏，曾导致 lca "重启后归零"假象）

**验证**：全量 **1640 用例通过**（1627 基线 + 13 新增）；uvicorn 真实启动冒烟通过；dual_agent 开关两条路径 HTTP 级测试锁定。

### 2026-09-11 — Phase 0 / 12.3 补齐状态入口的具体缺口（完成）

**三处直连调用评估（结论：均维持直接调用，不改代码）**
- `engine.l2.register_item`：改的是题目参数缓存（Q 矩阵内容装载，全学生共享），不触碰 `BeliefState`，属内容/配置装载。已在方案文档 12.3 留迁移纪律注记（0-C 迁 FastAPI 时两处调用不能漏，v0.47.4 事故依据）
- `_get_db().save_student_state`：纯持久化 I/O，已有 `persisted=false` + warning 防线和 HTTP 契约测试第 ④ 项锁定
- `reconcile_for_student`：写的 `misconception_evidence` 计数今天无任何认知内核消费者（仅教师展示视图，v0.97.2 拍板"不挂 BeliefState"）。已在方案文档 12.3 留 **A2 闭环 tripwire**：将来 evidence 计数参与信念更新时必须改走 Runtime
- 同时确认 `submit_answer` 核心路径事件总线路由（`_update_via_plugin_or_legacy` → bus → `PluginRuntime` → `Runtime.update_belief`）无需改动，作为 FastAPI 迁移的参考模式

**长期防线（12.3 第 4 项）**
- 新建 `githooks/pre-commit`（零 mutation AST 扫描，~1s）+ `githooks/pre-push`（同一扫描 + pytest 全量 ~25s），沿用 ECOS `core.hooksPath` 模式，hook 文件入仓 tracked
- `scripts/install-hooks.sh` 文案自 ECOS 版更新为 CogEdu 实况（原"5 项静态检查"描述与实际 hook 不符）
- 两 hook 已实测通过（扫描 54 文件 + 1627 用例全绿）；README 增加克隆后启用说明
- 注：ECOS 的 `check_defensive.sh` 暂不接入（内部硬编码扫描 `ecos/` 目录，需先适配 CogEdu 包名），留待后续按需处理

### 2026-09-11 — Phase 0 / 12.2 建立安全网（完成）

**内核复制（基线建立）**
- 从 ECOS v0.99.4（commit `9cdacab`）复制内核：`ecos/` → `cogedu/`（121 个 Python 文件），连同 `web/api/`（Flask，过渡期，0-C 迁 FastAPI 时重写）、`tests/`、`scripts/`、`examples/`、`data/`（Q 矩阵）、`web/student/` + `web/parent/`（静态页）一并迁入
- 包名 `ecos.*` → `cogedu.*`：仅重命名 import 语句与功能性字符串引用（logger 名、patch 目标、路径字面量），逻辑零改动
- 基线选择：方案原定 v0.98.0 快照，经确认改为最新 v0.99.4（含三处真实生产修复）；v0.98.0→v0.99.4 内核增量（7 文件/+159 行）已逐文件补审，v0.98.0 审查结论全部仍成立
- 复制保真验证：ECOS 侧基线 1623 用例全绿（18.92s）；CogEdu 侧复制后 1623 用例全部通过

**安全网补齐（12.2 第 2 项）**
- 新增 `tests/test_answer_endpoint_contract.py`（4 用例，HTTP 级）：
  - `/api/answer` 响应 9 字段契约（8 个函数级字段 + 路由层回显的 `reasoning`）
  - partial credit 派生口径（score ≥ 0.6 → correct=True）
  - `persisted=true` 正向锚点
  - save 失败可见性：`persisted=false` 必须返回前端 + warning 留痕（v0.47.5 "Bisen 反馈 4 道题没存" 真实事故的防线）
- 当前全量：**1627 用例通过**

**工程配置**
- `pyproject.toml` 建立：依赖随 ECOS 平移（flask 为过渡依赖），ruff（E/F/W/I/B/UP）+ mypy（lenient 起步）规则配置
- 零 mutation AST 扫描器（`scripts/check_no_direct_state_mutation.py`）扫描路径已指向 `cogedu/`，本仓库扫描通过（54 文件无违规）
- `docs/plugin_sdk.md`、`docs/plugin_library.md`、`docs/pomdp_diagnostic.md` 随内核迁入（docs-sync 测试的检查对象），内部代码路径引用同步更新为 `cogedu/`
