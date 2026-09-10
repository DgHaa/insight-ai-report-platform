import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Space,
  Switch,
  Table,
  Tabs,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import type { ReportListItem, SystemConfig, WhitelistItem } from '../../types';
import { adminApi } from '../../api/system';
import { confirmAction } from '../../components/ConfirmDialog';
import { formatTime } from '../../utils/format';
import BackButton from '../../components/BackButton';

export default function SystemAdmin() {
  const [tab, setTab] = useState('whitelist');
  const [domains, setDomains] = useState<WhitelistItem[]>([]);
  const [domain, setDomain] = useState('');
  const [domainDesc, setDomainDesc] = useState('');
  const [config, setConfig] = useState<SystemConfig | null>(null);
  const [configForm] = Form.useForm();
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [reportTotal, setReportTotal] = useState(0);
  const [reportPage, setReportPage] = useState(1);
  const [reportKeyword, setReportKeyword] = useState('');
  const [reportDept, setReportDept] = useState('');

  const loadWhitelist = useCallback(async () => {
    const data = await adminApi.whitelist();
    setDomains(data.domains);
  }, []);

  const loadConfig = useCallback(async () => {
    const data = await adminApi.systemConfig();
    setConfig(data);
    configForm.setFieldsValue({
      ...data,
      smtp: { ...data.smtp, password: undefined },
    });
  }, [configForm]);

  const loadReports = useCallback(async () => {
    const data = await adminApi.allReports({
      page: reportPage,
      page_size: 10,
      keyword: reportKeyword || undefined,
      department_id: reportDept || undefined,
    });
    setReports(data.list);
    setReportTotal(data.total);
  }, [reportPage, reportKeyword, reportDept]);

  useEffect(() => {
    if (tab === 'whitelist') loadWhitelist();
    if (tab === 'config') loadConfig();
    if (tab === 'reports') loadReports();
  }, [tab, loadWhitelist, loadConfig, loadReports]);

  const handleAddDomain = async () => {
    if (!domain.trim()) {
      message.warning('请输入域名');
      return;
    }
    await adminApi.addWhitelist({ domain: domain.trim(), description: domainDesc || undefined });
    message.success('已添加');
    setDomain('');
    setDomainDesc('');
    loadWhitelist();
  };

  const handleRemoveDomain = (id: string, d: string) => {
    confirmAction('删除白名单', `确定删除域名 ${d} 吗？`, async () => {
      await adminApi.removeWhitelist(id);
      message.success('已删除');
      loadWhitelist();
    });
  };

  const handleSaveConfig = async () => {
    const values = await configForm.validateFields();
    await adminApi.updateSystemConfig(values);
    message.success('系统配置已更新');
    loadConfig();
  };

  const [testingSmtp, setTestingSmtp] = useState(false);

  const handleTestSmtp = async () => {
    const v = configForm.getFieldsValue();
    const smtp = v?.smtp || {};
    if (!smtp.host) {
      message.warning('请先填写 SMTP 服务器');
      return;
    }
    setTestingSmtp(true);
    try {
      const res = await adminApi.testSmtp({
        host: smtp.host,
        port: smtp.port || 587,
        username: smtp.username,
        password: smtp.password || '',
        tls: smtp.tls ?? true,
      });
      if (res.success) {
        message.success(`${res.message}（${res.latency_ms}ms）`);
      } else {
        message.error(`连接失败：${res.message}`);
      }
    } finally {
      setTestingSmtp(false);
    }
  };

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback="/reports" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          系统管理
        </Typography.Title>
      </div>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'whitelist', label: '外部邮箱白名单' },
          { key: 'config', label: '系统配置' },
          { key: 'reports', label: '全部报告' },
        ]}
      />

      {tab === 'whitelist' ? (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Input
              placeholder="域名，如 @partner.com"
              style={{ width: 220 }}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
            />
            <Input
              placeholder="备注"
              style={{ width: 220 }}
              value={domainDesc}
              onChange={(e) => setDomainDesc(e.target.value)}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddDomain}>
              添加
            </Button>
          </Space>
          <Table
            rowKey="id"
            dataSource={domains}
            pagination={false}
            columns={[
              { title: '域名', dataIndex: 'domain' },
              { title: '备注', dataIndex: 'description', render: (v) => v || '—' },
              { title: '创建时间', dataIndex: 'created_at', render: (v) => formatTime(v) },
              {
                title: '操作',
                render: (_, record) => (
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => handleRemoveDomain(record.id, record.domain)}
                  >
                    删除
                  </Button>
                ),
              },
            ]}
          />
        </div>
      ) : null}

      {tab === 'config' ? (
        <Form form={configForm} layout="vertical" style={{ maxWidth: 520 }}>
          <Card size="small" title="SMTP 配置" style={{ marginBottom: 16 }}>
            <Form.Item name={['smtp', 'host']} label="SMTP 服务器">
              <Input placeholder="smtp.company.com" />
            </Form.Item>
            <Form.Item name={['smtp', 'port']} label="端口">
              <InputNumber min={1} max={65535} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name={['smtp', 'username']} label="用户名">
              <Input placeholder="noreply@company.com" />
            </Form.Item>
            <Form.Item name={['smtp', 'password']} label="密码（留空则不修改）">
              <Input.Password placeholder="••••••" />
            </Form.Item>
            <Form.Item name={['smtp', 'sender']} label="发件人">
              <Input placeholder="noreply@company.com" />
            </Form.Item>
            <Form.Item name={['smtp', 'tls']} label="启用 TLS" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Button loading={testingSmtp} onClick={handleTestSmtp}>
              测试 SMTP 连接
            </Button>
          </Card>
          <Card size="small" title="任务配置" style={{ marginBottom: 16 }}>
            <Form.Item name="max_concurrent_tasks" label="最大并发生成任务数">
              <InputNumber min={1} max={50} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="task_timeout_seconds" label="生成超时时间（秒）">
              <InputNumber min={60} max={7200} step={60} style={{ width: '100%' }} />
            </Form.Item>
          </Card>
          <Card size="small" title="邮件发送模式" style={{ marginBottom: 16 }}>
            <Form.Item
              name="email_simulate"
              label="模拟发送（开启时不真正调用 SMTP，任务直接标记已发送）"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              生产环境请关闭模拟发送，并确保上方 SMTP 配置可连通。
            </Typography.Text>
          </Card>
          <Button type="primary" onClick={handleSaveConfig}>
            保存系统配置
          </Button>
          {config ? (
            <div style={{ marginTop: 8 }}>
              当前：并发 {config.max_concurrent_tasks}，超时 {config.task_timeout_seconds}s，
              模拟发送 {config.email_simulate ? '开启' : '关闭'}
            </div>
          ) : null}
        </Form>
      ) : null}

      {tab === 'reports' ? (
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Input.Search
              placeholder="标题搜索"
              allowClear
              style={{ width: 200 }}
              onSearch={(v) => {
                setReportKeyword(v);
                setReportPage(1);
              }}
            />
            <Input
              placeholder="部门ID筛选"
              allowClear
              style={{ width: 200 }}
              onChange={(e) => {
                setReportDept(e.target.value);
                setReportPage(1);
              }}
            />
          </Space>
          <Table
            rowKey="id"
            dataSource={reports}
            pagination={{
              current: reportPage,
              pageSize: 10,
              total: reportTotal,
              onChange: setReportPage,
            }}
            columns={[
              { title: '标题', dataIndex: 'title' },
              { title: '部门', dataIndex: 'department_name', render: (v) => v || '—' },
              { title: '创建人', dataIndex: 'owner_name', render: (v) => v || '—' },
              { title: '类型', dataIndex: 'type' },
              { title: '状态', dataIndex: 'status' },
              { title: '版本', dataIndex: 'current_version', render: (v) => `V${v}` },
              { title: '更新时间', dataIndex: 'updated_at', render: (v) => formatTime(v) },
            ]}
          />
        </div>
      ) : null}
    </Card>
  );
}
