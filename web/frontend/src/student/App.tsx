import { Route, Routes } from "react-router-dom";
import { RequireSession } from "../shared/RequireSession";
import HomePage from "./pages/HomePage";
import AnswerPage from "./pages/AnswerPage";
import WherePage from "./pages/WherePage";
import GrowthPage from "./pages/GrowthPage";
import SettingsPage from "./pages/SettingsPage";
import ReportPage from "./pages/ReportPage";
import GuardianLinksPage from "./pages/GuardianLinksPage";
import ScenePage from "./presentation/ScenePage";
import SidebarShell from "./components/SidebarShell";
import { logout } from "../shared/auth";

// 学生端 App（UI-R-1）：会话守卫 + SidebarShell 工作台。
// 8 个路由表不变（HashRouter + NavLink 自动激活态，不需手工同步）；
// 顶条 + 底部导航由 SidebarShell 内部三形态切换接管（≥1024 wide / 768-1023 narrow / <768 drawer）。
// sid 来源 = 登录身份 learning_student_id（禁手输——3-F-5 语义延续）。
// 登录走服务端 /login 页，未登录由 RequireSession 跳转。
export default function App() {
  return (
    <RequireSession allowedRoles={["student"]}>
      {({ username, learningStudentId }) =>
        learningStudentId ? (
          <SidebarShell username={username}>
            <Routes>
              <Route path="/" element={<HomePage studentId={learningStudentId} />} />
              <Route path="/answer" element={<AnswerPage studentId={learningStudentId} />} />
              <Route path="/where" element={<WherePage studentId={learningStudentId} />} />
              <Route path="/growth" element={<GrowthPage studentId={learningStudentId} />} />
              <Route path="/report" element={<ReportPage studentId={learningStudentId} />} />
              <Route path="/scene" element={<ScenePage sid={learningStudentId} />} />
              <Route path="/scene/:outlineId" element={<ScenePage sid={learningStudentId} />} />
              {/* 2-A: 家长授权确认页（学生本人确认制） */}
              <Route path="/guardian-links" element={<GuardianLinksPage />} />
              <Route
                path="/settings"
                element={
                  <SettingsPage
                    studentId={learningStudentId}
                    onLogout={() => void logout()}
                  />
                }
              />
            </Routes>
          </SidebarShell>
        ) : (
          <div style={{ padding: 24 }}>
            <p>当前学生账号未绑定学习记录（learning_student_id 缺失），请联系管理员。</p>
          </div>
        )
      }
    </RequireSession>
  );
}