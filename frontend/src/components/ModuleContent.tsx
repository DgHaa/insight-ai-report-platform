import type { CSSProperties } from 'react';
import { Button, Card, Typography } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ModuleChart, ModuleDataPoint } from '../types';
import MarkdownView from './MarkdownView';
import ModuleInsight from './ModuleInsight';

export interface ModuleLike {
  module_title?: string;
  content?: string;
  data_points?: ModuleDataPoint[];
  charts?: ModuleChart[];
}

interface Props {
  module: ModuleLike;
  index: number;
  styleCss?: CSSProperties;
  canEdit?: boolean;
  regenerating?: boolean;
  onRegenerate?: (index: number) => void;
}

/** 单个模块内容卡片：叙述（Markdown）+ 结构化数据点/图表 + 重新生成入口 */
export default function ModuleContent({
  module,
  index,
  styleCss,
  canEdit,
  regenerating,
  onRegenerate,
}: Props) {
  return (
    <Card
      size="small"
      style={{ marginTop: 12 }}
      title={module.module_title || `模块 ${index + 1}`}
      extra={
        canEdit && onRegenerate ? (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={regenerating}
            onClick={() => onRegenerate(index)}
          >
            重新生成
          </Button>
        ) : null
      }
    >
      {module.content ? (
        <div className="report-content" style={styleCss}>
          <MarkdownView content={module.content} />
        </div>
      ) : (
        <Typography.Text type="secondary">（该模块暂无内容）</Typography.Text>
      )}
      <ModuleInsight dataPoints={module.data_points} charts={module.charts} />
    </Card>
  );
}
