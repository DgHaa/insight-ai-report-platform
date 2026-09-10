import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  Input,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ReloadOutlined,
  SendOutlined,
  StopOutlined,
  TableOutlined,
} from '@ant-design/icons';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { reportApi } from '../../api/reports';
import type { EmailDelivery, EmailTask } from '../../types';
import { formatTime } from '../../utils/format';
import { confirmAction } from '../../components/ConfirmDialog';
import BackButton from '../../components/BackButton';

const STATUS_META: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '排队中' },
  sending: { color: 'processing', text: '发送中' },
  sent: { color: 'success', text: '已发送' },
  failed: { color: 'error', text: '失败' },
  cancelled: { color: 'warning', text: '已终止' },
};

const TRIGGER_TEXT: Record<string, string> = {
  manual: '手动',
  scheduled: '定时',
  auto: '自动',
};

const FORMAT_TEXT: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  md: 'Markdown',
};

const ACTIVE_STATUS = ['pending', 'sending'];

export default function EmailTasks() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const reportId = searchParams.get('report_id') || undefined;

  const [list, setList] = useState<EmailTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await reportApi.emailTasks({
        page,
        page_size: 10,
        status: statusFilter,
        report_id: reportId,
        keyword: keyword || undefined,
      });
      setList(data.list);
      setTotal(data.total);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, reportId, keyword]);

  useEffect(() => {
    load();
  }, [load]);

  // 存在活跃任务时每 3 秒自动刷新（状态进度展示）
  const hasActive = useMemo(() => list.some((t) => ACTIVE_STATUS.includes(t.status)), [list]);
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => load(), 3000);
    return () => clearInterval(timer);
  }, [hasActive, load]);

  const handleCancel = (task: EmailTask) => {
    confirmAction('终止发送', '确定终止该邮件任务吗？已发出的邮件不撤回。', async () => {
      await reportApi.cancelEmailTask(task.id);
      message.success('已请求终止');
      load();
    });
  };

  const handleResend = (task: EmailTask) => {
    confirmAction('重发邮件', '将按原收件人/格式重新发送一次，确定？', async () => {
      await reportApi.resendEmailTask(task.id);
      message.success('已创建重发任务');
      load();
    });
  };

  const deliverySummary = (task: EmailTask) => {
    const sent = task.deliveries.filter((d) => d.status === 'sent').length;
    const totalD = task.deliveries.length || task.recipients.length;
    return `${sent}/${totalD}`;
  };

  const renderDeliveries = (task: EmailTask) => (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      {task.error_msg ? (
        <Typography.Text type="danger">任务说明：{task.error_msg}</Typography.Text>
      ) : null}
      <Table<EmailDelivery>
        size="small"
        rowKey={(r) => r.recipient}
        pagination={false}
        dataSource={task.deliveries}
        columns={[
          { title: '收件人', dataIndex: 'recipient' },
          {
            title: '状态',
            dataIndex: 'status',
            width: 120,
            render: (v: string) => (
              <Tag color={STATUS_META[v]?.color}>{STATUS_META[v]?.text || v}</Tag>
            ),
          },
          {
            title: '发送时间',
            dataIndex: 'sent_at',
            width: 160,
            render: (v: string | null) => formatTime(v),
          },
          {
            title: '错误信息',
            dataIndex: 'error_msg',
            render: (v: string | null) => v || '—',
          },
        ]}
      />
    </Space>
  );


  const columns = [
    {
      title: '报告',
      dataIndex: 'report_title',
      render: (v: string, t: EmailTask) =>
        t.report_id ? (
          <Button
            type="link"
            style={{ padding: 0 }}
            onClick={() => navigate(`/reports/${t.report_id}`)}
          >
            {v || '—'}
          </Button>
        ) : (
          v || '—'
        ),
    },
    {
      title: '收件人',
      dataIndex: 'recipients',
      render: (v: string[], t: EmailTask) => {
        const meta = STATUS_META[t.status];
        return (
          <Space direction="vertical" size={0}>
            <Typography.Text>{v.join('，')}</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {meta?.text}（{deliverySummary(t)}）
            </Typography.Text>
          </Space>
        );
      },
    },
    {
      title: '格式',
      dataIndex: 'formats',
      width: 150,
      render: (v: string[]) => v.map((f) => <Tag key={f}>{FORMAT_TEXT[f] || f}</Tag>),
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 80,
      render: (v: number | null) => (v ? `V${v}` : '最新'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 130,
      render: (v: string, t: EmailTask) => {
        const meta = STATUS_META[v] || { color: 'default', text: v };
        const totalD = t.deliveries.length || t.recipients.length;
        const done = t.deliveries.filter((d) => d.status !== 'pending').length;
        return (
          <Space direction="vertical" size={4}>
            <Tag color={meta.color}>{meta.text}</Tag>
            {v === 'sending' && totalD > 0 ? (
              <Progress percent={Math.round((done / totalD) * 100)} size="small" style={{ width: 110 }} />
            ) : null}
          </Space>
        );
      },
    },
    {
      title: '触发',
      dataIndex: 'trigger_type',
      width: 80,
      render: (v: string | null) => TRIGGER_TEXT[v || ''] || v || '—',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => formatTime(v),
    },
    {
      title: '发送时间',
      dataIndex: 'sent_at',
      width: 150,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: '操作',
      key: 'actions',
      width: 170,
      render: (_: unknown, t: EmailTask) => (
        <Space size={4}>
          {(t.status === 'pending' || t.status === 'sending') && (
            <Button size="small" danger icon={<StopOutlined />} onClick={() => handleCancel(t)}>
              终止
            </Button>
          )}
          {['sent', 'failed', 'cancelled'].includes(t.status) && (
            <Button size="small" icon={<SendOutlined />} onClick={() => handleResend(t)}>
              重发
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card>
      <Space style={{ marginBottom: 16 }}>
        <BackButton fallback="/reports" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          邮件发送记录
        </Typography.Title>
      </Space>
      <Space style={{ marginBottom: 12 }} wrap>
        <Input.Search
          placeholder="报告标题搜索"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setKeyword(v);
            setPage(1);
          }}
        />
        <Select
          placeholder="状态筛选"
          allowClear
          style={{ width: 140 }}
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
          options={Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.text }))}
        />
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      </Space>
      <Table<EmailTask>
        rowKey="id"
        loading={loading}
        dataSource={list}
        pagination={{
          current: page,
          pageSize: 10,
          total,
          onChange: setPage,
          showTotal: (n) => `共 ${n} 条`,
        }}
        columns={columns}
        expandable={{
          expandedRowRender: (t) => renderDeliveries(t),
          rowExpandable: (t) => t.deliveries.length > 0,
          expandIcon: ({ expanded, onExpand, record }) => (
            <Button
              type="text"
              size="small"
              icon={<TableOutlined rotate={expanded ? 90 : 0} />}
              onClick={(e) => onExpand(record, e)}
            />
          ),
        }}
      />
      {hasActive ? (
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          有任务正在发送中，页面每 3 秒自动刷新。
        </Typography.Text>
      ) : null}
    </Card>
  );
}
