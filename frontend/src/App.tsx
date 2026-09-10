import { ConfigProvider, App as AntApp, theme as antdTheme } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Register from './pages/Register';
import ReportList from './pages/reports/ReportList';
import ReportCreate from './pages/reports/ReportCreate';
import ReportDetail from './pages/reports/ReportDetail';
import DepartmentManage from './pages/department/DepartmentManage';
import EmailTasks from './pages/email/EmailTasks';
import SystemAdmin from './pages/admin/SystemAdmin';
import Departments from './pages/admin/Departments';
import DepartmentDetail from './pages/admin/DepartmentDetail';
import Profile from './pages/profile/Profile';
import { useThemeStore } from './store/theme';

export default function App() {
  const mode = useThemeStore((s) => s.mode);
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
      }}
    >
      <AntApp>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              element={
                <ProtectedRoute>
                  <MainLayout />
                </ProtectedRoute>
              }
            >
              <Route path="/reports" element={<ReportList />} />
              <Route path="/reports/create" element={<ReportCreate />} />
              <Route path="/reports/:id/edit" element={<ReportCreate />} />
              <Route path="/reports/:id" element={<ReportDetail />} />
              <Route path="/email-tasks" element={<EmailTasks />} />
              <Route
                path="/department/manage"
                element={
                  <ProtectedRoute roles={['dept_admin']}>
                    <DepartmentManage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/departments"
                element={
                  <ProtectedRoute roles={['super_admin']}>
                    <Departments />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/departments/:departmentId"
                element={
                  <ProtectedRoute roles={['super_admin']}>
                    <DepartmentDetail />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute roles={['super_admin']}>
                    <SystemAdmin />
                  </ProtectedRoute>
                }
              />
              <Route path="/profile" element={<Profile />} />
            </Route>
            <Route path="*" element={<Navigate to="/reports" replace />} />
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}
