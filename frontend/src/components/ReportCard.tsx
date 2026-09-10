import { Card, Space, Tag, Typography } from 'antd';
import {
  ClockCircleOutlined,
  EyeOutlined,
  FileDoneOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import type { ReportListItem } from '../types';
import { formatTime } from '../utils/format';
import { STATUS_COLOR, STATUS_TEXT } from '../constants/reportStatus';

/** AIHOT 轻量信息流风格报告卡片（等高布局：标题/描述截断，描述区 flex 撑开，底部信息对齐） */
export default function ReportCard({ report }: { report: ReportListItem }) {
  const navigate = useNavigate();
  return (
    <Card className="report-card" size="small" onClick={() => navigate(`/reports/${report.id}`)}>
      <div className="report-card-body">
        {/* 标题区：标题最多 2 行省略 + 状态/公开徽标 */}
        <div className="report-card-top">
          <span className="report-card-title" title={report.title}>
            {report.title}
          </span>
          <div className="report-card-badges">
            <Tag color={STATUS_COLOR[report.status]}>{STATUS_TEXT[report.status]}</Tag>
            {report.is_public ? (
              <Tag icon={<EyeOutlined />} color="blue">
                公开
              </Tag>
            ) : (
              <Tag>内部</Tag>
            )}
          </div>
        </div>

        {/* 描述区：最多 3 行省略（CSS line-clamp），flex 撑开使底部信息对齐 */}
        <Typography.Paragraph
          className="report-card-desc"
          type="secondary"
          title={report.description || '暂无描述'}
        >
          {report.description || '暂无描述'}
        </Typography.Paragraph>

        {/* 中间信息行：部门 / 版本 / 生成次数 */}
        <Space size={4} wrap className="report-card-tags">
          <Tag icon={<TeamOutlined />} color="geekblue">
            {report.department_name || '未分配部门'}
          </Tag>
          <Tag icon={<FileDoneOutlined />}>V{report.current_version}</Tag>
          <Tag color="purple">生成 {report.generate_count} 次</Tag>
        </Space>

        {/* 底部信息：创建人 + 更新时间 + 关键词标签，固定在卡片底部 */}
        <div className="report-card-footer">
          <div className="report-card-meta">
            <Typography.Text
              type="secondary"
              style={{
                fontSize: 12,
                flex: '1 1 auto',
                minWidth: 0,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              创建人：{report.owner_name || '—'}
            </Typography.Text>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, flexShrink: 0 }}
            >
              <ClockCircleOutlined /> {formatTime(report.updated_at)}
            </Typography.Text>
          </div>
          {report.tags && report.tags.length > 0 ? (
            <div className="report-card-keywords">
              {report.tags.map((t) => (
                <Tag key={t} color="cyan">
                  {t}
                </Tag>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

