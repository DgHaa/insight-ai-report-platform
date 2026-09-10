import type { CSSProperties } from 'react';
import type { StyleConfig, StyleFontFamily } from '../types';

/** 默认风格：科技蓝（与后端内置风格保持一致） */
export const DEFAULT_STYLE_CONFIG: StyleConfig = {
  primary_color: '#1677ff',
  background_color: '#ffffff',
  font_family: 'sans-serif',
  title_color: '#0f1b33',
  title_font_size: 24,
  body_font_size: 15,
  line_height: 1.8,
  table_border_color: '#d6e4ff',
  blockquote_bg: '#f0f5ff',
  blockquote_border_color: '#1677ff',
  code_bg: '#f6f8fa',
  code_color: '#c41d7f',
};

const FONT_STACKS: Record<StyleFontFamily, string> = {
  'sans-serif': "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
  serif: "Georgia, 'Times New Roman', 'Songti SC', 'SimSun', serif",
  monospace: "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace",
};

export const FONT_FAMILY_OPTIONS: { label: string; value: StyleFontFamily }[] = [
  { label: '系统默认（无衬线）', value: 'sans-serif' },
  { label: '衬线（宋体 / Georgia）', value: 'serif' },
  { label: '等宽', value: 'monospace' },
];

/** 合并缺失字段，返回完整风格配置 */
export function normalizeStyleConfig(config: Partial<StyleConfig> | undefined | null): StyleConfig {
  return { ...DEFAULT_STYLE_CONFIG, ...(config || {}) };
}

/**
 * 将风格配置映射为 CSS 变量并返回，供报告容器 / 预览区通过 style 属性注入。
 * 例如：--report-primary、--report-bg、--report-body-size …
 */
export function styleConfigToCssVars(
  config: Partial<StyleConfig> | undefined | null,
): CSSProperties {
  const s = normalizeStyleConfig(config);
  const vars: Record<string, string> = {
    '--report-primary': s.primary_color,
    '--report-bg': s.background_color,
    '--report-font': FONT_STACKS[s.font_family] || FONT_STACKS['sans-serif'],
    '--report-title-color': s.title_color,
    '--report-title-size': `${s.title_font_size}px`,
    '--report-body-size': `${s.body_font_size}px`,
    '--report-line-height': String(s.line_height),
    '--report-table-border': s.table_border_color,
    '--report-quote-bg': s.blockquote_bg,
    '--report-quote-border': s.blockquote_border_color,
    '--report-code-bg': s.code_bg,
    '--report-code-color': s.code_color,
  };
  return vars as CSSProperties;
}
