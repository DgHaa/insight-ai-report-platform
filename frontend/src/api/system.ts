import { request } from './http';
import type {
  DashboardStats,
  ModelProvider,
  SystemConfig,
  User,
  WhitelistItem,
} from '../types';

export const modelApi = {
  test: (data: {
    provider: ModelProvider;
    endpoint: string;
    api_key?: string;
    model_name: string;
    temperature?: number;
    max_tokens?: number;
  }) =>
    request.post<{ success: boolean; latency_ms: number; message: string }>(
      '/models/test',
      data,
    ),
  providers: () =>
    request.get<{ providers: ModelProvider[] }>('/models/providers'),
};

export const departmentApi = {
  /** 公开部门列表（公开报告按部门筛选等场景使用） */
  departments: () =>
    request.get<{ departments: { id: string; name: string; code: string }[] }>('/departments'),
  users: () =>
    request.get<{ users: User[] }>('/department/users'),
  createUser: (data: {
    username: string;
    email: string;
    role: 'user' | 'dept_admin';
    password?: string;
  }) => request.post<{ id: string }>('/department/users', data),
  updateUser: (id: string, data: { role: 'user' | 'dept_admin' }) =>
    request.put<void>(`/department/users/${id}`, data),
  removeUser: (id: string) => request.del<void>(`/department/users/${id}`),
  // 用已定义的 DashboardStats 收窄类型，避免 any 绕过类型检查
  statistics: (timeRange = 'month') =>
    request.get<DashboardStats>('/dashboard/statistics', { time_range: timeRange }),
  /** 本部门公共模型配置（api_key 为脱敏值，落库已加密） */
  modelConfig: () =>
    request.get<DepartmentModelConfigView | null>('/department/model-config'),
  saveModelConfig: (data: {
    name?: string;
    provider?: string;
    endpoint?: string;
    api_key?: string;
    model_name?: string;
  }) => request.put<void>('/department/model-config', data),
};

export interface DepartmentModelConfigView {
  id: string;
  name: string;
  provider: string;
  endpoint: string | null;
  model_name: string | null;
  /** 脱敏后的密钥，仅用于回显 */
  api_key: string | null;
  has_api_key: boolean;
}

export const adminApi = {
  whitelist: () =>
    request.get<{ domains: WhitelistItem[] }>('/admin/email-whitelist'),
  addWhitelist: (data: { domain: string; description?: string }) =>
    request.post<{ id: string }>('/admin/email-whitelist', data),
  removeWhitelist: (id: string) =>
    request.del<void>(`/admin/email-whitelist/${id}`),
  systemConfig: () =>
    request.get<SystemConfig>('/admin/system/config'),
  updateSystemConfig: (data: Partial<SystemConfig>) =>
    request.put<void>('/admin/system/config', data),
  testSmtp: (data: {
    host: string;
    port: number;
    username?: string;
    password?: string;
    tls?: boolean;
  }) =>
    request.post<{ success: boolean; latency_ms: number; message: string }>(
      '/admin/system/config/test-smtp',
      data,
    ),
  allReports: (params?: {
    department_id?: string;
    keyword?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }) =>
    request.get<{
      list: import('../types').ReportListItem[];
      total: number;
      page: number;
      page_size: number;
    }>('/admin/all-reports', params as Record<string, unknown>),

  // ==================== 全部门管理（超级管理员） ====================
  departments: () =>
    request.get<{ departments: DepartmentSummary[] }>('/admin/departments'),
  departmentStatistics: (departmentId: string, timeRange = 'month') =>
    request.get<DashboardStats>(`/admin/departments/${departmentId}/statistics`, {
      time_range: timeRange,
    }),
  departmentUsers: (departmentId: string) =>
    request.get<{ users: User[] }>(`/admin/departments/${departmentId}/users`),
  createDepartmentUser: (
    departmentId: string,
    data: {
      username: string;
      email: string;
      role: 'user' | 'dept_admin';
      password?: string;
    },
  ) => request.post<{ id: string }>(`/admin/departments/${departmentId}/users`, data),
  updateDepartmentUser: (
    departmentId: string,
    userId: string,
    data: { role: 'user' | 'dept_admin' },
  ) => request.put<void>(`/admin/departments/${departmentId}/users/${userId}`, data),
  removeDepartmentUser: (departmentId: string, userId: string) =>
    request.del<void>(`/admin/departments/${departmentId}/users/${userId}`),
  departmentModelConfigs: (departmentId: string) =>
    request.get<{ items: DepartmentModelConfigItem[] }>(
      `/admin/departments/${departmentId}/model-configs`,
    ),
  createDepartmentModelConfig: (
    departmentId: string,
    data: DepartmentModelConfigPayload,
  ) =>
    request.post<{ id: string }>(
      `/admin/departments/${departmentId}/model-configs`,
      data,
    ),
  updateDepartmentModelConfig: (
    departmentId: string,
    configId: string,
    data: Partial<DepartmentModelConfigPayload>,
  ) =>
    request.put<void>(
      `/admin/departments/${departmentId}/model-configs/${configId}`,
      data,
    ),
  removeDepartmentModelConfig: (departmentId: string, configId: string) =>
    request.del<void>(
      `/admin/departments/${departmentId}/model-configs/${configId}`,
    ),
};

// ==================== 部门管理类型 ====================

export interface DepartmentSummary {
  id: string;
  name: string;
  code: string;
  description: string | null;
  admin_id: string | null;
  admin_name: string | null;
  member_count: number;
  report_count: number;
}

export interface DepartmentModelConfigItem {
  id: string;
  name: string;
  provider: string | null;
  endpoint: string | null;
  /** 已由后端脱敏（如 sk-****abcd），任何情况下不含明文 */
  api_key: string | null;
  model_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface DepartmentModelConfigPayload {
  name: string;
  provider?: string;
  endpoint?: string;
  /** 编辑时留空表示不修改已保存的密钥 */
  api_key?: string;
  model_name?: string;
}
