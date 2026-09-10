import type { ReactNode } from 'react';
import { useAuthStore } from '../store/auth';
import type { Role } from '../types';

interface Props {
  roles?: Role[];
  children: ReactNode;
}

/** 组件级权限显隐：角色不在允许列表时渲染 null */
export default function PermGuard({ roles, children }: Props) {
  const user = useAuthStore((s) => s.user);
  if (!user) return null;
  if (roles && !roles.includes(user.role)) return null;
  return <>{children}</>;
}
