import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { adminApi, type DepartmentSummary } from '../../api/system';
import type { DashboardStats } from '../../types';
import {
  DonutChart,
  Legend,
  LineChart,
  RankBar,
  RingProgress,
} from '../../components/Charts';
import { confirmAction } from '../../components/ConfirmDialog';
import { formatTime } from '../../utils/format';
import BackButton from '../../components/BackButton';

/** 超级管理员：单个部门管理详情页（统计看板 / 用户管理 / 公共模型配置） */
export default function DepartmentDetail() {
  const { departmentId = '' } = useParams<{ departmentId: string }>();
  const [dept, setDept] = useState<DepartmentSummary | null>(null);
  const [tab, setTab] = useState('dashboard');

  useEffect(() => {
    adminApi
      .departments()
      .then((data) => {
        const found = data.departments.find((d) => d.id === departmentId);
        setDept(found || null);
      })
      .catch(() => undefined);
  }, [departmentId]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback="/admin/departments" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          {dept ? dept.name : '部门管理'}
        </Typography.Title>
      </div>

      <Card>
        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            { key: 'dashboard', label: '统计看板' },
            { key: 'users', label: '用户管理' },
            { key: 'model', label: '公共模型配置' },
          ]}
        />

        {tab === 'dashboard' ? <DashboardTab departmentId={departmentId} /> : null}
        {tab === 'users' ? <UsersTab departmentId={departmentId} /> : null}
        {tab === 'model' ? <ModelConfigsTab departmentId={departmentId} /> : null}
      </Card>
    </div>
  );
}

/* ==================== Tab1 统计看板 ==================== */

