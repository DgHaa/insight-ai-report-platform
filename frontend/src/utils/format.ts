/** 通用格式化工具 */
import dayjs from 'dayjs';

export function formatTime(value?: string | null): string {
  if (!value) return '—';
  return dayjs(value).format('YYYY-MM-DD HH:mm');
}

export function formatDate(value?: string | null): string {
  if (!value) return '—';
  return dayjs(value).format('YYYY-MM-DD');
}

/** 生成 WebSocket 进度地址 */
export function buildProgressWsUrl(reportId: string, token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${proto}//${host}/api/v1/reports/${reportId}/generate/progress?token=${encodeURIComponent(token)}`;
}

/** 生成邮件发送进度 WebSocket 地址 */
export function buildEmailProgressWsUrl(taskId: string, token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  return `${proto}//${host}/api/v1/email/tasks/${taskId}/progress?token=${encodeURIComponent(token)}`;
}
