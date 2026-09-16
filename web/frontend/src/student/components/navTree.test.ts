// UI-R-1：navTree 单一来源单测——侧栏/抽屉共用的"事实基线"。
//
// 锁语义（test_frontend_react_wiring.py 同步锁关键项）：
//   - 8 个学生路由全部在导航树可达（不留死链）
//   - 工具组 4 个 Phase 4-6 槽位 disabled（不提前渲染可点链接）
//   - 分组标题与设计稿 §9 D1 一致：学习 / 工具 / 报告 + 账户

import { describe, expect, it } from "vitest";
import {
  ACCOUNT_GROUP,
  LEARNING_GROUP,
  NAV_GROUPS,
  REPORTS_GROUP,
  TOOLS_GROUP,
} from "./navTree";

const EXPECTED_STUDENT_ROUTES = [
  "/", // 今天
  "/answer", // 答题
  "/scene", // 讲解
  "/where", // 我在哪
  "/growth", // 成长
  "/report", // 学习报告
  "/guardian-links", // 家长授权
  "/settings", // 设置
];

describe("navTree — 学生端单一导航源", () => {
  it("三组标题与设计稿 §9 D1 一致（学习 / 工具 / 报告 + 账户）", () => {
    expect(LEARNING_GROUP.title).toBe("学习");
    expect(TOOLS_GROUP.title).toBe("工具");
    expect(REPORTS_GROUP.title).toBe("报告");
    expect(ACCOUNT_GROUP.title).toBe("账户");
    expect(NAV_GROUPS.map((g) => g.title)).toEqual([
      "学习",
      "工具",
      "报告",
      "账户",
    ]);
  });

  it("学习组 5 项 + 报告/账户 3 项 = 现状 8 路由全部可达", () => {
    const reachable = NAV_GROUPS.flatMap((g) => g.items).map((i) => i.path);
    for (const route of EXPECTED_STUDENT_ROUTES) {
      expect(reachable).toContain(route);
    }
  });

  it("/ 是唯一 end=true 的项（精确匹配，避免 /scene 激活今天）", () => {
    const items = NAV_GROUPS.flatMap((g) => g.items);
    const ends = items.filter((i) => i.end);
    expect(ends.map((i) => i.path)).toEqual(["/"]);
  });

  it("工具组 4 个 Phase 4-6 槽位全部 disabled（占位不渲染可点链接）", () => {
    expect(TOOLS_GROUP.items).toHaveLength(4);
    for (const item of TOOLS_GROUP.items) {
      expect(item.enabled ?? false).toBe(false);
      expect(item.comingIn).toMatch(/^Phase/);
    }
  });

  it("复看路由 /scene/:outlineId 在导航树语义化表达为 REPLAY_PATH", () => {
    // 复看路由由 /scene 触发（点记录行 → navigate(/scene/:id)），主导航项保持 /scene。
    // 这里锁"未来加复看入口时不要新加 /scene/:id 一级导航"的契约。
    const paths = NAV_GROUPS.flatMap((g) => g.items).map((i) => i.path);
    expect(paths).not.toContain("/scene/:outlineId");
  });
});