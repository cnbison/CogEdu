// 学生端家长授权确认页（9-E：对应 legacy web/student/guardian-links.html 的 React 化）。
// 授权语义：pending → 确认(生效)/拒绝；active → 撤销（立即生效，家长下一请求即 403）。
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  confirmLink,
  fetchLearnerLinks,
  rejectLink,
  revokeLearnerLink,
  type GuardianLink,
} from "../guardianLinks";

const STATUS_LABEL: Record<GuardianLink["status"], string> = {
  pending: "待你确认",
  active: "已授权",
  rejected: "已拒绝",
  revoked: "已撤销",
};

function statusBadgeClass(status: GuardianLink["status"]): string {
  if (status === "active") return "badge ok";
  if (status === "pending") return "badge cold";
  return "badge muted";
}

export default function GuardianLinksPage() {
  const links = useQuery({ queryKey: ["learnerLinks"], queryFn: fetchLearnerLinks });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>, okText: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await fn();
      setMessage(okText);
      await links.refetch();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (links.isLoading) return <p className="muted" style={{ padding: 16 }}>加载授权申请…</p>;
  if (links.isError) return <div className="error-box" style={{ padding: 16 }}>授权列表加载失败</div>;

  const rows = links.data?.links ?? [];

  return (
    <div style={{ maxWidth: 560, margin: "0 auto", padding: 16 }}>
      <div className="card">
        <h2>家长授权管理</h2>
        <p className="muted" style={{ fontSize: 13 }}>
          家长发起的绑定申请需要你本人确认后才会生效；已授权的可随时撤销，撤销立即生效。
        </p>
        {message && <p className="muted" style={{ fontSize: 13 }}>{message}</p>}
        {rows.length === 0 ? (
          <p className="muted">暂无授权申请。</p>
        ) : (
          <table style={{ marginTop: 10 }}>
            <thead>
              <tr>
                <th>家长</th>
                <th>状态</th>
                <th>权限</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((link) => (
                <tr key={link.link_id}>
                  <td>
                    <strong>{link.guardian_display_name || link.guardian_username || "—"}</strong>
                  </td>
                  <td>
                    <span className={statusBadgeClass(link.status)}>{STATUS_LABEL[link.status]}</span>
                  </td>
                  <td style={{ fontSize: 12 }}>{link.permissions.join("、") || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      {link.status === "pending" && (
                        <>
                          <button
                            className="green"
                            disabled={busy}
                            onClick={() => act(() => confirmLink(link.link_id), "已确认，家长现在可以查看你的学习了。")}
                          >
                            确认
                          </button>
                          <button
                            className="ghost"
                            disabled={busy}
                            onClick={() => act(() => rejectLink(link.link_id), "已拒绝该申请。")}
                          >
                            拒绝
                          </button>
                        </>
                      )}
                      {link.status === "active" && (
                        <button
                          className="ghost"
                          disabled={busy}
                          onClick={() => act(() => revokeLearnerLink(link.link_id), "已撤销授权（立即生效）。")}
                        >
                          撤销授权
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
