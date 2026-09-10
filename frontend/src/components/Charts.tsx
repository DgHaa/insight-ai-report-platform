/** 轻量纯 SVG 图表（零额外依赖）：折线图 / 环形图 / 横向条形排行 / 环形进度 */

interface LineChartProps {
  labels: string[];
  values: number[];
  height?: number;
}

export function LineChart({ labels, values, height = 200 }: LineChartProps) {
  const width = 560;
  const pad = 28;
  const max = Math.max(...values, 1);
  const n = values.length;
  const stepX = (width - pad * 2) / Math.max(n - 1, 1);
  const points = values
    .map((v, i) => `${pad + i * stepX},${height - pad - (v / max) * (height - pad * 2)}`)
    .join(' ');

  // 横坐标标签显示间隔（防止标签重叠）：
  // - 数据点 ≤15（如近一周 7 天）：逐日显示
  // - 数据点 16~60（如近一月 30 天）：每隔 7 天显示一个关键日期
  // - 数据点 >60（如近一季度约 90 天）：每隔 30 天显示一个关键日期
  const interval = n > 60 ? 30 : n > 15 ? 7 : 1;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }}>
      <polyline
        points={points}
        fill="none"
        stroke="#1677ff"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {values.map((v, i) => {
        const x = pad + i * stepX;
        const y = height - pad - (v / max) * (height - pad * 2);
        // 仅显示间隔刻度上的标签（数据点仍全部保留在图表中）
        const showLabel = i % interval === 0 || i === n - 1;
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={3} fill="#1677ff">
              {/* 悬停显示完整日期与数值（不受标签间隔影响） */}
              <title>{`${labels[i]} 生成 ${v} 次`}</title>
            </circle>
            {showLabel ? (
              <text x={x} y={height - 6} fontSize={10} textAnchor="middle" fill="#999">
                {labels[i]}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

interface DonutProps {
  data: { name: string; value: number }[];
  size?: number;
}

const COLORS = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96'];

export function DonutChart({ data, size = 180 }: DonutProps) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = size / 2 - 12;
  let acc = 0;
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f0f0f0" strokeWidth={16} />
      {data.map((d, i) => {
        const len = (d.value / total) * 2 * Math.PI * r;
        const start = acc;
        acc += len;
        const end = acc;
        return (
          <circle
            key={i}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={COLORS[i % COLORS.length]}
            strokeWidth={16}
            strokeDasharray={`${len} ${2 * Math.PI * r - len}`}
            strokeDashoffset={-start}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
      })}
      <text x={size / 2} y={size / 2 - 4} textAnchor="middle" fontSize={18} fontWeight={600}>
        {data.reduce((s, d) => s + d.value, 0)}
      </text>
      <text x={size / 2} y={size / 2 + 16} textAnchor="middle" fontSize={11} fill="#999">
        总调用
      </text>
    </svg>
  );
}

export function Legend({ data }: { data: { name: string; value: number }[] }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  return (
    <div>
      {data.map((d, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0' }}>
          <span style={{ width: 10, height: 10, background: COLORS[i % COLORS.length], borderRadius: 2 }} />
          <span style={{ flex: 1 }}>{d.name}</span>
          <span style={{ color: '#999' }}>
            {d.value}（{((d.value / total) * 100).toFixed(1)}%）
          </span>
        </div>
      ))}
    </div>
  );
}

interface RankProps {
  data: { name: string; count: number }[];
}

export function RankBar({ data }: RankProps) {
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div>
      {data.map((d, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 6 }}>
          <span style={{ width: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {d.name}
          </span>
          <div style={{ flex: 1, background: '#f0f0f0', borderRadius: 4, height: 14 }}>
            <div
              style={{
                width: `${(d.count / max) * 100}%`,
                height: 14,
                background: COLORS[i % COLORS.length],
                borderRadius: 4,
              }}
            />
          </div>
          <span style={{ width: 40, textAlign: 'right' }}>{d.count}</span>
        </div>
      ))}
    </div>
  );
}

interface RingProps {
  percent: number;
  size?: number;
  label?: string;
}

export function RingProgress({ percent, size = 120, label }: RingProps) {
  const r = size / 2 - 8;
  const len = 2 * Math.PI * r;
  const done = (percent / 100) * len;
  return (
    <svg width={size} height={size}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#f0f0f0" strokeWidth={10} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="#52c41a"
        strokeWidth={10}
        strokeDasharray={`${done} ${len - done}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fontSize={16} fontWeight={600}>
        {label ?? `${percent.toFixed(1)}%`}
      </text>
    </svg>
  );
}
