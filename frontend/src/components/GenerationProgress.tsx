import { useEffect, useRef, useState } from 'react';
import { Alert, Progress, Space, Tag, Typography } from 'antd';
import { useAuthStore } from '../store/auth';
import type { ProgressEvent } from '../types';
import { buildProgressWsUrl } from '../utils/format';

interface Props {
  reportId: string;
  active: boolean;
  onComplete?: () => void;
  /** 模块完成（渐进渲染）：父组件可边生成边展示内容 */
  onModuleDone?: (
    moduleTitle: string,
    content: string,
    index: number,
    dataPoints?: unknown[],
    charts?: unknown[],
  ) => void;
}

/** 进度阶段的中文文案（原实现直接显示英文大写） */
const PHASE_TEXT: Record<string, string> = {
  init: '准备中',
  fetching: '抓取数据',
  building: '整合上下文',
  generating: '模型生成中',
  storing: '保存版本',
  module_done: '模块完成',
  complete: '完成',
  failed: '失败',
  timeout: '超时',
  terminated: '已终止',
};

/** WebSocket 生成进度条：连接 /api/v1/reports/{id}/generate/progress?token=JWT */
export default function GenerationProgress({ reportId, active, onComplete, onModuleDone }: Props) {
  const token = useAuthStore((s) => s.token);
  const [event, setEvent] = useState<ProgressEvent | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const terminalRef = useRef(false);
  const onCompleteRef = useRef(onComplete);
  const onModuleDoneRef = useRef(onModuleDone);
  onCompleteRef.current = onComplete;
  onModuleDoneRef.current = onModuleDone;

  // 已耗时计时器：模型调用阶段进度可能长时间不动，让用户知道任务仍在运行
  useEffect(() => {
    if (!active || !event || ['complete', 'failed', 'timeout', 'terminated'].includes(event.phase)) {
      return;
    }
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [active, event]);

  useEffect(() => {
    if (!active || !reportId || !token) return;
    let closed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const MAX_RETRY = 5;

    const connect = (attempt: number) => {
      const ws = new WebSocket(buildProgressWsUrl(reportId, token));
      wsRef.current = ws;
      setEvent(null);
      setElapsed(0);

      ws.onmessage = (msg) => {
        try {
          const ev = JSON.parse(msg.data) as ProgressEvent;
          setEvent(ev);
          if (ev.phase === 'module_done') {
            onModuleDoneRef.current?.(
              ev.payload?.module_title || '',
              ev.payload?.content || '',
              ev.payload?.index || ev.current || 0,
              ev.payload?.data_points,
              ev.payload?.charts,
            );
            return;
          }
          const terminal = ['complete', 'failed', 'timeout', 'terminated'];
          if (terminal.includes(ev.phase)) {
            terminalRef.current = true;
            // 任何终态（成功/失败/超时/终止）都通知父组件复位并重新拉取详情，避免按钮卡在置灰
            onCompleteRef.current?.();
            setTimeout(() => ws.close(), 100);
          }
        } catch {
          /* ignore */
        }
      };
      ws.onerror = () => {
        setEvent({ phase: 'failed', progress: 0, message: '进度连接失败，正在重连...' });
      };
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        if (!terminalRef.current && !closed && attempt < MAX_RETRY) {
          retryTimer = setTimeout(() => connect(attempt + 1), 1200);
        } else if (!terminalRef.current) {
          // 重连次数耗尽：通知父组件收敛状态（避免按钮永久置灰）
          terminalRef.current = true;
          onCompleteRef.current?.();
        }
      };
    };

    terminalRef.current = false;
    connect(0);

    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [reportId, active, token]);

  if (!active || !event) return null;

  const isError = event.phase === 'failed' || event.phase === 'terminated' || event.phase === 'timeout';
  const isDone = event.phase === 'complete';
  const phaseText = PHASE_TEXT[event.phase] || event.phase;
  const moduleInfo =
    event.current && event.total ? `模块 ${event.current}/${event.total}` : undefined;
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(elapsed % 60).padStart(2, '0');

  return (
    <Alert
      type={isError ? 'error' : isDone ? 'success' : 'info'}
      showIcon
      message={
        <Space direction="vertical" style={{ width: '100%' }}>
          <Space wrap>
            <Progress
              percent={event.progress}
              size="small"
              status={isError ? 'exception' : isDone ? 'success' : 'active'}
              style={{ width: 220 }}
            />
            <Tag color={isDone ? 'green' : isError ? 'red' : 'blue'}>{phaseText}</Tag>
            {moduleInfo ? <Tag>{moduleInfo}</Tag> : null}
            {!isDone && !isError ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                已耗时 {mm}:{ss}
              </Typography.Text>
            ) : null}
            {event.version ? <Typography.Text type="success">V{event.version}</Typography.Text> : null}
          </Space>
          <Typography.Text type="secondary">{event.message}</Typography.Text>
        </Space>
      }
    />
  );
}
