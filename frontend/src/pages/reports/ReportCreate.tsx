import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Steps,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, SettingOutlined, StopOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons';
import { useNavigate, useParams } from 'react-router-dom';
import { reportApi } from '../../api/reports';
import { credentialApi } from '../../api/credentials';
import { styleApi } from '../../api/styles';
import type { Credential, ModuleConfig, ReportConfig, ReportStyle } from '../../types';
import { useAuthStore } from '../../store/auth';
import BackButton from '../../components/BackButton';
import StyleManager from '../../components/StyleManager';
import GenerationProgress from '../../components/GenerationProgress';
import ModuleFormModal from './ModuleFormModal';

interface BasicInfo {
  title: string;
  description?: string;
  type: 'department' | 'personal';
  is_public: boolean;
  tags?: string[];
  style_id?: string;
}

export default function ReportCreate() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.user?.role);
  const user = useAuthStore((s) => s.user);
  const [current, setCurrent] = useState(0);
  const [basicForm] = Form.useForm<BasicInfo>();
  const [modules, setModules] = useState<ModuleConfig[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModuleConfig | null>(null);
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [saving, setSaving] = useState(false);
  const [styles, setStyles] = useState<ReportStyle[]>([]);
  const [styleModalOpen, setStyleModalOpen] = useState(false);
  /** “保存并生成”触发后正在生成的报告ID（用于本页展示进度 + 终止） */
  const [generatingReportId, setGeneratingReportId] = useState<string | null>(null);

  const isEdit = !!id;
  const canCreateDepartment = role === 'dept_admin' || role === 'super_admin';

  useEffect(() => {
    credentialApi.list().then(setCredentials).catch(() => undefined);
    styleApi.list().then(setStyles).catch(() => undefined);
  }, []);

  /** 风格下拉选项：默认（科技蓝） + 全部可用风格（内置/自定义/部门共享） */
  const styleOptions = useMemo(
    () => [
      { label: '默认（科技蓝）', value: '' },
      ...styles.map((s) => ({
        value: s.id,
        label: (
          <Space size={6}>
            <span
              style={{
                display: 'inline-block',
                width: 12,
                height: 12,
                borderRadius: 2,
                background: s.config.primary_color,
              }}
            />
            {s.name}
            {s.type === 'builtin' ? null : s.is_shared ? <Tag color="green">共享</Tag> : <Tag>自定义</Tag>}
          </Space>
        ),
      })),
    ],
    [styles],
  );

  const loadReport = useCallback(async () => {
    if (!id) return;
    try {
      const report = await reportApi.detail(id);
      // 编辑路由守卫：非报告所有者禁止编辑，重定向回详情页
      if (report.owner_id !== user?.id) {
        message.error('您没有权限编辑此报告');
        navigate(`/reports/${id}`, { replace: true });
        return;
      }
      basicForm.setFieldsValue({
        title: report.title,
        description: report.description || undefined,
        type: report.type,
        is_public: report.is_public,
        tags: report.tags || undefined,
        style_id: report.style_id || '',
      });
      setModules(report.config?.modules || []);
    } catch {
      /* 已统一提示 */
    }
  }, [id, basicForm, user, navigate]);

  useEffect(() => {
    if (isEdit) loadReport();
  }, [isEdit, loadReport]);

  const handleSaveModule = (module: ModuleConfig) => {
    if (editing) {
      setModules((prev) => prev.map((m) => (m === editing ? module : m)));
      message.success('模块已更新');
    } else {
      setModules((prev) => [...prev, module]);
      message.success('模块已添加');
    }
    setModalOpen(false);
    setEditing(null);
  };

  const handlePublish = async (generateNow: boolean) => {
    // 基本信息 Form 仅在 current===0 时挂载；进入模块配置/预览页后 Form 已卸载，
    // 此时 validateFields() 返回空对象会导致 title 缺失（后端报 Field required）。
    // 改用 getFieldsValue(true) 读取 Form store 中已填写的值，并手动校验标题。
    const basic = basicForm.getFieldsValue(true);
    if (!basic.title || !String(basic.title).trim()) {
      message.warning('请先填写报告标题');
      setCurrent(0);
      return;
    }
    if (modules.length === 0) {
      message.warning('请至少配置一个模块');
      setCurrent(1);
      return;
    }
    const config: ReportConfig = { modules };
    setSaving(true);
    let reportId = id;
    try {
      if (isEdit && reportId) {
        await reportApi.update(reportId, {
          title: basic.title,
          description: basic.description,
          is_public: basic.is_public,
          tags: basic.tags,
          config,
          style_id: basic.style_id || null,
        });
        message.success('报告已更新');
      } else {
        const created = await reportApi.create({
          title: basic.title,
          description: basic.description,
          type: basic.type,
          is_public: basic.type === 'personal' ? basic.is_public : false,
          tags: basic.tags,
          config,
          style_id: basic.style_id || null,
        });
        reportId = created.id;
        message.success('报告已创建');
      }
      if (generateNow && reportId) {
        await reportApi.generate(reportId, false);
        // 停留本页展示生成进度与终止按钮，完成后自动跳转详情页
        setGeneratingReportId(reportId);
      } else if (reportId) {
        navigate(`/reports/${reportId}`, { replace: true }); // 仅保存草稿
      }
    } catch {
      // 保存/生成异常：错误已由拦截器统一提示，仍跳转详情页查看真实状态
      if (reportId) {
        navigate(`/reports/${reportId}`, { replace: true });
      }
    } finally {
      setSaving(false);
    }
  };

  /** 终止本页正在进行的生成 */
  const handleTerminateGenerating = async () => {
    if (!generatingReportId) return;
    try {
      await reportApi.terminate(generatingReportId);
      message.success('已请求终止，正在停止...');
    } catch {
      /* 已统一提示 */
    }
    // WS 终态事件（terminated）会自动触发 onComplete → 跳转详情页
  };

  const previewJson = useMemo(
    () => JSON.stringify({ ...basicForm.getFieldsValue(), config: { modules } }, null, 2),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [modules, current],
  );

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback={isEdit && id ? `/reports/${id}` : '/reports'} />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          {isEdit ? '编辑报告' : '新建报告'}
        </Typography.Title>
      </div>
      <Steps
        current={current}
        onChange={setCurrent}
        items={[
          { title: '基本信息' },
          { title: '模块配置' },
          { title: '预览与发布' },
        ]}
        style={{ marginBottom: 24, maxWidth: 560 }}
      />

      {current === 0 ? (
        <Form form={basicForm} layout="vertical" initialValues={{ type: 'personal', is_public: false }}>
          <Row gutter={16}>
            <Col span={14}>
              <Form.Item name="title" label="报告标题" rules={[{ required: true, message: '请输入标题' }]}>
                <Input placeholder="如：质量舆情日报" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="type" label="报告类型" rules={[{ required: true }]}>
                <Select
                  options={[
                    { label: '个人报告', value: 'personal' },
                    ...(canCreateDepartment ? [{ label: '部门报告', value: 'department' }] : []),
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={14}>
              <Form.Item name="description" label="报告描述">
                <Input.TextArea rows={3} placeholder="简要说明报告用途" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item
                name="style_id"
                label={
                  <Space>
                    报告风格
                    <Button
                      size="small"
                      type="link"
                      icon={<SettingOutlined />}
                      onClick={() => setStyleModalOpen(true)}
                    >
                      管理
                    </Button>
                  </Space>
                }
                initialValue=""
              >
                <Select options={styleOptions} placeholder="默认（科技蓝）" />
              </Form.Item>
              <Form.Item name="tags" label="标签">
                <Select mode="tags" placeholder="回车添加标签" open={false} suffixIcon={null} />
              </Form.Item>
              <Form.Item name="is_public" label="公开到平台" valuePropName="checked">
                <Switch checkedChildren="公开" unCheckedChildren="内部" />
              </Form.Item>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                公开仅对个人报告生效；部门报告强制对内公开
              </Typography.Text>
            </Col>
          </Row>
          <Space>
            {isEdit ? (
              <Button
                loading={saving}
                disabled={!!generatingReportId}
                onClick={() => handlePublish(false)}
                title="仅保存修改，不调用模型生成报告"
              >
                保存修改
              </Button>
            ) : null}
            <Button type="primary" onClick={() => setCurrent(1)}>
              下一步：模块配置
            </Button>
          </Space>
        </Form>
      ) : null}

      {current === 1 ? (
        <div>
          <List
            header={
              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>已配置模块（{modules.length}）</Typography.Text>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    setEditing(null);
                    setModalOpen(true);
                  }}
                >
                  添加模块
                </Button>
              </Space>
            }
            dataSource={modules}
            locale={{ emptyText: '尚未添加任何模块' }}
            renderItem={(m, idx) => (
              <List.Item
                actions={[
                  <Button
                    key="up"
                    size="small"
                    icon={<ArrowUpOutlined />}
                    disabled={idx === 0}
                    onClick={() =>
                      setModules((prev) => {
                        if (idx <= 0) return prev;
                        const next = [...prev];
                        [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
                        return next;
                      })
                    }
                  >
                    上移
                  </Button>,
                  <Button
                    key="down"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    disabled={idx === modules.length - 1}
                    onClick={() =>
                      setModules((prev) => {
                        if (idx >= prev.length - 1) return prev;
                        const next = [...prev];
                        [next[idx + 1], next[idx]] = [next[idx], next[idx + 1]];
                        return next;
                      })
                    }
                  >
                    下移
                  </Button>,
                  <Button
                    key="edit"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => {
                      setEditing(m);
                      setModalOpen(true);
                    }}
                  >
                    编辑
                  </Button>,
                  <Button
                    key="del"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => setModules((prev) => prev.filter((x) => x !== m))}
                  >
                    删除
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={<Space>{idx + 1}. {m.module_title}</Space>}
                  description={
                    <Space wrap>
                      <Tag color="blue">{m.model_config?.provider}</Tag>
                      <Tag>{m.model_config?.model_name || '未配置模型'}</Tag>
                      <Tag>{m.schedule?.type || 'manual'}</Tag>
                      {m.keywords?.map((k) => (
                        <Tag key={k} color="cyan">{k}</Tag>
                      ))}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
          <Divider />
          <Space>
            <Button onClick={() => setCurrent(0)}>上一步</Button>
            <Button type="primary" onClick={() => setCurrent(2)}>
              下一步：预览与发布
            </Button>
          </Space>
        </div>
      ) : null}

      {current === 2 ? (
        <div>
          <Typography.Paragraph type="secondary">报告完整配置预览（JSON）：</Typography.Paragraph>
          <pre
            style={{
              background: '#f6f8fa',
              borderRadius: 8,
              padding: 16,
              maxHeight: 360,
              overflow: 'auto',
              fontSize: 12,
            }}
          >
            {previewJson}
          </pre>
          <Space>
            <Button onClick={() => setCurrent(1)}>上一步</Button>
            <Button
              type={isEdit ? 'primary' : 'default'}
              loading={saving}
              disabled={!!generatingReportId}
              onClick={() => handlePublish(false)}
            >
              {isEdit ? '保存修改' : '保存草稿'}
            </Button>
            <Button
              type={isEdit ? 'default' : 'primary'}
              loading={saving}
              disabled={!!generatingReportId}
              onClick={() => handlePublish(true)}
            >
              {isEdit ? '保存并生成' : '保存并生成报告'}
            </Button>
          </Space>

          {generatingReportId ? (
            <Card size="small" style={{ marginTop: 16 }} title="正在生成报告">
              <GenerationProgress
                reportId={generatingReportId}
                active
                onComplete={() => navigate(`/reports/${generatingReportId}`, { replace: true })}
              />
              <Space style={{ marginTop: 12 }}>
                <Button danger icon={<StopOutlined />} onClick={handleTerminateGenerating}>
                  终止生成
                </Button>
              </Space>
            </Card>
          ) : null}
        </div>
      ) : null}

      <ModuleFormModal
        open={modalOpen}
        initial={editing}
        credentials={credentials}
        onOk={handleSaveModule}
        onCancel={() => {
          setModalOpen(false);
          setEditing(null);
        }}
      />

      <StyleManager
        open={styleModalOpen}
        onClose={() => setStyleModalOpen(false)}
        onChanged={() => styleApi.list().then(setStyles).catch(() => undefined)}
      />
    </Card>
  );
}
