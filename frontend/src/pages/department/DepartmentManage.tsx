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
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import type { DashboardStats, User } from '../../types';
import { departmentApi } from '../../api/system';
import { DonutChart, Legend, LineChart, RankBar, RingProgress } from '../../components/Charts';
import { confirmAction } from '../../components/ConfirmDialog';
import { formatTime } from '../../utils/format';
import BackButton from '../../components/BackButton';

export default function DepartmentManage() {
  const [tab, setTab] = useState('dashboard');
  const [timeRange, setTimeRange] = useState('month');
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm] = Form.useForm();

  const loadStats = useCallback(async () => {
    try {
      setStats(await departmentApi.statistics(timeRange));
    } catch {
      /* 已统一提示 */
    }
  }, [timeRange]);

  const loadUsers = useCallback(async () => {
    try {
      const data = await departmentApi.users();
      setUsers(data.users);
    } catch {
      /* 已统一提示 */
    }
  }, []);

  useEffect(() => {
    if (tab === 'dashboard') loadStats();
    if (tab === 'users') loadUsers();
  }, [tab, loadStats, loadUsers]);

  const handleAddUser = async () => {
    const values = await addForm.validateFields();
    await departmentApi.createUser(values);
    message.success('用户已添加');
    setAddOpen(false);
    addForm.resetFields();
    loadUsers();
  };

  const handleRoleChange = async (id: string, role: 'user' | 'dept_admin') => {
    await departmentApi.updateUser(id, { role });
    message.success('角色已更新');
    loadUsers();
  };

  const handleRemoveUser = (id: string, username: string) => {
    confirmAction('移除用户', `确定移除用户 ${username} 吗？`, async () => {
      await departmentApi.removeUser(id);
      message.success('已移除');
      loadUsers();
    });
  };

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback="/reports" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          部门管理
        </Typography.Title>
      </div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'dashboard', label: '统计看板' },
          { key: 'users', label: '用户管理' },
          { key: 'model', label: '公共模型配置' },
        ]}
      />

      {tab === 'dashboard' ? (
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
          {!stats ? (
            <Empty description="暂无统计数据" />
          ) : (
            <Row gutter={[16, 16]}>
              <Col span={14}>
                <Card size="small" title="报告生成趋势">
                  <LineChart labels={stats.generate_trend.labels} values={stats.generate_trend.daily} />
                </Card>
              </Col>
              <Col span={10}>
                <Card size="small" title="模块生成成功率">
                  <Space align="center" size={24}>
                    <RingProgress
                      percent={
                        stats.module_success_rate.total_attempts
                          ? (stats.module_success_rate.success / stats.module_success_rate.total_attempts) * 100
                          : 0
                      }
                    />
                    <div>
                      <div>总尝试：{stats.module_success_rate.total_attempts}</div>
                      <div style={{ color: '#52c41a' }}>成功：{stats.module_success_rate.success}</div>
                      <div style={{ color: '#ff4d4f' }}>失败：{stats.module_success_rate.failed}</div>
                      {Object.entries(stats.module_success_rate.failure_reasons).map(([k, v]) => (
                        <Typography.Text key={k} type="secondary" style={{ fontSize: 12 }}>
                          {k}: {v}{' '}
                        </Typography.Text>
                      ))}
                    </div>
                  </Space>
                </Card>
              </Col>
              <Col span={12}>
                <Card size="small" title="热门关键词排行">
                  {stats.hot_keywords.length ? (
                    <RankBar data={stats.hot_keywords.map((k) => ({ name: k.keyword, count: k.count }))} />
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  )}
                </Card>
              </Col>
              <Col span={12}>
                <Card size="small" title="活跃用户排行">
                  {stats.active_users.length ? (
                    <RankBar data={stats.active_users.map((u) => ({ name: u.username, count: u.generate_count }))} />
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
                      data={stats.model_usage.map((m) => ({ name: `${m.provider}/${m.model}`, value: m.calls }))}
                    />
                    <Legend
                      data={stats.model_usage.map((m) => ({ name: `${m.provider}/${m.model}`, value: m.calls }))}
                    />
                  </Space>
                </Card>
              </Col>
            </Row>
          )}
        </div>
      ) : null}

      {tab === 'users' ? (
        <div>
          <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'flex-end' }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
              添加用户
            </Button>
          </Space>
          <Table
            rowKey="id"
            dataSource={users}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: '用户名', dataIndex: 'username' },
              { title: '邮箱', dataIndex: 'email' },
              {
                title: '角色',
                dataIndex: 'role',
                render: (role: string, record) => (
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
                render: (_, record) =>
                  record.role === 'super_admin' ? null : (
                    <Button size="small" danger onClick={() => handleRemoveUser(record.id, record.username)}>
                      移除
                    </Button>
                  ),
              },
            ]}
          />
        </div>
      ) : null}

      {tab === 'model' ? <PublicModelConfig /> : null}

      <Modal
        open={addOpen}
        title="添加部门用户"
        okText="添加"
        onOk={handleAddUser}
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
    </Card>
  );
}

/**
 * 部门公共模型配置
 *
 * 原先实现把含 api_key 的配置明文写入 localStorage（任何人可读，且是半成品）。
 * 现改为调用后端 /department/model-config：密钥落库加密、接口返回脱敏值。
 */
function PublicModelConfig() {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    departmentApi
      .modelConfig()
      .then((cfg) => {
        if (cancelled || !cfg) return;
        form.setFieldsValue({
          endpoint: cfg.endpoint ?? undefined,
          model_name: cfg.model_name ?? undefined,
          api_key: cfg.api_key ?? undefined,
        });
      })
      .catch(() => {
        /* 已统一提示 */
      });
    return () => {
      cancelled = true;
    };
  }, [form]);

  const handleSave = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      // api_key 留空或为脱敏回显值（含 ****）时，后端会保留原密钥不覆盖
      await departmentApi.saveModelConfig({
        endpoint: values.endpoint,
        model_name: values.model_name,
        api_key: values.api_key,
      });
      message.success('已保存');
    } catch {
      /* 已统一提示 */
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 520 }}>
      <Typography.Paragraph type="secondary">
        设置本部门公共模型配置（默认 API 地址 / 密钥 / 模型），新建模块时可快速引用。
        密钥加密存储，此处仅显示脱敏值，留空表示不修改。
      </Typography.Paragraph>
      <Form form={form} layout="vertical">
        <Form.Item name="endpoint" label="默认 API 地址">
          <Input placeholder="https://xxx/v1/chat/completions" />
        </Form.Item>
        <Form.Item name="api_key" label="默认 API 密钥">
          <Input.Password placeholder="留空则不修改" autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="model_name" label="默认模型名称">
          <Input placeholder="如 Qwen3.8-27B" />
        </Form.Item>
        <Button type="primary" onClick={handleSave} loading={saving}>
          保存
        </Button>
      </Form>
    </div>
  );
}
