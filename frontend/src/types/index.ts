// ==================== 通用 ====================

export type Role = 'super_admin' | 'dept_admin' | 'user';

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export interface PageData<T> {
  list: T[];
  total: number;
  page: number;
  page_size: number;
}

// ==================== 用户 ====================

export interface User {
  id: string;
  username: string;
  email: string;
  department_id: string | null;
  department_name?: string | null;
  role: Role;
  is_active?: boolean;
  report_count?: number;
  last_active?: string | null;
}

export interface LoginResult {
  token: string;
  user: User;
}

// ==================== 报告 ====================

export type ReportType = 'department' | 'personal';
export type ReportStatus =
  | 'draft'
  | 'generating'
  | 'completed'
  | 'failed'
  | 'timeout'
  | 'terminated';

export interface ReportListItem {
  id: string;
  title: string;
  description: string | null;
  type: ReportType;
  department_id: string | null;
  department_name: string | null;
  owner_id: string | null;
  owner_name: string | null;
  is_public: boolean;
  status: ReportStatus;
  current_version: number;
  generate_count: number;
  tags: string[] | null;
  style_id?: string | null;
  last_generated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReportDetail extends ReportListItem {
  config: ReportConfig;
}

// ==================== 报告配置 ====================

export type ModelProvider = 'ascend' | 'openai' | 'anthropic' | 'custom';

export interface ModelConfig {
  provider: ModelProvider;
  endpoint: string;
  api_key?: string;
  model_name: string;
  parameters?: {
    temperature?: number;
    max_tokens?: number;
  };
  unit_price_per_1k_tokens?: number;
  /** 引用「部门公共模型配置」作为默认值（生成时由后端解析，密钥不落报告配置） */
  use_department_default?: boolean;
}

export interface GrabConfig {
  proxy?: string;
  cookies?: string;
  custom_headers?: Record<string, string>;
  timeout?: number;
  retries?: number;
  max_length?: number;
  use_playwright?: boolean;
}

export interface DataSources {
  urls: string[];
  credential_id?: string;
  grab_config?: GrabConfig;
}

export interface ScheduleConfig {
  type: 'manual' | 'daily' | 'weekly' | 'monthly';
  cron?: string;
}

export interface ModuleConfig {
  module_title: string;
  model_config?: ModelConfig;
  keywords?: string[];
  prompt?: string;
  /** 分析框架模板 key（见 /api/frameworks），约束模型的分析视角与结构 */
  framework?: string;
  data_sources?: DataSources;
  schedule?: ScheduleConfig;
  /** text=Markdown；json=纯 JSON；structured=叙述+数据点+图表（前端可视化） */
  output_format?: 'text' | 'json' | 'structured';
}

/** 图表类型（与后端结构化输出 schema 对齐） */
export type ChartType = 'bar' | 'line' | 'pie';

/** 结构化输出：单个关键数据点（量化结论卡片） */
export interface ModuleDataPoint {
  label: string;
  value?: string;
  unit?: string;
  trend?: 'up' | 'down' | 'flat';
  note?: string;
}

/** 结构化输出：单个图表规格（前端据此渲染 SVG 图表） */
export interface ModuleChart {
  type: ChartType;
  title: string;
  caption?: string;
  x?: string[];
  series: { name: string; data: number[] }[];
}

export interface ReportConfig {
  modules: ModuleConfig[];
}

// ==================== 历史版本 ====================

export interface VersionItem {
  version_number: number;
  generated_at: string;
  model_used: string | null;
  status: string | null;
  style_id?: string | null;
  is_current: boolean;
}

export interface VersionDetail {
  version_number: number;
  content: VersionContent;
  config_snapshot: ReportConfig;
  model_used: string | null;
  status: string | null;
  style_id?: string | null;
  content_hash: string | null;
  generated_at: string;
}

// ==================== 生成任务 ====================

/** 分析框架模板（/api/frameworks 返回） */
export interface Framework {
  id: string;
  name: string;
  category: string;
  description: string;
}

export interface GenerationTaskResult {
  task_id: string;
  status: string;
}

export interface ProgressEvent {
  phase:
    | 'init'
    | 'fetching'
    | 'building'
    | 'generating'
    | 'storing'
    | 'module_done'
    | 'complete'
    | 'failed'
    | 'timeout'
    | 'terminated';
  progress: number;
  message: string;
  version?: number;
  task_id?: string;
  /** 当前第几个模块（从 1 开始） */
  current?: number;
  /** 模块总数 */
  total?: number;
  /** module_done 事件携带的模块内容（渐进渲染） */
  payload?: {
    index: number;
    module_title: string;
    content: string;
    /** 结构化输出（output_format=structured）提取的关键数据点 */
    data_points?: ModuleDataPoint[];
    /** 结构化输出提取的图表规格 */
    charts?: ModuleChart[];
  };
}

export interface VersionContent {
  summary?: string;
  modules?: {
    module_title?: string;
    content?: string;
    /** 结构化输出（output_format=structured）提取的关键数据点 */
    data_points?: ModuleDataPoint[];
    /** 结构化输出提取的图表规格 */
    charts?: ModuleChart[];
  }[];
  /** 生成时失败模块的明细（部分失败时存在） */
  errors?: { module_title?: string; error?: string }[];
}

// ==================== 数据源凭证 ====================

export interface Credential {
  id: string;
  name: string;
  proxy?: string | null;
  cookies?: string | null;
  custom_headers?: Record<string, string> | null;
  created_at: string;
}

// ==================== 邮件 ====================

export type EmailTaskStatus =
  | 'pending'
  | 'sending'
  | 'sent'
  | 'failed'
  | 'cancelled';

export interface EmailDelivery {
  recipient: string;
  status: 'pending' | 'sending' | 'sent' | 'failed' | 'cancelled';
  error_msg: string | null;
  sent_at: string | null;
}

export interface EmailTask {
  id: string;
  report_id: string | null;
  report_title: string | null;
  recipients: string[];
  formats: string[];
  version: number | null;
  status: EmailTaskStatus;
  attempts: number;
  deliveries: EmailDelivery[];
  trigger_type: string | null;
  cancel_requested_at: string | null;
  scheduled_at: string | null;
  sent_at: string | null;
  error_msg: string | null;
  created_at: string;
}

// ==================== 报告风格 ====================

export type StyleFontFamily = 'sans-serif' | 'serif' | 'monospace';

export interface StyleConfig {
  primary_color: string;
  background_color: string;
  font_family: StyleFontFamily;
  title_color: string;
  title_font_size: number;
  body_font_size: number;
  line_height: number;
  table_border_color: string;
  blockquote_bg: string;
  blockquote_border_color: string;
  code_bg: string;
  code_color: string;
}

export interface ReportStyle {
  id: string;
  name: string;
  type: 'builtin' | 'custom';
  config: StyleConfig;
  owner_id: string | null;
  owner_name: string | null;
  department_id: string | null;
  department_name: string | null;
  is_shared: boolean;
  can_edit: boolean;
  can_delete: boolean;
  created_at: string;
  updated_at: string;
}

// ==================== 统计看板 ====================

export interface DashboardStats {
  generate_trend: { daily: number[]; labels: string[] };
  hot_keywords: { keyword: string; count: number }[];
  active_users: { username: string; generate_count: number }[];
  model_usage: { provider: string; model: string; calls: number }[];
  module_success_rate: {
    total_attempts: number;
    success: number;
    failed: number;
    failure_reasons: Record<string, number>;
  };
}

// ==================== 系统管理 ====================

export interface WhitelistItem {
  id: string;
  domain: string;
  description: string | null;
  created_at: string;
}

export interface SmtpConfig {
  host: string;
  port: number;
  username: string;
  password?: string | null;
  tls: boolean;
  sender: string;
}

export interface SystemConfig {
  smtp: SmtpConfig;
  max_concurrent_tasks: number;
  task_timeout_seconds: number;
  email_simulate: boolean;
}
