// 9-E: 家长授权管理卡（2-A 授权流程：申请 → 学生确认 → active / 撤销立即失效）。
// 数据源 /api/guardian/links；错误语义 400 业务规则 / 404 不存在 / 409 重复申请。
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  GUARDIAN_PERMISSIONS,
  cancelGuardianLink,
  fetchGuardianLinks,
  linkErrorMessage,
  requestGuardianLink,
  type GuardianLink,
} from "../api";

const STATUS_LABEL: Record<GuardianLink["status"], string> = {
  pending: "待学生确认",
  active: "已生效",
  rejected: "已拒绝",
  revoked: "已撤销",
};

function statusBadgeClass(status: GuardianLink["status"]): string {
  if (status === "active") return "badge ok";
  if (status === "pending") return "badge cold";
  return "badge muted";
}

export default function GuardianLinksCard() {
  const links = useQuery({ queryKey: ["guardianLinks"], queryFn: fetchGuardianLinks });
  const [learnerUsername, setLearnerUsername] = useState("");
  const [perms, setPerms] = useState<string[]>(["view_progress"]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const togglePerm = (key: string) => {
    setPerms((prev) => (prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]));
  };

  const submit = async () => {
    if (!learnerUsername.trim() || perms.length === 0 || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      await requestGuardianLink(learnerUsername.trim(), perms);
      setMessage("申请已提交，等待学生确认。");
      setLearnerUsername("");
      await links.refetch();
    } catch (e) {
      setMessage(linkErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (linkId: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await cancelGuardianLink(linkId);
      await links.refetch();
    } catch (e) {
      setMessage(linkErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const rows = links.data?.links ?? [];

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <h2>家长授权管理</h2>
      <p className="muted" style={{ fontSize: 13 }}>
        绑定采用学生本人确认制：申请提交后由学生确认才生效；撤销立即失效。
      </p>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 10 }}>
        <input
          placeholder="学生账号用户名"
          value={learnerUsername}
          onChange={(e) => setLearnerUsername(e.target.value)}
          style={{ flex: "1 1 180px", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8 }}
        />
        <button onClick={submit} disabled={busy || !learnerUsername.trim() || perms.length === 0}>
          {busy ? "处理中…" : "发起绑定申请"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0" }}>
        {GUARDIAN_PERMISSIONS.map((p) => (
          <button
            key={p.key}
            className={`chip${perms.includes(p.key) ? " selected" : ""}`}
            onClick={() => togglePerm(p.key)}
            title={p.label}
          >
            {p.label}
          </button>
        ))}
      </div>

      {message && <p className="muted" style={{ fontSize: 13 }}>{message}</p>}

      {rows.length > 0 && (
        <table style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>学生</th>
              <th>状态</th>
              <th>权限</th>
              <th>申请时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((link) => (
              <tr key={link.link_id}>
                <td>
                  <strong>{link.learner_username ?? "—"}</strong>
                  {link.learner_student_id && (
                    <div className="muted" style={{ fontSize: 12 }}>{link.learner_student_id}</div>
                  )}
                </td>
                <td>
                  <span className={statusBadgeClass(link.status)}>{STATUS_LABEL[link.status]}</span>
                </td>
                <td style={{ fontSize: 12 }}>{link.permissions.join("、") || "—"}</td>
                <td className="muted" style={{ fontSize: 12 }}>
                  {link.requested_at?.slice(0, 10) ?? "—"}
                </td>
                <td>
                  {(link.status === "pending" || link.status === "active") && (
                    <button className="ghost" onClick={() => cancel(link.link_id)} disabled={busy}>
                      {link.status === "pending" ? "撤回" : "撤销"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
