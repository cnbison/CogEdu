// 9-A 骨架占位：业务代码随 9-B..9-E 分任务移植（见方案文档 §10.1.6）。
import "./index.css";

export function AppShell({ title }: { title: string }) {
  return (
    <main className="content">
      <h1>{title}</h1>
      <p className="muted">React 移植施工中（UI 现代化 §10 #9）。此页为 9-A 工程骨架占位。</p>
    </main>
  );
}
