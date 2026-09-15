import { Link, Route, Routes } from "react-router-dom";
import { RequireSession } from "./shared/RequireSession";
import RosterPage from "./pages/RosterPage";
import StudentDetailPage from "./pages/StudentDetailPage";

// 9-C：教师端页面移植（RosterPage/StudentDetailPage 自 ECOS v0.99.5 前端，端点 1:1 对齐）。
// 适配：外层包 CogEdu 会话守卫（teacher/admin），API client 走共享 Bearer 基座。
export default function App() {
  return (
    <RequireSession allowedRoles={["teacher", "admin"]}>
      {() => (
        <div className="app">
          <header className="topbar">
            <Link to="/" className="brand">
              CogEdu 教师端
            </Link>
            <span className="topbar-sub">v{__APP_VERSION__} · 证据链视图 · POMDP 诊断</span>
          </header>
          <main className="content">
            <Routes>
              <Route path="/" element={<RosterPage />} />
              <Route path="/students/:id" element={<StudentDetailPage />} />
            </Routes>
          </main>
        </div>
      )}
    </RequireSession>
  );
}
