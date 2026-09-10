import { request } from './http';
import type { ReportStyle, StyleConfig } from '../types';

export const styleApi = {
  /** 获取当前用户可用的全部风格（内置 + 个人自定义 + 部门共享） */
  list: () => request.get<ReportStyle[]>('/styles'),
  create: (data: { name: string; config: StyleConfig }) =>
    request.post<ReportStyle>('/styles', data),
  update: (id: string, data: { name?: string; config?: StyleConfig; is_shared?: boolean }) =>
    request.put<ReportStyle>(`/styles/${id}`, data),
  remove: (id: string) => request.del<void>(`/styles/${id}`),
  /** 部门管理员将个人风格设为部门共享 */
  share: (id: string) => request.post<ReportStyle>(`/styles/${id}/share`),
};
