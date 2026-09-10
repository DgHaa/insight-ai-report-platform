import { request } from './http';
import type { LoginResult, User } from '../types';

export const authApi = {
  login: (username: string, department_id: string | null) =>
    request.post<LoginResult>('/auth/login', { username, department_id }),
  logout: () => request.post<void>('/auth/logout'),
  updateMe: (data: { email: string }) => request.put<void>('/auth/me', data),
  register: (data: { username: string; department_id: string }) =>
    request.post<{ id: string }>('/auth/register', data),
};

export interface PublicDepartment {
  id: string;
  name: string;
  code: string;
}

/** 无需登录的公开接口 */
export const publicApi = {
  departments: () =>
    request.get<{ departments: PublicDepartment[] }>('/departments'),
};

export type { User };
