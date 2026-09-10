import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Table,
  Tabs,
  Typography,
  message,
} from 'antd';
import { DeleteOutlined, EditOutlined, MoonOutlined, PlusOutlined, SunOutlined } from '@ant-design/icons';
import type { Credential } from '../../types';
import { credentialApi } from '../../api/credentials';
import { authApi } from '../../api/auth';
import { useAuthStore } from '../../store/auth';
import { useThemeStore } from '../../store/theme';
import { confirmAction } from '../../components/ConfirmDialog';
import { formatTime } from '../../utils/format';
import BackButton from '../../components/BackButton';
import StyleManager from '../../components/StyleManager';

interface CredentialForm {
  name: string;
  proxy?: string;
  cookies?: string;
  custom_headers?: string;
}

export default function Profile() {
  const [tab, setTab] = useState('credentials');
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Credential | null>(null);
  const [styleManagerOpen, setStyleManagerOpen] = useState(false);
  const [form] = Form.useForm<CredentialForm>();
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailForm] = Form.useForm<{ email: string }>();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const mode = useThemeStore((s) => s.mode);
  const toggleMode = useThemeStore((s) => s.toggleMode);

  const load = useCallback(async () => {
    try {
      setCredentials(await credentialApi.list());
    } catch {
      /* 已统一提示 */
    }
  }, []);

  useEffect(() => {
    if (tab === 'credentials') load();
  }, [tab, load]);

  const openModal = (cred?: Credential | null) => {
    setEditing(cred || null);
    form.setFieldsValue(
      cred
        ? {
            name: cred.name,
            proxy: cred.proxy || '',
            cookies: cred.cookies || '',
            custom_headers: cred.custom_headers ? JSON.stringify(cred.custom_headers) : '',
          }
        : { name: '' },
    );
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    let customHeaders: Record<string, string> | undefined;
    if (values.custom_headers) {
      try {
        customHeaders = JSON.parse(values.custom_headers);
      } catch {
        message.error('自定义请求头不是合法 JSON');
        return;
      }
    }
    const payload = {
      name: values.name,
      proxy: values.proxy || undefined,
      cookies: values.cookies || undefined,
      custom_headers: customHeaders,
    };
    if (editing) {
      await credentialApi.update(editing.id, payload);
      message.success('凭证已更新');
    } else {
      await credentialApi.create(payload);
      message.success('凭证已创建');
    }
    setModalOpen(false);
    load();
  };

  const handleDelete = (id: string, name: string) => {
    confirmAction('删除凭证', `确定删除凭证「${name}」吗？`, async () => {
      await credentialApi.remove(id);
      message.success('已删除');
      load();
    });
  };

  const openEmailEdit = () => {
    emailForm.setFieldsValue({ email: user?.email || '' });
    setEmailModalOpen(true);
  };

  const handleSaveEmail = async () => {
    const values = await emailForm.validateFields();
    setEmailSaving(true);
    try {
      await authApi.updateMe({ email: values.email });
      if (user) setUser({ ...user, email: values.email });
      message.success('邮箱已更新');
      setEmailModalOpen(false);
    } finally {
      setEmailSaving(false);
    }
  };

  return (
    <Row justify="center">
      <Col xs={24} lg={14}>
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
            <BackButton fallback="/reports" />
            <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
              个人中心
            </Typography.Title>
          </div>
          <Tabs
            activeKey={tab}
            onChange={setTab}
            items={[
              { key: 'credentials', label: '数据源凭证' },
              { key: 'styles', label: '报告风格' },
              { key: 'info', label: '个人信息' },
              { key: 'theme', label: '主题设置' },
            ]}
          />

          {tab === 'credentials' ? (
            <div>
              <Space style={{ marginBottom: 12, width: '100%', justifyContent: 'flex-end' }}>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
                  新建凭证
                </Button>
              </Space>
              <Table
                rowKey="id"
                dataSource={credentials}
                pagination={false}
                columns={[
                  { title: '名称', dataIndex: 'name' },
                  { title: '代理', dataIndex: 'proxy', render: (v) => v || '—' },
                  { title: 'Cookie', dataIndex: 'cookies', render: (v) => (v ? `${v.slice(0, 12)}***` : '—') },
                  { title: '创建时间', dataIndex: 'created_at', render: (v) => formatTime(v) },
                  {
                    title: '操作',
                    render: (_, record) => (
                      <Space>
                        <Button size="small" icon={<EditOutlined />} onClick={() => openModal(record)}>
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
            </div>
          ) : null}

          {tab === 'info' ? (
            <Descriptions column={1} bordered>
              <Descriptions.Item label="用户名">{user?.username}</Descriptions.Item>
              <Descriptions.Item label="邮箱">
                <Space>
                  {user?.email}
                  <Button size="small" type="link" onClick={openEmailEdit}>
                    修改
                  </Button>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="部门">{user?.department_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="角色">
                {user?.role === 'super_admin'
                  ? '超级管理员'
                  : user?.role === 'dept_admin'
                    ? '部门管理员'
                    : '普通用户'}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {tab === 'theme' ? (
            <div>
              <Typography.Paragraph type="secondary">选择界面主题（浅色 / 深色）</Typography.Paragraph>
              <Space size={24}>
                <Space
                  direction="vertical"
                  style={{ cursor: 'pointer', opacity: mode === 'light' ? 1 : 0.5 }}
                  onClick={() => mode !== 'light' && toggleMode()}
                >
                  <SunOutlined style={{ fontSize: 40, color: '#faad14' }} />
                  <span>浅色</span>
                </Space>
                <Space
                  direction="vertical"
                  style={{ cursor: 'pointer', opacity: mode === 'dark' ? 1 : 0.5 }}
                  onClick={() => mode !== 'dark' && toggleMode()}
                >
                  <MoonOutlined style={{ fontSize: 40, color: '#722ed1' }} />
                  <span>深色</span>
                </Space>
              </Space>
            </div>
          ) : null}

          {tab === 'styles' ? (
            <div>
              <Typography.Paragraph type="secondary">
                管理报告排版风格：可新建个人风格、编辑/删除自定义风格；部门管理员可将自己的风格共享给本部门同事使用。
              </Typography.Paragraph>
              <Space style={{ marginBottom: 12 }}>
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setStyleManagerOpen(true)}>
                  管理报告风格
                </Button>
              </Space>
            </div>
          ) : null}

          <Modal
            open={modalOpen}
            title={editing ? '编辑凭证' : '新建凭证'}
            okText="保存"
            onOk={handleSave}
            onCancel={() => setModalOpen(false)}
          >
            <Form form={form} layout="vertical">
              <Form.Item name="name" label="凭证名称" rules={[{ required: true, message: '请输入名称' }]}>
                <Input placeholder="如：爬取A网站专用" />
              </Form.Item>
              <Form.Item name="proxy" label="代理">
                <Input placeholder="http://user:pass@192.168.1.1:8080" />
              </Form.Item>
              <Form.Item name="cookies" label="Cookie">
                <Input.TextArea rows={2} placeholder="session_id=abc; token=xyz" />
              </Form.Item>
              <Form.Item name="custom_headers" label="自定义请求头（JSON）">
                <Input.TextArea rows={2} placeholder={'{"Referer": "https://google.com"}'} />
              </Form.Item>
            </Form>
          </Modal>

          <Modal
            open={emailModalOpen}
            title="修改邮箱"
            okText="保存"
            confirmLoading={emailSaving}
            onOk={handleSaveEmail}
            onCancel={() => setEmailModalOpen(false)}
          >
            <Form form={emailForm} layout="vertical">
              <Form.Item
                name="email"
                label="邮箱"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input placeholder="用于接收报告邮件" />
              </Form.Item>
            </Form>
          </Modal>

          <StyleManager
            open={styleManagerOpen}
            onClose={() => setStyleManagerOpen(false)}
          />
        </Card>
      </Col>
    </Row>
  );
}
