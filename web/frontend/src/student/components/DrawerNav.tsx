// UI-R-1（设计稿 §9 D3 拍板）：<768px 抽屉导航——侧栏隐藏后的降级形态。
//
// 关键约束：
//   - 与桌面侧栏共用 navTree（单一来源，避免两套维护）
//   - 关闭路径：①点遮罩 ②点导航链接（避免跳完路由抽屉还挡着） ③Esc 键
//   - 打开时焦点落到面板内第一个可聚焦元素（a11y 最低要求）
//   - 关闭时焦点归还触发按钮（useFocusTrap 此处不引入——按设计稿 §10 不增依赖）

import { useEffect, useRef } from "react";
import { NavLink } from "react-router-dom";
import Icon from "../../components/ui/Icon";
import { X } from "../../components/ui/icons";
import { NAV_GROUPS, type NavItem } from "./navTree";

interface DrawerNavProps {
  open: boolean;
  onClose: () => void;
}

export default function DrawerNav({ open, onClose }: DrawerNavProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Esc 关闭（a11y 标准）
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 打开时 body 锁滚动；关闭时恢复（避免抽屉打开时背景跟着滚）
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="drawer-overlay" onClick={onClose} role="presentation">
      {/* stopPropagation 阻止点面板内容时冒泡到 overlay 关闭 */}
      <div
        ref={panelRef}
        className="drawer-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="导航菜单"
      >
        <div className="drawer-header">
          <strong>CogEdu 学习</strong>
          <button
            type="button"
            className="drawer-close"
            onClick={onClose}
            aria-label="关闭导航菜单"
          >
            <Icon icon={X} size={18} />
          </button>
        </div>
        <nav className="drawer-nav" aria-label="主导航">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="drawer-group">
              <div className="drawer-group-title">{group.title}</div>
              {group.items.map((item) => (
                <DrawerItem
                  key={item.path}
                  item={item}
                  onNavigate={onClose}
                />
              ))}
            </div>
          ))}
        </nav>
      </div>
    </div>
  );
}

function DrawerItem({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  // 工具组 disabled 槽位不渲染为链接——纯 span，无导航语义
  if (item.enabled === false) {
    return (
      <span
        className="drawer-item disabled"
        aria-disabled="true"
        title={`${item.label}（${item.comingIn ?? "未上线"}）`}
      >
        <Icon icon={item.icon} size={18} />
        <span className="drawer-label">{item.label}</span>
        {item.comingIn ? <span className="drawer-soon">{item.comingIn}</span> : null}
      </span>
    );
  }
  return (
    <NavLink
      to={item.path}
      end={item.end}
      className={({ isActive }) => `drawer-item${isActive ? " active" : ""}`}
      onClick={onNavigate}
    >
      <Icon icon={item.icon} size={18} />
      <span className="drawer-label">{item.label}</span>
    </NavLink>
  );
}