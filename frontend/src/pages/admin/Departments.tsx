import { useCallback, useEffect, useState } from 'react';
import { Button, Card, Col, Row, Spin, Tag, Typography, message } from 'antd';
import {
  ArrowRightOutlined,
  BankOutlined,
  TeamOutlined,
  FileTextOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { adminApi, type DepartmentSummary } from '../../api/system';
import BackButton from '../../components/BackButton';

/** 超级管理员：全部门管理 - 部门列表页 */
export default function Departments() {
  const navigate = useNavigate();
  const [departments, setDepartments] = useState<DepartmentSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await adminApi.departments();
      setDepartments(data.departments);
    } catch {
      /* 已统一提示 */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback="/admin" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          部门管理
        </Typography.Title>
      </div>

      <Spin spinning={loading}>
        <Row gutter={[16, 16]}>
          {departments.map((dept) => (
            <Col xs={24} sm={12} lg={8} xl={6} key={dept.id}>
              <Card
                hoverable
                onClick={() => navigate(`/admin/departments/${dept.id}`)}
                style={{ height: '100%', display: 'flex', flexDirection: 'column' }}
                styles={{ body: { flex: 1, display: 'flex', flexDirection: 'column' } }}
              >
                <SpaceBetween>
                  <Typography.Text strong style={{ fontSize: 15 }}>
                    {dept.name}
                  </Typography.Text>
                  <Tag icon={<BankOutlined />} color="blue">
                    {dept.code}
                  </Tag>
                </SpaceBetween>
                <Typography.Paragraph
                  type="secondary"
                  style={{ fontSize: 12, marginTop: 6, marginBottom: 10 }}
                  ellipsis={{ rows: 2 }}
                >
                  {dept.description || '—'}
                </Typography.Paragraph>
                <div style={{ marginTop: 'auto' }}>
                  <SpaceBetween style={{ marginBottom: 8 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      <TeamOutlined /> 成员 {dept.member_count} 人
                    </Typography.Text>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      <FileTextOutlined /> 报告 {dept.report_count} 份
                    </Typography.Text>
                  </SpaceBetween>
                  <Typography.Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 10 }}>
                    <UserOutlined /> 管理员：{dept.admin_name || '未设置'}
                  </Typography.Text>
                  <Button type="primary" block icon={<ArrowRightOutlined />}>
                    进入管理
                  </Button>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
        {!loading && departments.length === 0 ? (
          <Typography.Text type="secondary">暂无部门数据</Typography.Text>
        ) : null}
      </Spin>
    </div>
  );
}

/** 简易两端对齐容器（避免为单处引入额外依赖） */
function SpaceBetween({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
