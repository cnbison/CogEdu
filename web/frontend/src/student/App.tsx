import { NavLink, Route, Routes } from "react-router-dom";
import Icon from "../components/ui/Icon";
import { Home, MapPin, Pencil, Settings, TrendingUp, User } from "../components/ui/icons";
import { RequireSession } from "../shared/RequireSession";
import HomePage from "./pages/HomePage";
import AnswerPage from "./pages/AnswerPage";
import WherePage from "./pages/WherePage";
import GrowthPage from "./pages/GrowthPage";
import SettingsPage from "./pages/SettingsPage";
import ReportPage from "./pages/ReportPage";
import GuardianLinksPage from "./pages/GuardianLinksPage";
import ScenePage from "./presentation/ScenePage";
import { logout } from "../shared/auth";

// 学生端 App（9-D）：会话守卫 + 底部导航（信息架构三问）+ 讲解场景路由。
// sid 来源 = 登录身份 learning_student_id（禁手输——3-F-5 语义延续）。
// 登录走服务端 /login 页（拍板：login 页保留原样），未登录由 RequireSession 跳转。
export default function App() {
  return (
    <RequireSession allowedRoles={["student"]}>
      {({ username, learningStudentId }) =>
        learningStudentId ? (
          <div className="app">
            <header className="student-topbar">
              <strong>CogEdu 学习</strong>
              <span className="sid">
                <Icon icon={User} size={14} /> {username}
              </span>
            </header>
            <main className="content">
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
                    <SettingsPage studentId={learningStudentId} onLogout={() => void logout()} />
                  }
                />
              </Routes>
            </main>
            <nav className="bottom-nav">
              <NavLink to="/" end>
                <Icon icon={Home} size={18} /> 今天
              </NavLink>
              <NavLink to="/answer">
                <Icon icon={Pencil} size={18} /> 答题
              </NavLink>
              <NavLink to="/where">
                <Icon icon={MapPin} size={18} /> 我在哪
              </NavLink>
              <NavLink to="/growth">
                <Icon icon={TrendingUp} size={18} /> 成长
              </NavLink>
              <NavLink to="/settings">
                <Icon icon={Settings} size={18} /> 设置
              </NavLink>
            </nav>
          </div>
        ) : (
          <div style={{ padding: 24 }}>
            <p>当前学生账号未绑定学习记录（learning_student_id 缺失），请联系管理员。</p>
          </div>
        )
      }
    </RequireSession>
  );
}