function DashboardTab({ departmentId }: { departmentId: string }) {
  const [timeRange, setTimeRange] = useState('month');
  const [stats, setStats] = useState<DashboardStats | null>(null);

  useEffect(() => {
    adminApi
      .departmentStatistics(departmentId, timeRange)
      .then(setStats)
      .catch(() => undefined);
  }, [departmentId, timeRange]);

  if (!stats) {
    return <Spin style={{ display: 'block', margin: '60px auto' }} />;
  }

  const successRate = stats.module_success_rate || {};
  const percent = successRate.total_attempts
    ? (successRate.success / successRate.total_attempts) * 100
    : 0;

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Typography.Text>时间范围：</Typography.Text>
        <Select
          value={timeRange}
          style={{ width: 120 }}
          options={[
            { label: '近一周', value: 'week' },
            { label: '近一月', value: 'month' },
            { label: '近一季度', value: 'quarter' },
          ]}
          onChange={setTimeRange}
        />
      </Space>
      <Row gutter={[16, 16]}>
        <Col span={14}>
          <Card size="small" title="报告生成趋势">
            <LineChart labels={stats.generate_trend.labels} values={stats.generate_trend.daily} />
          </Card>
        </Col>
        <Col span={10}>
          <Card size="small" title="模块生成成功率">
            <Space align="center" size={24}>
              <RingProgress percent={percent} />
              <div>
                <div>总尝试：{successRate.total_attempts}</div>
                <div style={{ color: '#52c41a' }}>成功：{successRate.success}</div>
                <div style={{ color: '#ff4d4f' }}>失败：{successRate.failed}</div>
                {Object.entries(successRate.failure_reasons || {}).map(([k, v]) => (
                  <Typography.Text key={k} type="secondary" style={{ fontSize: 12 }}>
                    {k}: {String(v)}{' '}
                  </Typography.Text>
                ))}
              </div>
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="热门关键词排行">
            {stats.hot_keywords.length ? (
              <RankBar
                data={stats.hot_keywords.map((k: any) => ({ name: k.keyword, count: k.count }))}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="活跃用户排行">
            {stats.active_users.length ? (
              <RankBar
                data={stats.active_users.map((u: any) => ({ name: u.username, count: u.generate_count }))}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="模型调用分布">
            <Space>
              <DonutChart
                size={160}
                data={stats.model_usage.map((m: any) => ({ name: `${m.provider}/${m.model}`, value: m.calls }))}
              />
              <Legend
                data={stats.model_usage.map((m: any) => ({ name: `${m.provider}/${m.model}`, value: m.calls }))}
              />
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
}

/* ==================== Tab2 用户管理 ==================== */

function UsersTab({ departmentId }: { departmentId: string }) {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.departmentUsers(departmentId);
      setUsers(data.users);
    } catch {
      /* 已统一提示 */
    } finally {
      setLoading(false);
    }
  }, [departmentId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async () => {
    const values = await addForm.validateFields();
    await adminApi.createDepartmentUser(departmentId, values);
    message.success('用户已添加');
    setAddOpen(false);
    addForm.resetFields();
    load();
  };

  const handleRoleChange = async (id: string, role: 'user' | 'dept_admin') => {
    await adminApi.updateDepartmentUser(departmentId, id, { role });
    message.success('角色已更新');
    load();
  };

  const handleRemove = (id: string, username: string) => {
    confirmAction('移除用户', `确定移除用户 ${username} 吗？`, async () => {
      await adminApi.removeDepartmentUser(departmentId, id);
      message.success('已移除');
      load();
    });
  };

  return (
    <div>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'flex-end' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
          添加用户
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={users}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '用户名', dataIndex: 'username' },
          { title: '邮箱', dataIndex: 'email' },
          {
            title: '角色',
            dataIndex: 'role',
            render: (role: string, record: any) => (
              <Select
                size="small"
                value={role}
                disabled={role === 'super_admin'}
                options={[
                  { label: '普通用户', value: 'user' },
                  { label: '部门管理员', value: 'dept_admin' },
                ]}
                onChange={(v) => handleRoleChange(record.id, v as 'user' | 'dept_admin')}
              />
            ),
          },
          {
            title: '状态',
            dataIndex: 'is_active',
            render: (active: boolean) =>
              active ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>,
          },
          { title: '报告数', dataIndex: 'report_count' },
          { title: '最近活跃', dataIndex: 'last_active', render: (v: string) => formatTime(v) },
          {
            title: '操作',
            render: (_, record: any) =>
              record.role === 'super_admin' ? null : (
                <Button
                  size="small"
                  danger
                  onClick={() => handleRemove(record.id, record.username)}
                >
                  移除
                </Button>
              ),
          },
        ]}
      />

      <Modal
        open={addOpen}
        title="添加部门用户"
        okText="添加"
        onOk={handleAdd}
        onCancel={() => setAddOpen(false)}
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input placeholder="3-50位字母数字" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email', message: '请输入邮箱' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="user">
            <Select
              options={[
                { label: '普通用户', value: 'user' },
                { label: '部门管理员', value: 'dept_admin' },
              ]}
            />
          </Form.Item>
          <Form.Item name="password" label="初始密码" tooltip="缺省使用占位密码 User@2026">
            <Input.Password placeholder="可选，8位以上" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

/* ==================== Tab3 公共模型配置 ==================== */

interface ModelFormValues {
  name: string;
  provider?: string;
  endpoint?: string;
  model_name?: string;
  api_key?: string; // 编辑时留空 = 不修改已保存密钥
}

function ModelConfigsTab({ departmentId }: { departmentId: string }) {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [form] = Form.useForm<ModelFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.departmentModelConfigs(departmentId);
      setItems(data.items);
    } catch {
      /* 已统一提示 */
    } finally {
      setLoading(false);
    }
  }, [departmentId]);

  useEffect(() => {
    load();
  }, [load]);

  const openModal = (item?: any | null) => {
    setEditing(item || null);
    form.resetFields();
    if (item) {
      // api_key 不预填明文（后端仅返回脱敏值）；编辑留空表示不修改
      form.setFieldsValue({
        name: item.name,
        provider: item.provider || undefined,
        endpoint: item.endpoint || undefined,
        model_name: item.model_name || undefined,
        api_key: undefined,
      });
    }
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    if (editing) {
      await adminApi.updateDepartmentModelConfig(departmentId, editing.id, values);
      message.success('配置已更新');
    } else {
      await adminApi.createDepartmentModelConfig(departmentId, values);
      message.success('配置已创建');
    }
    setModalOpen(false);
    load();
  };

  const handleDelete = (id: string, name: string) => {
    confirmAction('删除配置', `确定删除公共模型配置「${name}」吗？`, async () => {
      await adminApi.removeDepartmentModelConfig(departmentId, id);
      message.success('已删除');
      load();
    });
  };

  return (
    <div>
      <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'flex-end' }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
          新增配置
        </Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
        API Key 已脱敏存储，任何列表与详情中均不显示明文，也不提供查看/复制明文入口。
      </Typography.Paragraph>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '名称', dataIndex: 'name' },
          { title: '提供商', dataIndex: 'provider', render: (v: string) => v || '—' },
          { title: '模型', dataIndex: 'model_name', render: (v: string) => v || '—' },
          {
            title: 'API 地址',
            dataIndex: 'endpoint',
            ellipsis: true,
            render: (v: string) => v || '—',
          },
          {
            title: 'API Key',
            dataIndex: 'api_key',
            render: (v: string) =>
              v ? (
                <Typography.Text code style={{ color: '#8c8c8c' }}>
                  {v}
                </Typography.Text>
              ) : (
                <Typography.Text type="secondary">未设置</Typography.Text>
              ),
          },
          { title: '更新时间', dataIndex: 'updated_at', render: (v: string) => formatTime(v) },
          {
            title: '操作',
            render: (_, record: any) => (
              <Space size={4}>
                <Button
                  size="small"
                  icon={<EditOutlined />}
                  onClick={() => openModal(record)}
                >
                  编辑
                </Button>
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => handleDelete(record.id, record.name)}
                >
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
      />

      <Modal
        open={modalOpen}
        title={editing ? '编辑公共模型配置' : '新增公共模型配置'}
        okText="保存"
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={560}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：质量分析模型" />
          </Form.Item>
          <Form.Item name="provider" label="提供商">
            <Select
              allowClear
              placeholder="选择模型提供商"
              options={[
                { label: '昇腾（华为云MaaS/MindIE）', value: 'ascend' },
                { label: 'OpenAI', value: 'openai' },
                { label: 'Anthropic（Claude）', value: 'anthropic' },
                { label: '自定义（OpenAI兼容）', value: 'custom' },
              ]}
            />
          </Form.Item>
          <Form.Item name="endpoint" label="API 地址">
            <Input placeholder="https://xxx/v1/chat/completions" />
          </Form.Item>
          <Form.Item name="model_name" label="模型名称">
            <Input placeholder="如 Qwen3.8-27B" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={editing ? 'API Key（留空则不修改）' : 'API Key'}
            tooltip={editing ? '出于安全考虑不显示已保存的密钥；留空保存将保留原密钥。' : undefined}
          >
            <Input.Password placeholder={editing ? '留空表示不修改已保存的密钥' : 'sk-...'} autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
