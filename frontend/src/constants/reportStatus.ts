/**
 * 报告状态展示映射（单一数据源）
 *
 * 之前 ReportCard / ReportDetail / EmailTasks / DepartmentManage 各自维护一份，
 * 导致同一状态在列表显示中文、详情显示英文。统一收敛到此处，改一处全站生效。
 */
export const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  generating: 'processing',
  completed: 'success',
  failed: 'error',
  timeout: 'warning',
  terminated: 'default',
};

export const STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  generating: '生成中',
  completed: '已完成',
  failed: '失败',
  timeout: '超时',
  terminated: '已终止',
};
