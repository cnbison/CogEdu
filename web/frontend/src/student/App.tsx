import { RequireSession } from "../shared/RequireSession";

// 9-B：学生端 shell + 会话守卫。
// sid 来源 = 登录身份 learning_student_id（清单 b #2，禁手输 sid——3-F-5 语义延续）。
// 答题/我在哪/成长/报告等页面在 9-D 移植。
export default function App() {
  return (
    <RequireSession allowedRoles={["student"]}>
      {({ username, learningStudentId }) => (
        <main className="content">
          <h1>CogEdu 学生端</h1>
          <p className="muted">
            {username}（学习记录 {learningStudentId ?? "未绑定"}）——页面移植中（UI 现代化 9-D）。
          </p>
        </main>
      )}
    </RequireSession>
  );
}
