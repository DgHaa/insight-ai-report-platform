import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import type { Role } from '../types';

interface Props {
  roles?: Role[];
  children: ReactNode;
}

/** 路由级权限守卫：未登录跳转登录页；角色不符跳转报告列表 */
export default function ProtectedRoute({ roles, children }: Props) {
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const location = useLocation();

  if (!token || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/reports" replace />;
  }
  return <>{children}</>;
}
