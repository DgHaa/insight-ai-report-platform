import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Col,
  Input,
  Pagination,
  Row,
  Select,
  Space,
  Tabs,
  Empty,
  Spin,
} from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { reportApi, type ReportQuery } from '../../api/reports';
import { departmentApi } from '../../api/system';
import type { ReportListItem } from '../../types';
import ReportCard from '../../components/ReportCard';
import { useAuthStore } from '../../store/auth';

type ViewKey = 'my' | 'department' | 'public' | 'all';

export default function ReportList() {
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.user?.role);
  const [view, setView] = useState<ViewKey>('my');
  const [keyword, setKeyword] = useState('');
  const [tag, setTag] = useState('');
  const [status, setStatus] = useState<string>();
  const [departments, setDepartments] = useState<{ id: string; name: string; code: string }[]>([]);
  const [deptId, setDeptId] = useState<string>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [list, setList] = useState<ReportListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // 公开报告按部门筛选下拉的数据源
  useEffect(() => {
    departmentApi
      .departments()
      .then((d) => setDepartments(d.departments))
      .catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: ReportQuery = {
        view,
        keyword: keyword || undefined,
        tag: tag || undefined,
        status: status || undefined,
        // 公开报告/全部报告支持按部门筛选（后端已对对应角色放行）
        department_id: view === 'public' || view === 'all' ? deptId : undefined,
        page,
        page_size: pageSize,
      };
      const data = await reportApi.list(params);
      setList(data.list);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [view, keyword, tag, status, deptId, page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  const tabs = [
    { key: 'my', label: '我的报告' },
    // 超级管理员不显示“部门报告”标签（通过“全部报告”查看所有部门）
    ...(role !== 'super_admin' ? [{ key: 'department' as ViewKey, label: '部门报告' }] : []),
    { key: 'public', label: '公开报告' },
    ...(role === 'super_admin' ? [{ key: 'all' as ViewKey, label: '全部报告' }] : []),
  ];

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }}>
        <Tabs
          activeKey={view}
          items={tabs}
          onChange={(k) => {
            setView(k as ViewKey);
            setPage(1);
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/reports/create')}>
          新建报告
        </Button>
      </Space>

      <Space wrap style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="标题搜索"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setKeyword(v);
            setPage(1);
          }}
        />
        <Input
          placeholder="标签筛选"
          allowClear
          style={{ width: 160 }}
          onChange={(e) => {
            setTag(e.target.value);
            setPage(1);
          }}
        />
        {view === 'public' || view === 'all' ? (
          <Select
            placeholder="按部门筛选"
            allowClear
            style={{ width: 200 }}
            value={deptId}
            options={departments.map((d) => ({ label: d.name, value: d.id }))}
            onChange={(v) => {
              setDeptId(v);
              setPage(1);
            }}
          />
        ) : null}
        <Select
          placeholder="状态"
          allowClear
          style={{ width: 140 }}
          options={[
            { label: '草稿', value: 'draft' },
            { label: '生成中', value: 'generating' },
            { label: '已完成', value: 'completed' },
            { label: '失败', value: 'failed' },
            { label: '超时', value: 'timeout' },
            { label: '已终止', value: 'terminated' },
          ]}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
        />
      </Space>

      <Spin spinning={loading}>
        {list.length === 0 ? (
          <Empty description="暂无报告" style={{ padding: 48 }} />
        ) : (
          <Row gutter={[16, 16]} align="stretch">
            {list.map((r) => (
              <Col
                xs={24}
                sm={12}
                lg={8}
                xl={6}
                key={r.id}
                className="report-card-col"
              >
                <ReportCard report={r} />
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      <div style={{ textAlign: 'center', marginTop: 16 }}>
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger
          showTotal={(t) => `共 ${t} 条`}
          onChange={(p, ps) => {
            setPage(p);
            setPageSize(ps);
          }}
        />
      </div>
    </div>
  );
}
