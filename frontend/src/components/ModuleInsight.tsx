import { Typography } from 'antd';
import type { ModuleChart, ModuleDataPoint } from '../types';

const COLORS = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96'];

/** 单个数据点卡片（量化结论） */
function DataPointCard({ dp }: { dp: ModuleDataPoint }) {
  const trend =
    dp.trend === 'up'
      ? { s: '▲', c: '#52c41a', t: '上升' }
      : dp.trend === 'down'
        ? { s: '▼', c: '#f5222d', t: '下降' }
        : dp.trend === 'flat'
          ? { s: '▶', c: '#999', t: '持平' }
          : null;
  return (
    <div
      style={{
        border: '1px solid #f0f0f0',
        borderRadius: 8,
        padding: '10px 12px',
        minWidth: 160,
        flex: '1 1 160px',
      }}
    >
      <div style={{ fontSize: 12, color: '#666' }}>{dp.label}</div>
      <div style={{ fontSize: 20, fontWeight: 600, marginTop: 4 }}>
        {dp.value}
        {dp.unit ? (
          <span style={{ fontSize: 12, fontWeight: 400, color: '#999' }}> {dp.unit}</span>
        ) : null}
        {trend ? (
          <span style={{ color: trend.c, fontSize: 14, marginLeft: 6 }} title={trend.t}>
            {trend.s}
          </span>
        ) : null}
      </div>
      {dp.note ? (
        <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>{dp.note}</div>
      ) : null}
    </div>
  );
}

function ChartFrame({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 12, marginTop: 8 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      {children}
      {caption ? (
        <div style={{ fontSize: 12, color: '#999', marginTop: 6 }}>{caption}</div>
      ) : null}
    </div>
  );
}

function BarChart({
  labels,
  values,
  title,
  caption,
}: {
  labels: string[];
  values: number[];
  title: string;
  caption?: string;
}) {
  const width = 480;
  const height = 200;
  const pad = 28;
  const max = Math.max(...(values.length ? values : [1]), 1);
  const n = values.length;
  const bw = (width - pad * 2) / Math.max(n, 1);
  return (
    <ChartFrame title={title} caption={caption}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }}>
        {values.map((v, i) => {
          const h = (v / max) * (height - pad * 2);
          const x = pad + i * bw + bw * 0.15;
          const w = bw * 0.7;
          const y = height - pad - h;
          return (
            <g key={i}>
              <rect x={x} y={y} width={w} height={h} rx={3} fill={COLORS[i % COLORS.length]} />
              <text x={x + w / 2} y={height - 10} fontSize={10} textAnchor="middle" fill="#999">
                {labels[i]}
              </text>
              <text x={x + w / 2} y={y - 4} fontSize={10} textAnchor="middle" fill="#333">
                {v}
              </text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

function LineChart({
  labels,
  values,
  title,
  caption,
}: {
  labels: string[];
  values: number[];
  title: string;
  caption?: string;
}) {
  const width = 480;
  const height = 200;
  const pad = 28;
  const max = Math.max(...(values.length ? values : [1]), 1);
  const n = values.length;
  const stepX = (width - pad * 2) / Math.max(n - 1, 1);
  const points = values
    .map((v, i) => `${pad + i * stepX},${height - pad - (v / max) * (height - pad * 2)}`)
    .join(' ');
  const interval = n > 30 ? 10 : 1;
  return (
    <ChartFrame title={title} caption={caption}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }}>
        <polyline points={points} fill="none" stroke="#1677ff" strokeWidth={2} />
        {values.map((v, i) => {
          const x = pad + i * stepX;
          const y = height - pad - (v / max) * (height - pad * 2);
          return (
            <g key={i}>
              <circle cx={x} cy={y} r={3} fill="#1677ff">
                <title>{`${labels[i]}: ${v}`}</title>
              </circle>
            </g>
          );
        })}
        {labels.map((l, i) =>
          i % interval === 0 || i === n - 1 ? (
            <text key={i} x={pad + i * stepX} y={height - 10} fontSize={10} textAnchor="middle" fill="#999">
              {l}
            </text>
          ) : null,
        )}
      </svg>
    </ChartFrame>
  );
}

function PieChart({
  labels,
  values,
  title,
  caption,
}: {
  labels: string[];
  values: number[];
  title: string;
  caption?: string;
}) {
  const size = 200;
  const r = size / 2 - 14;
  const total = values.reduce((s, v) => s + v, 0) || 1;
  let acc = 0;
  return (
    <ChartFrame title={title} caption={caption}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <svg width={size} height={size}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f0f0f0" strokeWidth={18} />
          {values.map((v, i) => {
            const len = (v / total) * 2 * Math.PI * r;
            const start = acc;
            acc += len;
            return (
              <circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={18}
                strokeDasharray={`${len} ${2 * Math.PI * r - len}`}
                strokeDashoffset={-start}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
              />
            );
          })}
        </svg>
        <div>
          {values.map((v, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '2px 0' }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: COLORS[i % COLORS.length] }} />
              <span style={{ flex: 1 }}>{labels[i]}</span>
              <span style={{ color: '#999' }}>{((v / total) * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      </div>
    </ChartFrame>
  );
}

function ModuleChartView({ chart }: { chart: ModuleChart }) {
  if (chart.type === 'pie') {
    const labels = chart.x && chart.x.length ? chart.x : chart.series.map((s) => s.name);
    const values = chart.series.length ? chart.series[0].data : [];
    return <PieChart labels={labels} values={values} title={chart.title} caption={chart.caption} />;
  }
  const labels = chart.x || [];
  const values = chart.series.length ? chart.series[0].data : [];
  if (chart.type === 'line') {
    return <LineChart labels={labels} values={values} title={chart.title} caption={chart.caption} />;
  }
  return <BarChart labels={labels} values={values} title={chart.title} caption={chart.caption} />;
}

/** 模块洞察辅助组件：关键数据点卡片 + 图表（结构化输出渲染） */
export default function ModuleInsight({
  dataPoints,
  charts,
}: {
  dataPoints?: ModuleDataPoint[];
  charts?: ModuleChart[];
}) {
  if ((!dataPoints || !dataPoints.length) && (!charts || !charts.length)) return null;
  return (
    <div style={{ marginTop: 12 }}>
      {dataPoints && dataPoints.length ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            关键数据点
          </Typography.Text>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
            {dataPoints.map((dp, i) => (
              <DataPointCard key={i} dp={dp} />
            ))}
          </div>
        </>
      ) : null}
      {charts && charts.length ? (
        <div style={{ marginTop: 12 }}>
          {charts.map((ch, i) => (
            <ModuleChartView key={i} chart={ch} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
