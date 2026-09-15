import { RequireSession } from "../shared/RequireSession";

// 9-B：家长端 shell + 会话守卫。roster/概览/授权管理/报告下载在 9-E 移植。
export default function App() {
  return (
    <RequireSession allowedRoles={["guardian", "teacher", "admin"]}>
      {({ username }) => (
        <main className="content">
          <h1>CogEdu 家长端</h1>
          <p className="muted">{username} —— 页面移植中（UI 现代化 9-E）。</p>
        </main>
      )}
    </RequireSession>
  );
}
