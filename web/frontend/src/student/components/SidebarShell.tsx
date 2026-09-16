// UI-R-1（设计稿 docs/ui-r-0-信息架构设计稿.md）：学生端 SidebarShell 工作台。
//
// 三形态（设计稿 §2）：
//   - wide (≥1024px)：220px 展开侧栏，分组标题 + 文字 label
//   - narrow (768-1023px)：64px 图标栏，title/aria-label 替代文字 label
//   - drawer (<768px)：侧栏隐藏，顶条汉堡按钮唤出 DrawerNav
//
// 单一导航源：侧栏与 DrawerNav 都消费 navTree.ts 的 NAV_GROUPS。
// 顶条跨三种形态常驻：汉堡（仅 drawer）/ brand / username / 退出。
//
// 硬边界：
//   - 不动 Phase 3 vanilla 模块（whiteboard/playback/formula.js）
//   - 不动 scene.css 的 .wrap { max-width: 720px }（白板破版心留 UI-R-2）
//   - 不动路由表（侧栏激活态由 NavLink 自动匹配，不需额外手工同步）

import { useMemo, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import useMediaQuery from "../../components/ui/useMediaQuery";
import Icon from "../../components/ui/Icon";
import { LogOut, Menu, User } from "lucide-react";
import { logout } from "../../shared/auth";
import DrawerNav from "./DrawerNav";
import { NAV_GROUPS, type NavGroup, type NavItem } from "./navTree";

// lucide-react 的 LogOut 不在 icons.ts 公共导出里——为 UI-R-1 顶条退出按钮
// 单点引入，保持 components/ui/icons.ts 既有边界不动。

interface SidebarShellProps {
  username: string;
  children: React.ReactNode;
}

type ShellMode = "wide" | "narrow" | "drawer";

// 设计稿 §3：顶条"页面标题"取自最长匹配的导航项 label，避免侧栏已高亮还重复。
function useActiveLabel(pathname: string): string | null {
  return useMemo(() => {
    const items = NAV_GROUPS.flatMap((g) => g.items);
    const enabledItems = items.filter((i) => i.enabled !== false);
    // NavLink 默认前缀匹配：/scene 匹配 /scene 与 /scene/:outlineId；
    // 这里手动找最长前缀命中，与 NavLink 行为一致。
    let best: NavItem | null = null;
    for (const it of enabledItems) {
      const matches =
        it.end === true ? pathname === it.path : pathname === it.path || pathname.startsWith(it.path + "/");
      if (!matches) continue;
      if (!best || it.path.length > best.path.length) best = it;
    }
    return best?.label ?? null;
  }, [pathname]);
}

export default function SidebarShell({ username, children }: SidebarShellProps) {
  const isWide = useMediaQuery("(min-width: 1024px)");
  const isAtLeastTablet = useMediaQuery("(min-width: 768px)");
  const mode: ShellMode = isWide ? "wide" : isAtLeastTablet ? "narrow" : "drawer";

  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const activeLabel = useActiveLabel(location.pathname);

  return (
    <div className={`sidebar-shell ${mode}`}>
      {/* 顶条（跨三种形态常驻） */}
      <header className="shell-topbar">
        {mode === "drawer" ? (
          <button
            type="button"
            className="shell-menu-btn"
            onClick={() => setDrawerOpen(true)}
            aria-label="打开导航菜单"
            aria-expanded={drawerOpen}
          >
            <Icon icon={Menu} size={20} />
          </button>
        ) : null}
        <Link to="/" className="shell-brand">
          CogEdu 学习
        </Link>
        {mode !== "drawer" && activeLabel ? (
          <span className="shell-topbar-title">· {activeLabel}</span>
        ) : null}
        <span className="shell-topbar-spacer" />
        <span className="shell-username">
          <Icon icon={User} size={14} /> {username}
        </span>
        <button
          type="button"
          className="shell-logout"
          onClick={() => void logout()}
          aria-label="退出登录"
          title="退出登录"
        >
          <LogOut size={16} strokeWidth={1.5} aria-hidden="true" />
          {mode === "wide" ? <span style={{ marginLeft: 6 }}>退出</span> : null}
        </button>
      </header>

      {/* 侧栏（≥768 才渲染——drawer 模式避免占布局） */}
      {mode !== "drawer" ? (
        <aside className="shell-sidebar" aria-label="主导航">
          <nav>
            {NAV_GROUPS.map((group) => (
              <SidebarGroup key={group.title} group={group} mode={mode} />
            ))}
          </nav>
        </aside>
      ) : null}

      {/* 内容区 */}
      <main className="shell-content">{children}</main>

      {/* 抽屉（仅 <768px + 打开时） */}
      <DrawerNav open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </div>
  );
}

function SidebarGroup({ group, mode }: { group: NavGroup; mode: ShellMode }) {
  return (
    <div className="sidebar-group">
      {mode === "wide" ? <div className="sidebar-group-title">{group.title}</div> : null}
      {group.items.map((item) => (
        <SidebarItem key={item.path} item={item} mode={mode} />
      ))}
    </div>
  );
}

function SidebarItem({ item, mode }: { item: NavItem; mode: ShellMode }) {
  const isWide = mode === "wide";
  if (item.enabled === false) {
    return (
      <span
        className="sidebar-item disabled"
        aria-disabled="true"
        title={`${item.label}（${item.comingIn ?? "未上线"}）`}
      >
        <Icon icon={item.icon} size={20} />
        {isWide ? <span className="sidebar-label">{item.label}</span> : null}
      </span>
    );
  }
  return (
    <NavLink
      to={item.path}
      end={item.end}
      className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
      aria-label={item.label}
      title={item.label}
    >
      <Icon icon={item.icon} size={20} />
      {isWide ? <span className="sidebar-label">{item.label}</span> : null}
    </NavLink>
  );
}