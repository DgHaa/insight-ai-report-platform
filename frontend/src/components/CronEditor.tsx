import { Form, InputNumber, Select, Space } from 'antd';
import type { ScheduleConfig } from '../types';

/** 调度配置内部类型（含小时/分钟/天，用于生成 Cron） */
interface ScheduleState extends ScheduleConfig {
  hour?: number;
  minute?: number;
  day?: number;
}

const WEEK_DAYS = [
  { label: '周一', value: 1 },
  { label: '周二', value: 2 },
  { label: '周三', value: 3 },
  { label: '周四', value: 4 },
  { label: '周五', value: 5 },
  { label: '周六', value: 6 },
  { label: '周日', value: 0 },
];

function buildCron(type: string, hour: number, minute: number, day?: number): string {
  if (type === 'daily') return `${minute} ${hour} * * *`;
  if (type === 'weekly') return `${minute} ${hour} * * ${day ?? 1}`;
  if (type === 'monthly') return `${minute} ${hour} ${day ?? 1} * *`;
  return '';
}

/** 从已保存的 cron 反解出 时/分/日，否则重新打开时总是回显默认 8:00 */
function parseCron(cron?: string): { hour?: number; minute?: number; day?: number } {
  if (!cron) return {};
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return {};
  const [mi, h, dom, , dow] = parts;
  const minute = /^\d+$/.test(mi) ? parseInt(mi, 10) : undefined;
  const hour = /^\d+$/.test(h) ? parseInt(h, 10) : undefined;
  if (minute === undefined || hour === undefined) return {};
  if (dow && dow !== '*') {
    const day = /^\d+$/.test(dow) ? parseInt(dow, 10) : undefined;
    return { hour, minute, day };
  }
  if (dom && dom !== '*') {
    const day = /^\d+$/.test(dom) ? parseInt(dom, 10) : undefined;
    return { hour, minute, day };
  }
  return { hour, minute };
}

interface Props {
  value?: ScheduleConfig;
  onChange?: (value: ScheduleConfig) => void;
}

/** 调度配置：手动 / 每日 / 每周 / 每月，生成 Cron 表达式 */
export default function CronEditor({ value, onChange }: Props) {
  // 优先用父组件传入的 时/分/日；否则从已保存的 cron 反解（修复重开后回显 8:00 的问题）
  const parsed = parseCron(value?.cron);
  const schedule: ScheduleState = {
    type: 'manual',
    cron: '',
    hour: 8,
    minute: 0,
    day: 1,
    ...parsed,
    ...value,
  };

  const update = (patch: Partial<ScheduleState>) => {
    const next: ScheduleState = { ...schedule, ...patch };
    if (next.type !== 'manual') {
      next.hour = next.hour ?? 8;
      next.minute = next.minute ?? 0;
      if (next.type === 'weekly') next.day = next.day ?? 1;
      if (next.type === 'monthly') next.day = next.day ?? 1;
      next.cron = buildCron(next.type, next.hour, next.minute, next.day);
    } else {
      next.cron = '';
    }
    onChange?.({ type: next.type, cron: next.cron });
  };

  return (
    <Space wrap>
      <Select
        style={{ width: 120 }}
        value={schedule.type}
        options={[
          { label: '手动', value: 'manual' },
          { label: '每日', value: 'daily' },
          { label: '每周', value: 'weekly' },
          { label: '每月', value: 'monthly' },
        ]}
        onChange={(type) => update({ type })}
      />
      {schedule.type !== 'manual' ? (
        <>
          <Form.Item style={{ marginBottom: 0 }} label="时">
            <InputNumber min={0} max={23} value={schedule.hour} onChange={(v) => update({ hour: v ?? 8 })} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }} label="分">
            <InputNumber min={0} max={59} value={schedule.minute} onChange={(v) => update({ minute: v ?? 0 })} />
          </Form.Item>
          {schedule.type === 'weekly' ? (
            <Form.Item style={{ marginBottom: 0 }} label="星期">
              <Select
                style={{ width: 100 }}
                options={WEEK_DAYS}
                value={schedule.day}
                onChange={(d) => update({ day: d })}
              />
            </Form.Item>
          ) : null}
          {schedule.type === 'monthly' ? (
            <Form.Item style={{ marginBottom: 0 }} label="日">
              <InputNumber min={1} max={31} value={schedule.day} onChange={(d) => update({ day: d ?? 1 })} />
            </Form.Item>
          ) : null}
          <InputNumber style={{ width: 180 }} disabled value={schedule.cron} placeholder="Cron 表达式" />
        </>
      ) : null}
    </Space>
  );
}

