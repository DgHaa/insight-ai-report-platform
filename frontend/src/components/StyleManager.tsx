import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  ColorPicker,
  Divider,
  Empty,
  Input,
  List,
  Modal,
  Select,
  Slider,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ShareAltOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { styleApi } from '../api/styles';
import type { ReportStyle, StyleConfig, StyleFontFamily } from '../types';
import {
  DEFAULT_STYLE_CONFIG,
  FONT_FAMILY_OPTIONS,
  styleConfigToCssVars,
} from '../utils/reportStyle';
import MarkdownView from './MarkdownView';
import { confirmAction } from './ConfirmDialog';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 风格列表变化后的回调（用于刷新使用方） */
  onChanged?: () => void;
}

const PREVIEW_MD = `## 一、核心摘要
本报告对**服务质量**相关指标进行持续监测与分析，用于支持管理决策。

> 关键结论：整体满意度 92.3%，较上期提升 2.1 个百分点。

## 二、关键指标

| 指标 | 数值 | 环比 |
| ---- | ---- | ---- |
| 满意度 | 92.3% | ↑ 2.1% |
| 投诉量 | 128 | ↓ 8.4% |

## 三、代码示例

\`\`\`python
def analyze(report):
    return report.summarize()
\`\`\``;

type ConfigKey = keyof StyleConfig;

const COLOR_FIELDS: { key: ConfigKey; label: string }[] = [
  { key: 'primary_color', label: '主色' },
  { key: 'background_color', label: '背景色' },
  { key: 'title_color', label: '标题颜色' },
  { key: 'table_border_color', label: '表格边框' },
  { key: 'blockquote_bg', label: '引用块背景' },
  { key: 'blockquote_border_color', label: '引用块边框' },
  { key: 'code_bg', label: '代码块背景' },
  { key: 'code_color', label: '代码文字' },
];

