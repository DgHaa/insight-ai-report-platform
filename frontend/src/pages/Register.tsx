import { useEffect, useState } from 'react';
import { Button, Card, Form, Input, Select, Typography, message } from 'antd';
import { TeamOutlined, UserOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { authApi, publicApi, type PublicDepartment } from '../api/auth';

interface RegisterForm {
  username: string;
  department_id: string;
}

/** 用户自助注册页：仅需用户名与所属部门 */
export default function Register() {
  const navigate = useNavigate();
  const [departments, setDepartments] = useState<PublicDepartment[]>([]);
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm<RegisterForm>();

  useEffect(() => {
    publicApi
      .departments()
      .then((data) => setDepartments(data.departments))
      .catch(() => undefined);
  }, []);

  const onFinish = async (values: RegisterForm) => {
    setLoading(true);
    try {
      await authApi.register({
        username: values.username,
        department_id: values.department_id,
      });
      message.success('注册成功，请登录');
      // 跳转登录页并携带用户名与部门，登录表单自动预填
      navigate('/login', {
        state: {
          registered: true,
          registeredUsername: values.username,
          registeredDepartmentId: values.department_id,
        },
      });
    } catch {
      /* 错误已由 http 拦截统一提示 */
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <Card style={{ width: 420 }}>
        <Typography.Title level={3} style={{ textAlign: 'center' }}>
          注册账号
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          加入服务部AI洞察平台，开启 AI 报告洞察
        </Typography.Paragraph>
        <Form form={form} onFinish={onFinish} size="large">
          <Form.Item
            name="username"
            rules={[
              { required: true, message: '请输入用户名' },
              { pattern: /^[\u4e00-\u9fa5a-zA-Z0-9_]{3,50}$/, message: '3-50位中英文、数字或下划线' },
            ]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名（3-50位）" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="department_id"
            rules={[{ required: true, message: '请选择所属部门' }]}
          >
            <Select
              placeholder="选择所属部门"
              suffixIcon={<TeamOutlined />}
              options={departments.map((d) => ({ label: d.name, value: d.id }))}
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              注册
            </Button>
          </Form.Item>
        </Form>
        <div style={{ textAlign: 'center' }}>
          <Typography.Text type="secondary">已有账号？</Typography.Text>
          <Button type="link" onClick={() => navigate('/login')}>
            返回登录
          </Button>
        </div>
      </Card>
    </div>
  );
}

