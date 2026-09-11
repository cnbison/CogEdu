# Changelog

本文件记录 **CogEdu 自身**的版本演进。内核代码复制自 ECOS（v0.99.4，commit `9cdacab`，2026-09-11），ECOS 的历史版本记录不在本文件范围内——如需追溯内核的历史设计决策，见 `discussions/` 收录的设计文档与 ECOS 仓库。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

## [Unreleased]

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
