import { useMemo } from 'react';
import { Layout, Menu, Dropdown, Avatar, Space, Switch, Typography } from 'antd';
import {
  AppstoreOutlined,
  DashboardOutlined,
  LogoutOutlined,
  MailOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
  MoonOutlined,
  SunOutlined,
} from '@ant-design/icons';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/auth';
import { useThemeStore } from '../store/theme';
import { authApi } from '../api/auth';

const { Header, Sider, Content } = Layout;

export default function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const mode = useThemeStore((s) => s.mode);
  const toggleMode = useThemeStore((s) => s.toggleMode);

  const items = useMemo(() => {
    const list = [
      { key: '/reports', icon: <AppstoreOutlined />, label: '报告中心' },
      { key: '/email-tasks', icon: <MailOutlined />, label: '邮件发送记录' },
    ];
    if (user?.role === 'dept_admin') {
      list.push({ key: '/department/manage', icon: <TeamOutlined />, label: '部门管理' });
    }
    if (user?.role === 'super_admin') {
      list.push({ key: '/admin/departments', icon: <TeamOutlined />, label: '部门管理' });
      list.push({ key: '/admin', icon: <SettingOutlined />, label: '系统管理' });
    }
    list.push({ key: '/profile', icon: <UserOutlined />, label: '个人中心' });
    return list;
  }, [user]);

  const selectedKey =
    items.find((it) => location.pathname.startsWith(it.key))?.key || '/reports';

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      /* 忽略登出失败 */
    }
    clearAuth();
    navigate('/login');
  };

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme={mode === 'dark' ? 'dark' : 'light'} width={200}>
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 16,
            fontWeight: 600,
            color: mode === 'dark' ? '#fff' : '#1677ff',
          }}
        >
          <DashboardOutlined /> AI 洞察
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={items}
          onClick={(e) => navigate(e.key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: mode === 'dark' ? '#141414' : '#fff',
            padding: '0 24px',
          }}
        >
          <Typography.Text strong>服务部AI洞察平台</Typography.Text>
          <Space size={16}>
            <Switch
              checkedChildren={<MoonOutlined />}
              unCheckedChildren={<SunOutlined />}
              checked={mode === 'dark'}
              onChange={toggleMode}
            />
            <Dropdown
              menu={{
                items: [
                  { key: 'profile', icon: <UserOutlined />, label: '个人中心', onClick: () => navigate('/profile') },
                  { type: 'divider' },
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
                ],
              }}
            >
              <Space style={{ cursor: 'pointer' }}>
                <Avatar size="small" icon={<UserOutlined />} />
                <Typography.Text>{user?.username}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {user?.role === 'super_admin' ? '超级管理员' : user?.role === 'dept_admin' ? '部门管理员' : '普通用户'}
                </Typography.Text>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
