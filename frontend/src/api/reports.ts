import { request, downloadFile } from './http';
import type {
  Framework,
  GenerationTaskResult,
  PageData,
  ReportConfig,
  ReportDetail,
  ReportListItem,
  VersionContent,
  VersionDetail,
  VersionItem,
  EmailTask,
} from '../types';

export interface ReportQuery {
  view?: 'my' | 'department' | 'public' | 'all';
  department_id?: string;
  tag?: string;
  keyword?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export const reportApi = {
  // ---- 报告管理 ----
  list: (params: ReportQuery) => request.get<PageData<ReportListItem>>('/reports', params as Record<string, unknown>),
  create: (data: {
    title: string;
    description?: string;
    type: string;
    is_public?: boolean;
    tags?: string[];
    config: ReportConfig;
    style_id?: string | null;
  }) => request.post<{ id: string; created_at: string }>('/reports', data),
  detail: (id: string) => request.get<ReportDetail>(`/reports/${id}`),
  update: (
    id: string,
    data: Partial<{
      title: string;
      description: string;
      is_public: boolean;
      tags: string[];
      config: ReportConfig;
      style_id: string | null;
    }>,
  ) => request.put<{ id: string; updated_at: string }>(`/reports/${id}`, data),
  remove: (id: string) => request.del<void>(`/reports/${id}`),

  // ---- 报告生成 ----
  generate: (id: string, force = false) =>
    request.post<GenerationTaskResult>(`/reports/${id}/generate`, { force }),
  terminate: (id: string) =>
    request.post<void>(`/reports/${id}/generate/terminate`),

  // ---- 模块级重生成 ----
  regenerateModule: (id: string, moduleIndex: number) =>
    request.post<GenerationTaskResult>(
      `/reports/${id}/modules/${moduleIndex}/regenerate`,
    ),

  // ---- 分析框架模板 ----
  frameworks: () =>
    request.get<{ frameworks: Framework[] }>('/frameworks'),

  // ---- 历史版本 ----
  versions: (id: string) =>
    request.get<{ versions: VersionItem[] }>(`/reports/${id}/versions`),
  version: (id: string, version: number) =>
    request.get<VersionDetail>(`/reports/${id}/versions/${version}`),
  rollback: (id: string, version: number) =>
    request.post<{ current_version: number; message: string }>(
      `/reports/${id}/versions/${version}/rollback`,
    ),

  // ---- 导出 ----
  export: (id: string, format: 'pdf' | 'docx' | 'md', version?: number) =>
    downloadFile(`/reports/${id}/export`, { format, version }),

  // ---- 邮件 ----
  sendEmail: (
    id: string,
    data: {
      recipients: string[];
      formats: string[];
      version?: number;
      scheduled_at?: string;
    },
  ) => request.post<{ task_id: string; status: string }>(`/reports/${id}/email`, data),
  emailTasks: (params?: {
    page?: number;
    page_size?: number;
    status?: string;
    report_id?: string;
    keyword?: string;
  }) => request.get<PageData<EmailTask>>('/email/tasks', params as Record<string, unknown>),
  emailTask: (taskId: string) =>
    request.get<EmailTask>(`/email/tasks/${taskId}`),
  cancelEmailTask: (taskId: string) =>
    request.post<void>(`/email/tasks/${taskId}/cancel`),
  resendEmailTask: (taskId: string) =>
    request.post<{ task_id: string; status: string }>(`/email/tasks/${taskId}/resend`),
  emailContacts: () =>
    request.get<{ contacts: { id: string; username: string; email: string }[] }>(
      '/email/contacts',
    ),
};

export type { ReportConfig, VersionContent };
