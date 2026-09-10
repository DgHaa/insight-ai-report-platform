import { useEffect, useState } from 'react';
import { Button, Card, Form, Input, Select, Typography, message } from 'antd';
import { TeamOutlined, UserOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { authApi, publicApi, type PublicDepartment } from '../api/auth';
import { useAuthStore } from '../store/auth';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [loading, setLoading] = useState(false);
  const [departments, setDepartments] = useState<PublicDepartment[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    publicApi
      .departments()
      .then((data) => setDepartments(data.departments))
      .catch(() => undefined);
  }, []);

  // 注册成功后跳转：自动提示并预填用户名与部门
  useEffect(() => {
    const state = location.state as
      | {
          registered?: boolean;
          registeredUsername?: string;
          registeredDepartmentId?: string;
        }
      | null;
    if (state?.registered) {
      message.success('注册成功，请登录');
      if (state.registeredUsername) {
        form.setFieldValue('username', state.registeredUsername);
      }
      if (state.registeredDepartmentId) {
        form.setFieldValue('department_id', state.registeredDepartmentId);
      }
      // 清除 history state，防止刷新页面重复提示
      window.history.replaceState({}, document.title);
    }
  }, [location.state, form]);

  const onFinish = async (values: { username: string; department_id?: string }) => {
    setLoading(true);
    try {
      const data = await authApi.login(values.username, values.department_id || null);
      setAuth(data.token, data.user);
      message.success('登录成功');
      const from = (location.state as { from?: string } | null)?.from || '/reports';
      navigate(from, { replace: true });
    } catch {
      /* 错误已由 http 拦截统一提示（用户名/部门不匹配、账号禁用） */
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <Card style={{ width: 380 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>
          服务部AI洞察平台
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          为终端BG服务部提供 AI 驱动的洞察报告生成与管理
        </Typography.Paragraph>
        <Form form={form} onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="department_id">
            <Select
              allowClear
              placeholder="选择部门（管理员账号可不选）"
              suffixIcon={<TeamOutlined />}
              options={departments.map((d) => ({ label: d.name, value: d.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登录
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Typography.Text type="secondary">还没有账号？</Typography.Text>
          <Button type="link" onClick={() => navigate('/register')}>
            立即注册
          </Button>
        </div>
      </Card>
    </div>
  );
}
