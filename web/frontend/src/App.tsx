import { RequireSession } from "./shared/RequireSession";

// 9-B：教师端 shell + 会话守卫。7 个端点的页面在 9-C 移植（§10.1.6）。
export default function App() {
  return (
    <RequireSession allowedRoles={["teacher", "admin"]}>
      {() => (
        <main className="content">
          <h1>CogEdu 教师端</h1>
          <p className="muted">页面移植中（UI 现代化 9-C）。</p>
        </main>
      )}
    </RequireSession>
  );
}