/** 风格管理：列表 + 创建/编辑 + 实时预览 */
export default function StyleManager({ open, onClose, onChanged }: Props) {
  const [styles, setStyles] = useState<ReportStyle[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id?: string; name: string; config: StyleConfig } | null>(
    null,
  );

  // 用 ref 持有 onChanged：父组件若传内联函数，其引用每次渲染都变化，
  // 直接放进 useCallback 依赖会导致 load 反复重建 → 打开弹窗时无限重新加载（左侧列表闪动）。
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await styleApi.list();
      setStyles(data);
      onChangedRef.current?.();
    } catch {
      /* 已统一提示 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      load();
      setSelectedId(null);
      setEditing(null);
    }
  }, [open, load]);

  const selected = useMemo(() => {
    if (editing) return editing.config;
    const s = styles.find((x) => x.id === selectedId);
    return s ? s.config : null;
  }, [editing, styles, selectedId]);

  const previewConfig = selected || DEFAULT_STYLE_CONFIG;

  const updateConfig = (key: ConfigKey, value: unknown) => {
    setEditing((e) => (e ? { ...e, config: { ...e.config, [key]: value } } : e));
  };

  const save = async () => {
    if (!editing) return;
    if (!editing.name.trim()) {
      message.warning('请输入风格名称');
      return;
    }
    setSaving(true);
    try {
      const payload = { name: editing.name.trim(), config: editing.config };
      if (editing.id) {
        await styleApi.update(editing.id, payload);
        message.success('风格已更新');
      } else {
        await styleApi.create(payload);
        message.success('风格已创建');
      }
      setEditing(null);
      await load();
    } catch {
      /* 已统一提示 */
    } finally {
      setSaving(false);
    }
  };

  const remove = (style: ReportStyle) => {
    confirmAction(
      '删除风格',
      `确定删除风格「${style.name}」吗？删除后引用该风格的报告将回退到默认风格。`,
      async () => {
        await styleApi.remove(style.id);
        message.success('已删除');
        if (selectedId === style.id) setSelectedId(null);
        await load();
      },
    );
  };

  const share = async (style: ReportStyle) => {
    try {
      await styleApi.share(style.id);
      message.success('已共享到本部门');
      await load();
    } catch {
      /* 已统一提示 */
    }
  };

  const unshare = async (style: ReportStyle) => {
    try {
      await styleApi.update(style.id, { is_shared: false });
      message.success('已取消共享');
      await load();
    } catch {
      /* 已统一提示 */
    }
  };

  const groups = useMemo(() => {
    const builtin = styles.filter((s) => s.type === 'builtin');
    const mine = styles.filter((s) => s.type === 'custom' && !s.is_shared);
    const shared = styles.filter((s) => s.type === 'custom' && s.is_shared);
    return [
      { title: '内置风格', items: builtin },
      { title: '我的风格', items: mine },
      { title: '部门共享', items: shared },
    ];
  }, [styles]);

  return (
    <Modal
      open={open}
      title="报告风格管理"
      width={1080}
      footer={null}
      onCancel={onClose}
      destroyOnClose
    >
      <div style={{ display: 'flex', gap: 16, minHeight: 520 }}>
        {/* 左侧列表 */}
        <div style={{ width: 280, flexShrink: 0, borderRight: '1px solid #f0f0f0', paddingRight: 12, overflow: 'auto' }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            style={{ marginBottom: 12 }}
            onClick={() => setEditing({ name: '', config: { ...DEFAULT_STYLE_CONFIG } })}
          >
            新建自定义风格
          </Button>
          {loading ? (
            <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
          ) : groups.every((g) => g.items.length === 0) ? (
            <Empty description="暂无风格" />
          ) : (
            groups.map((g) =>
              g.items.length === 0 ? null : (
                <div key={g.title} style={{ marginBottom: 12 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {g.title}（{g.items.length}）
                  </Typography.Text>
                  <List
                    size="small"
                    dataSource={g.items}
                    renderItem={(s) => (
                      <List.Item
                        style={{
                          cursor: 'pointer',
                          borderRadius: 6,
                          background:
                            selectedId === s.id || editing?.id === s.id ? '#e6f4ff' : undefined,
                          paddingLeft: 8,
                        }}
                        onClick={() => {
                          setEditing(null);
                          setSelectedId(s.id);
                        }}
                        actions={[
                          s.can_edit ? (
                            <Button
                              key="edit"
                              size="small"
                              type="text"
                              icon={<EditOutlined />}
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditing({ id: s.id, name: s.name, config: { ...s.config } });
                                setSelectedId(s.id);
                              }}
                            />
                          ) : null,
                          s.can_delete ? (
                            <Button
                              key="del"
                              size="small"
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={(e) => {
                                e.stopPropagation();
                                remove(s);
                              }}
                            />
                          ) : null,
                          s.type === 'custom' && !s.is_shared && s.can_edit ? (
                            <Button
                              key="share"
                              size="small"
                              type="text"
                              icon={<ShareAltOutlined />}
                              title="共享到本部门"
                              onClick={(e) => {
                                e.stopPropagation();
                                share(s);
                              }}
                            />
                          ) : null,
                          s.type === 'custom' && s.is_shared && s.can_edit ? (
                            <Button
                              key="unshare"
                              size="small"
                              type="text"
                              icon={<StopOutlined />}
                              title="取消共享"
                              onClick={(e) => {
                                e.stopPropagation();
                                unshare(s);
                              }}
                            />
                          ) : null,
                        ]}
                      >
                        <Space size={4}>
                          <span
                            style={{
                              display: 'inline-block',
                              width: 12,
                              height: 12,
                              borderRadius: 3,
                              background: s.config.primary_color,
                              flexShrink: 0,
                            }}
                          />
                          <Typography.Text>{s.name}</Typography.Text>
                          {s.type === 'builtin' ? (
                            <Tag color="blue">内置</Tag>
                          ) : s.is_shared ? (
                            <Tag color="green">共享</Tag>
                          ) : (
                            <Tag>自定义</Tag>
                          )}
                        </Space>
                      </List.Item>
                    )}
                  />
                </div>
              ),
            )
          )}
        </div>

        {/* 右侧编辑 + 预览 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {editing ? (
            <div>
              <Typography.Title level={5}>{editing.id ? '编辑风格' : '新建风格'}</Typography.Title>
              <Input
                placeholder="风格名称"
                value={editing.name}
                maxLength={100}
                onChange={(e) => setEditing((p) => (p ? { ...p, name: e.target.value } : p))}
                style={{ marginBottom: 12 }}
              />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 20px' }}>
                <div>
                  <Typography.Text type="secondary">字体</Typography.Text>
                  <Select<StyleFontFamily>
                    style={{ width: '100%' }}
                    value={editing.config.font_family}
                    options={FONT_FAMILY_OPTIONS}
                    onChange={(v) => updateConfig('font_family', v)}
                  />
                </div>
                {COLOR_FIELDS.map((f) => (
                  <div key={f.key}>
                    <Typography.Text type="secondary">{f.label}</Typography.Text>
                    <div style={{ marginTop: 2 }}>
                      <ColorPicker
                        value={editing.config[f.key] as string}
                        onChange={(c) => updateConfig(f.key, c.toHexString())}
                        showText
                      />
                    </div>
                  </div>
                ))}
                <div>
                  <Typography.Text type="secondary">标题字号（px）</Typography.Text>
                  <Slider
                    min={16}
                    max={32}
                    value={editing.config.title_font_size}
                    onChange={(v) => updateConfig('title_font_size', v)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">正文字号（px）</Typography.Text>
                  <Slider
                    min={12}
                    max={20}
                    value={editing.config.body_font_size}
                    onChange={(v) => updateConfig('body_font_size', v)}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">行距</Typography.Text>
                  <Slider
                    min={1.4}
                    max={2.4}
                    step={0.05}
                    value={editing.config.line_height}
                    onChange={(v) => updateConfig('line_height', v)}
                  />
                </div>
              </div>
              <Space style={{ marginTop: 16 }}>
                <Button type="primary" loading={saving} onClick={save}>
                  保存
                </Button>
                <Button onClick={() => setEditing(null)}>取消</Button>
              </Space>
            </div>
          ) : (
            <Typography.Text type="secondary">
              点击左侧风格进行预览；点击「编辑」修改自定义风格，或「新建自定义风格」创建个人风格。
            </Typography.Text>
          )}

          <Divider />

          <Typography.Text strong>实时预览</Typography.Text>
          <div style={{ maxHeight: 320, overflow: 'auto', marginTop: 8 }}>
            <div className="report-content" style={styleConfigToCssVars(previewConfig)}>
              <MarkdownView content={PREVIEW_MD} />
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}
