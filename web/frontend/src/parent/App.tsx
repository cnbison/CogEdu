// 家长端 SPA（9-E，移植自 ECOS v0.98 单页形态 + CogEdu 扩展）。
// CogEdu 适配：RequireSession 会话守卫（guardian；staff 复用教师数据视图）；
// roster 选择 + 四卡 overview（ECOS 原样）+ 授权管理卡 + Word 报告下载（2-A/2-C）。
import { RequireSession } from "../shared/RequireSession";
import ParentHomePage from "./pages/ParentHomePage";
import { logout } from "../shared/auth";

export default function App() {
  return (
    <RequireSession allowedRoles={["guardian", "teacher", "admin"]}>
      {() => (
        <div className="app">
          <header className="topbar">
            <span className="brand">CogEdu 家长端</span>
            <span className="topbar-sub">v{__APP_VERSION__} · 学习状态 · 成长概览</span>
            <button className="ghost" style={{ marginLeft: "auto" }} onClick={() => void logout()}>
              退出登录
            </button>
          </header>
          <main className="content">
            <ParentHomePage />
          </main>
        </div>
      )}
    </RequireSession>
  );
}
