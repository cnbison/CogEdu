# Changelog

本文件记录 **CogEdu 自身**的版本演进。内核代码复制自 ECOS（v0.99.4，commit `9cdacab`，2026-09-11），ECOS 的历史版本记录不在本文件范围内——如需追溯内核的历史设计决策，见 `discussions/` 收录的设计文档与 ECOS 仓库。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

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
