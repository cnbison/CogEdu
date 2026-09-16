// UI-R-1（设计稿 docs/ui-r-0-信息架构设计稿.md）：学生端导航树单一来源。
//
// 侧栏（SidebarShell ≥768px）与抽屉（DrawerNav <768px）共用此常量，
// 保证桌面与移动是同一棵导航树——不会出现"侧栏有但抽屉漏"。
//
// 三组（设计稿 §9 D1 拍板）：
//   - 学习：今天 / 答题 / 讲解 / 我在哪 / 成长
//   - 工具（Phase 4-6 逐项点亮）：诊断 / 资源 / 探索 / 练习
//   - 报告 + 授权 / 设置
//
// 工具组 4 个槽位当前 disabled（enabled = false）；上线时只改此常量，
// 侧栏与抽屉自动同步——避免"功能上线但忘了加导航项"的返工。

import type { LucideIcon } from "lucide-react";
import {
  BarChart,
  BookOpen,
  Brain,
  ClipboardList,
  Home,
  Lightbulb,
  MapPin,
  Pencil,
  Settings,
  Speech,
  TrendingUp,
  Users,
} from "../../components/ui/icons";

export interface NavItem {
  /** React Router 路径。NavLink 用 `to={path}`，`end` 仅 "/" 启用 */
  path: string;
  /** 中文导航 label（侧栏展开/抽屉/aria-label 共用） */
  label: string;
  /** Lucide 图标组件 */
  icon: LucideIcon;
  /** 仅 "/" 启用：精确匹配，避免 /scene 也激活"今天" */
  end?: boolean;
  /** Phase 4-6 槽位：上线前不可点 */
  enabled?: boolean;
  /** disabled 时 tooltip / aria-label 补充说明，方便后续替换为路由不存在的占位提示 */
  comingIn?: string;
}

export interface NavGroup {
  /** 分组标题（侧栏展开态显示；收窄态与抽屉隐藏） */
  title: string;
  items: NavItem[];
}

// 学习组（设计稿 §3）：现状 8 路由中 5 个一级导航项 + 讲解（一级化）。
export const LEARNING_GROUP: NavGroup = {
  title: "学习",
  items: [
    { path: "/", label: "今天", icon: Home, end: true },
    { path: "/answer", label: "答题", icon: Pencil },
    { path: "/scene", label: "讲解", icon: Speech },
    { path: "/where", label: "我在哪", icon: MapPin },
    { path: "/growth", label: "成长", icon: TrendingUp },
  ],
};

// 工具组：Phase 4-6 槽位。enabled = false → 渲染为 disabled 项；
// 上线时把对应项 enabled = true 即可点亮侧栏与抽屉，不需改组件代码。
export const TOOLS_GROUP: NavGroup = {
  title: "工具",
  items: [
    {
      path: "/diagnostic",
      label: "诊断",
      icon: Brain,
      enabled: false,
      comingIn: "Phase 4",
    },
    {
      path: "/resources",
      label: "资源",
      icon: BookOpen,
      enabled: false,
      comingIn: "Phase 5",
    },
    {
      path: "/explore",
      label: "探索",
      icon: Lightbulb,
      enabled: false,
      comingIn: "Phase 6",
    },
    {
      path: "/practice",
      label: "练习",
      icon: ClipboardList,
      enabled: false,
      comingIn: "Phase 6",
    },
  ],
};

// 报告 + 授权 / 设置（设计稿 §3 + §9 D1 三组外的同级项）。
export const REPORTS_GROUP: NavGroup = {
  title: "报告",
  items: [{ path: "/report", label: "学习报告", icon: BarChart }],
};

export const ACCOUNT_GROUP: NavGroup = {
  title: "账户",
  items: [
    { path: "/guardian-links", label: "家长授权", icon: Users },
    { path: "/settings", label: "设置", icon: Settings },
  ],
};

// 全量导航组（按设计稿 §9 D1 顺序：学习 / 工具 / 报告，账户与报告同级）
export const NAV_GROUPS: readonly NavGroup[] = [
  LEARNING_GROUP,
  TOOLS_GROUP,
  REPORTS_GROUP,
  ACCOUNT_GROUP,
];

/** 路由参数形态化为 `:outlineId`（用于断言 / 文档说明） */
export const REPLAY_PATH = "/scene/:outlineId";