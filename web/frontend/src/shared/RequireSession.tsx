// 会话守卫：未登录 → 跳 /login?next=；已登录但角色不符 → 提示页。
// 登录态服务端权威校验（与 legacy requireLogin 语义一致），本地缓存仅作初始渲染。
import { useEffect } from "react";
import { getToken, homePathOf, currentReturnPath, type UserRole } from "./auth";
import { useSession } from "./session";

export function RequireSession({
  allowedRoles,
  children,
}: {
  allowedRoles: UserRole[];
  children: (user: { username: string; learningStudentId: string | null }) => React.ReactNode;
}) {
  const cached = getToken();
  const { data: user, isLoading, isError } = useSession();

  useEffect(() => {
    if (!cached) {
      window.location.href = `/login?next=${encodeURIComponent(currentReturnPath())}`;
    }
  }, [cached]);

  if (!cached) return null;
  if (isLoading) {
    return <div className="muted" style={{ padding: 24 }}>正在校验登录态…</div>;
  }
  if (isError || !user) {
    // authFetch 已在 401 时跳转登录页；此处是兜底提示
    return <div className="muted" style={{ padding: 24 }}>登录态校验失败，正在跳转登录页…</div>;
  }
  if (!allowedRoles.includes(user.role)) {
    return (
      <div style={{ padding: 24 }}>
        <p>当前账号（{user.username}）无权访问此端。</p>
        <p>
          <a href={homePathOf(user.role)}>前往对应端首页</a>
        </p>
      </div>
    );
  }
  return (
    <>
      {children({
        username: user.username,
        learningStudentId: user.learning_student_id,
      })}
    </>
  );
}
