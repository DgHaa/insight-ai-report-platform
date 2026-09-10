import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Descriptions,
  Dropdown,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import {
  CloudDownloadOutlined,
  DeleteOutlined,
  DiffOutlined,
  EditOutlined,
  MailOutlined,
  PlayCircleOutlined,
  RollbackOutlined,
  StopOutlined,
  TableOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { useNavigate, useParams } from 'react-router-dom';
import { reportApi } from '../../api/reports';
import { styleApi } from '../../api/styles';
import type {
  ReportDetail as ReportDetailType,
  ReportStyle,
  VersionContent,
  VersionItem,
} from '../../types';
import MarkdownView from '../../components/MarkdownView';
import ModuleContent, { type ModuleLike } from '../../components/ModuleContent';
import GenerationProgress from '../../components/GenerationProgress';
import DiffView from '../../components/DiffView';
import { confirmAction } from '../../components/ConfirmDialog';
import { formatTime } from '../../utils/format';
import { styleConfigToCssVars } from '../../utils/reportStyle';
import BackButton from '../../components/BackButton';
import { useAuthStore } from '../../store/auth';
import { STATUS_COLOR, STATUS_TEXT } from '../../constants/reportStatus';

export default function ReportDetail() {
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [report, setReport] = useState<ReportDetailType | null>(null);
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [content, setContent] = useState<VersionContent | null>(null);
  const [currentVersion, setCurrentVersion] = useState(1);
  const [generating, setGenerating] = useState(false);
  // 模块级重生成状态：regenIndex 标记正在重生成的模块下标，isModuleRegen 区分全量生成
  const [regenIndex, setRegenIndex] = useState<number | null>(null);
  const [isModuleRegen, setIsModuleRegen] = useState(false);
  // 渐进渲染：生成过程中已完成的模块内容（module_done 事件推送）
  const [streamedModules, setStreamedModules] = useState<
    { module_title: string; content: string }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [styles, setStyles] = useState<ReportStyle[]>([]);
  const [versionStyleId, setVersionStyleId] = useState<string | null>(null);
  const [emailOpen, setEmailOpen] = useState(false);
  const [emailForm, setEmailForm] = useState({
    recipients: '',
    formats: ['pdf'] as string[],
    version: undefined as number | undefined,
  });
  const [emailSending, setEmailSending] = useState(false);
  const [emailScheduled, setEmailScheduled] = useState(false);
  const [emailScheduledAt, setEmailScheduledAt] = useState<dayjs.Dayjs | null>(null);
  const [contacts, setContacts] = useState<{ id: string; username: string; email: string }[]>([]);
  const [contactsKey, setContactsKey] = useState(0);

  // 打开发送弹窗时加载通讯录（本部门/全部，超管）
  useEffect(() => {
    if (!emailOpen) return;
    reportApi
      .emailContacts()
      .then((d) => setContacts(d.contacts))
      .catch(() => undefined);
  }, [emailOpen]);
  const [diffOpen, setDiffOpen] = useState(false);
  const [diffA, setDiffA] = useState<number | undefined>();
  const [diffB, setDiffB] = useState<number | undefined>();
  const [diffTextA, setDiffTextA] = useState('');
  const [diffTextB, setDiffTextB] = useState('');

  const loadVersions = useCallback(async () => {
    const data = await reportApi.versions(id);
    setVersions(data.versions);
    return data.versions;
  }, [id]);

  const loadVersionContent = useCallback(
    async (version: number) => {
      const data = await reportApi.version(id, version);
      setContent(data.content);
      setCurrentVersion(version);
      setVersionStyleId(data.style_id ?? null);
    },
    [id],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const detail = await reportApi.detail(id);
      setReport(detail);
      setGenerating(detail.status === 'generating');
      const vs = await loadVersions();
      if (vs.length > 0) {
        const latest = detail.current_version || vs[0].version_number;
        await loadVersionContent(latest);
      }
    } finally {
      setLoading(false);
    }
  }, [id, loadVersions, loadVersionContent]);

  useEffect(() => {
    load();
  }, [load]);

  // 加载当前用户可用的风格列表（用于解析 report.style_id / version.style_id）
  useEffect(() => {
    styleApi.list().then(setStyles).catch(() => undefined);
  }, []);

  // 轮询兜底：WS 进度不可用时，3 秒轮询一次详情，状态收敛后停止
  useEffect(() => {
    if (!generating) return;
    const timer = setInterval(async () => {
      try {
        const d = await reportApi.detail(id);
        if (d.status !== 'generating') {
          setGenerating(false);
          load();
        }
      } catch {
        /* 忽略瞬时错误 */
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [generating, id, load]);

  /** 当前生效风格：
   * - 当前版本：跟随报告当前风格（report.style_id），改风格立即生效、无需重新生成；
   * - 历史版本：保留生成时的风格快照（version.style_id），缺失时回退报告当前风格。
   */
  const activeStyle = useMemo(() => {
    const isCurrent = report != null && currentVersion === report.current_version;
    let sid: string | null;
    if (isCurrent) {
      sid = report?.style_id ?? versionStyleId;
    } else {
      sid = versionStyleId ?? report?.style_id ?? null;
    }
    return styles.find((s) => s.id === sid) || null;
  }, [styles, report, versionStyleId, currentVersion]);

  /** 详情页风格下拉选项（owner 可用） */
  const styleOptions = useMemo(
    () => [
      { label: '默认（科技蓝）', value: '' },
      ...styles.map((s) => ({
        value: s.id,
        label: (
          <Space size={6}>
            <span
              style={{
                display: 'inline-block',
                width: 12,
                height: 12,
                borderRadius: 2,
                background: s.config.primary_color,
              }}
            />
            {s.name}
            {s.type === 'builtin' ? null : s.is_shared ? <Tag color="green">共享</Tag> : <Tag>自定义</Tag>}
          </Space>
        ),
      })),
    ],
    [styles],
  );

  /** 一键切换报告风格（不重新生成，当前版本立即按新风格渲染） */
  const handleChangeStyle = async (value: string) => {
    try {
      await reportApi.update(id, { style_id: value || null });
      message.success('报告风格已更新');
      load();
    } catch {
      /* 已统一提示 */
    }
  };

  const handleGenerate = async (force = false) => {
    try {
      await reportApi.generate(id, force);
      setGenerating(true);
      setIsModuleRegen(false);
      setRegenIndex(null);
      setStreamedModules([]);
      setReport((r) => (r ? { ...r, status: 'generating' } : r));
      message.success(force ? '已触发生成任务（将生成新版本）' : '已触发生成任务');
    } catch {
      // 触发失败（如已有任务/无权限）：与后端真实状态对齐
      load();
    }
  };

  /** 模块级重生成：补丁式更新当前版本该模块（复用同一 WS 进度通道） */
  const handleRegenerateModule = async (index: number) => {
    if (generating) return;
    try {
      await reportApi.regenerateModule(id, index);
      setIsModuleRegen(true);
      setRegenIndex(index);
      setGenerating(true);
      setStreamedModules([]);
      message.success('已触发该模块重生成');
    } catch {
      // 触发失败（如已有任务/无权限）：与后端真实状态对齐
      load();
    }
  };

  const handleTerminate = async () => {
    try {
      await reportApi.terminate(id);
      message.success('任务已终止');
    } catch {
      // 终止失败（后端已改为幂等，此处兜底）也复位本地状态并重新拉取，避免按钮永久置灰
    } finally {
      setGenerating(false);
      load();
    }
  };

  const handleExport = (format: 'pdf' | 'docx' | 'md') => {
    reportApi
      .export(id, format, currentVersion)
      .then(() => message.success('导出成功'))
      .catch(() => {
        // 错误提示（含解析出的后端文案）已由 http 拦截器与 downloadFile 统一处理，
        // 此处仅兜底捕获，避免未处理的 promise rejection
      });
  };

  const addRecipients = (emails: string[]) => {
    const current = emailForm.recipients
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    emails.forEach((e) => {
      if (e && !current.includes(e)) current.push(e);
    });
    setEmailForm({ ...emailForm, recipients: current.join(', ') });
  };

  const handleSendEmail = async () => {
    const recipients = emailForm.recipients
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (recipients.length === 0) {
      message.warning('请至少填写一个收件人');
      return;
    }
    setEmailSending(true);
    try {
      await reportApi.sendEmail(id, {
        recipients,
        formats: emailForm.formats,
        version: emailForm.version,
        scheduled_at:
          emailScheduled && emailScheduledAt
            ? emailScheduledAt.format('YYYY-MM-DDTHH:mm:ss')
            : undefined,
      });
      message.success(emailScheduled ? '已创建定时发送任务' : '邮件任务已创建');
      setEmailOpen(false);
    } finally {
      setEmailSending(false);
    }
  };

  const handleRollback = (version: number) => {
    confirmAction('版本回滚', `确定回滚至版本 ${version} 吗？`, async () => {
      await reportApi.rollback(id, version);
      message.success(`已回滚至版本 ${version}`);
      load();
    });
  };

  const handleDiff = async () => {
    if (!diffA || !diffB || diffA === diffB) {
      message.warning('请选择两个不同版本');
      return;
    }
    const a = await reportApi.version(id, diffA);
    const b = await reportApi.version(id, diffB);
    setDiffTextA(renderContentText(a.content));
    setDiffTextB(renderContentText(b.content));
    setDiffOpen(true);
  };

  // ---- 权限控制：仅报告所有者可编辑/生成/回滚/删除 ----
  const isOwner = !!report?.owner_id && report.owner_id === user?.id;

  const handleDelete = () => {
    if (!report) return;
    confirmAction('删除报告', `确定删除报告「${report.title}」吗？该报告的全部历史版本将一并删除，此操作不可恢复。`, async () => {
      await reportApi.remove(id);
      message.success('报告已删除');
      navigate('/reports', { replace: true });
    });
  };

  if (loading) return <Spin style={{ display: 'block', margin: '80px auto' }} />;
  if (!report) return null;

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <BackButton fallback="/reports" />
        <Typography.Title level={4} style={{ margin: 0, marginLeft: 12 }}>
          报告详情
        </Typography.Title>
      </div>
      <Row gutter={16}>
      <Col span={17}>
        <Card
          title={
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '8px 12px',
                width: '100%',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  flex: '0 1 auto',
                  minWidth: 0,
                }}
              >
                <Typography.Title
                  level={4}
                  style={{ margin: 0, minWidth: 0 }}
                  ellipsis={{ tooltip: report.title }}
                >
                  {report.title}
                </Typography.Title>
                <Tag style={{ flexShrink: 0 }} color={STATUS_COLOR[report.status]}>
                  {STATUS_TEXT[report.status] ?? report.status}
                </Tag>
              </div>
              <Space wrap style={{ flex: '0 0 auto' }}>
              {isOwner ? (
                <Select
                  size="small"
                  style={{ width: 180 }}
                  value={report.style_id || ''}
                  onChange={handleChangeStyle}
                  options={styleOptions}
                  title="切换报告风格（当前版本立即生效，无需重新生成）"
                />
              ) : null}
              {isOwner ? (
                <Button icon={<EditOutlined />} onClick={() => navigate(`/reports/${id}/edit`)}>
                  编辑
                </Button>
              ) : null}
              {isOwner ? (
                <Dropdown.Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  loading={generating}
                  disabled={generating}
                  onClick={() => handleGenerate(false)}
                  menu={{
                    items: [
                      {
                        key: 'force',
                        label: '生成新版本（保留当前版本）',
                      },
                    ],
                    onClick: ({ key }) => {
                      if (key === 'force') handleGenerate(true);
                    },
                  }}
                >
                  生成
                </Dropdown.Button>
              ) : null}
              {isOwner && generating ? (
                <Button danger icon={<StopOutlined />} onClick={handleTerminate}>
                  终止
                </Button>
              ) : null}
              {isOwner && report.status !== 'generating' ? (
                <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>
                  删除
                </Button>
              ) : null}
              <Dropdown
                menu={{
                  items: [
                    { key: 'pdf', label: 'PDF', onClick: () => handleExport('pdf') },
                    { key: 'docx', label: 'Word (docx)', onClick: () => handleExport('docx') },
                    { key: 'md', label: 'Markdown', onClick: () => handleExport('md') },
                  ],
                }}
              >
                <Button icon={<CloudDownloadOutlined />}>导出</Button>
              </Dropdown>
              <Button icon={<MailOutlined />} onClick={() => setEmailOpen(true)}>
                邮件发送
              </Button>
              <Button icon={<DiffOutlined />} onClick={() => setDiffOpen(true)}>
                版本对比
              </Button>
              </Space>
            </div>
          }
        >
          {!isOwner ? (
            <Alert
              type="info"
              showIcon
              message="只读模式"
              description="您正在以只读模式查看此报告，仅可查看内容、导出文件或发送邮件；编辑配置、触发生成、版本回滚与删除仅报告所有者可用。"
              style={{ marginBottom: 12 }}
            />
          ) : null}

          <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="部门">{report.department_name || '—'}</Descriptions.Item>
            <Descriptions.Item label="创建人">{report.owner_name || '—'}</Descriptions.Item>
            <Descriptions.Item label="当前版本">V{report.current_version}</Descriptions.Item>
            <Descriptions.Item label="生成次数">{report.generate_count}</Descriptions.Item>
            <Descriptions.Item label="最近生成">{formatTime(report.last_generated_at)}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{formatTime(report.updated_at)}</Descriptions.Item>
            <Descriptions.Item label="类型">
              {report.type === 'department' ? '部门报告' : '个人报告'}
            </Descriptions.Item>
            <Descriptions.Item label="公开">{report.is_public ? '是' : '否'}</Descriptions.Item>
          </Descriptions>

          <GenerationProgress
            reportId={id}
            active={generating}
            onComplete={() => {
              setGenerating(false);
              setIsModuleRegen(false);
              setRegenIndex(null);
              load();
            }}
            onModuleDone={(
              moduleTitle,
              moduleContent,
              index,
              dataPoints,
              charts,
            ) => {
              // 模块级重生成：就地补丁当前版本该模块（实时刷新，无需等整份完成）
              if (isModuleRegen && regenIndex != null && index - 1 === regenIndex) {
                setContent((prev) => {
                  if (!prev) return prev;
                  const modules = [...(prev.modules || [])];
                  if (regenIndex < modules.length) {
                    modules[regenIndex] = {
                      ...modules[regenIndex],
                      module_title: moduleTitle,
                      content: moduleContent,
                      data_points: dataPoints as ModuleLike['data_points'],
                      charts: charts as ModuleLike['charts'],
                    };
                  }
                  return { ...prev, modules };
                });
              }
              // 按模块原始序号放置（并行执行时完成顺序不定），未完成的位次留空
              setStreamedModules((prev) => {
                const next = [...prev];
                const at = Math.max(0, index - 1);
                while (next.length < at) next.push({ module_title: '', content: '' });
                next[at] = { module_title: moduleTitle, content: moduleContent };
                return next;
              });
            }}
          />

          {/* 渐进渲染：模块完成即展示，无需等整份报告结束（模块级重生成不展示此卡片） */}
          {generating && !isModuleRegen && streamedModules.some((m) => m.content) ? (
            <Card
              size="small"
              title={`生成中 · 已完成 ${streamedModules.filter((m) => m.content).length} 个模块`}
              style={{ marginTop: 12 }}
            >
              {streamedModules.map(
                (m, i) =>
                  m.content ? (
                    <div key={i} style={{ marginBottom: 12 }}>
                      <Typography.Text strong>{m.module_title}</Typography.Text>
                      <div className="report-content" style={styleConfigToCssVars(activeStyle?.config)}>
                        <MarkdownView content={m.content} />
                      </div>
                    </div>
                  ) : null,
              )}
            </Card>
          ) : null}

          {content ? (
            <Card size="small" title={`V${currentVersion} 报告内容`} style={{ marginTop: 12 }}>
              {/* 部分模块失败：显式展示失败明细，避免用户误以为全部成功 */}
              {content.errors && content.errors.length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 12 }}
                  message={`${content.errors.length} 个模块生成失败，以下内容不包含其结果`}
                  description={
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {content.errors.map((e, i) => (
                        <li key={i}>
                          <b>{e.module_title || '未命名模块'}</b>：{e.error || '未知错误'}
                        </li>
                      ))}
                    </ul>
                  }
                />
              ) : null}
              {content.modules && content.modules.length > 0 ? (
                content.modules.map((m, i) => (
                  <ModuleContent
                    key={i}
                    module={m}
                    index={i}
                    styleCss={styleConfigToCssVars(activeStyle?.config)}
                    canEdit={isOwner}
                    regenerating={regenIndex === i}
                    onRegenerate={handleRegenerateModule}
                  />
                ))
              ) : (
                <Typography.Text type="secondary">暂无内容</Typography.Text>
              )}
            </Card>
          ) : (
            <Card size="small" style={{ marginTop: 12 }}>
              <Typography.Text type="secondary">尚未生成报告内容，点击“生成”开始</Typography.Text>
            </Card>
          )}

          {/* 报告配置：所有者可见完整配置；非所有者仅见脱敏后的只读配置（api_key 已由后端脱敏） */}
          <Collapse
            ghost
            style={{ marginTop: 12 }}
            items={[
              {
                key: 'config',
                label: isOwner ? '报告配置（含模型密钥）' : '报告配置（只读，密钥已脱敏）',
                children: (
                  <pre
                    style={{
                      background: '#f6f8fa',
                      borderRadius: 8,
                      padding: 12,
                      maxHeight: 320,
                      overflow: 'auto',
                      fontSize: 12,
                    }}
                  >
                    {JSON.stringify(report.config, null, 2)}
                  </pre>
                ),
              },
            ]}
          />
        </Card>
      </Col>

      <Col span={7}>
        <Card size="small" title="历史版本">
          <Timeline
            items={versions.map((v) => ({
              color: v.is_current ? 'green' : v.status === 'success' ? 'blue' : 'gray',
              children: (
                <Space direction="vertical" size={2}>
                  <Space wrap>
                    <a onClick={() => loadVersionContent(v.version_number)}>V{v.version_number}</a>
                    {v.is_current ? <Tag color="green">当前</Tag> : null}
                    <Tag>{v.model_used || '—'}</Tag>
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {formatTime(v.generated_at)}
                  </Typography.Text>
                  <Space size={4}>
                    <Button size="small" type="link" onClick={() => loadVersionContent(v.version_number)}>
                      查看
                    </Button>
                    {!v.is_current && isOwner ? (
                      <Button
                        size="small"
                        type="link"
                        danger
                        onClick={() => handleRollback(v.version_number)}
                      >
                        <RollbackOutlined /> 回滚
                      </Button>
                    ) : null}
                  </Space>
                </Space>
              ),
            }))}
          />
        </Card>
      </Col>

      {/* 邮件发送弹窗 */}
      <Modal
        open={emailOpen}
        title="发送报告邮件"
        okText={emailScheduled ? '创建定时任务' : '发送'}
        confirmLoading={emailSending}
        onOk={handleSendEmail}
        onCancel={() => setEmailOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>收件人（逗号分隔，外部邮箱需在白名单内）</Typography.Text>
          <Input
            placeholder="zhangsan@insight.local, partner@partner.com"
            value={emailForm.recipients}
            onChange={(e) => setEmailForm({ ...emailForm, recipients: e.target.value })}
          />
          <Select
            key={contactsKey}
            mode="multiple"
            placeholder="从通讯录选择收件人"
            style={{ width: '100%' }}
            options={contacts.map((c) => ({
              value: c.email,
              label: `${c.username}（${c.email}）`,
            }))}
            onSelect={(email: string) => {
              addRecipients([email]);
              setContactsKey((k) => k + 1);
            }}
          />
          {user?.email ? (
            <Space>
              <Button size="small" icon={<MailOutlined />} onClick={() => addRecipients([user.email!])}>
                添加我（{user.email}）
              </Button>
            </Space>
          ) : null}
          <Select
            mode="multiple"
            placeholder="附件格式"
            style={{ width: '100%' }}
            value={emailForm.formats}
            options={[
              { label: 'PDF', value: 'pdf' },
              { label: 'Word', value: 'docx' },
              { label: 'Markdown', value: 'md' },
            ]}
            onChange={(v) => setEmailForm({ ...emailForm, formats: v })}
          />
          <Select
            placeholder="版本号（默认最新）"
            allowClear
            style={{ width: '100%' }}
            value={emailForm.version}
            onChange={(v) => setEmailForm({ ...emailForm, version: v })}
            options={versions.map((v) => ({
              value: v.version_number,
              label: `V${v.version_number}${v.version_number === report?.current_version ? '（最新）' : ''}`,
            }))}
          />
          <Space style={{ justifyContent: 'space-between', width: '100%' }}>
            <Typography.Text>定时发送</Typography.Text>
            <Switch checked={emailScheduled} onChange={setEmailScheduled} />
          </Space>
          {emailScheduled ? (
            <DatePicker
              showTime
              style={{ width: '100%' }}
              placeholder="选择发送时间"
              value={emailScheduledAt}
              onChange={setEmailScheduledAt}
              disabledDate={(d) => d.isBefore(dayjs(), 'day')}
            />
          ) : null}
          <Space style={{ justifyContent: 'space-between', width: '100%' }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              发送后可到「邮件发送记录」查看逐收件人结果
            </Typography.Text>
            <Button
              size="small"
              type="link"
              icon={<TableOutlined />}
              onClick={() => navigate(`/email-tasks?report_id=${id}`)}
            >
              发送记录
            </Button>
          </Space>
        </Space>
      </Modal>

      {/* 版本对比弹窗 */}
      <Modal
        open={diffOpen}
        title="版本对比"
        width={720}
        footer={null}
        onCancel={() => setDiffOpen(false)}
      >
        <Space style={{ marginBottom: 12 }}>
          <Select
            placeholder="版本 A"
            style={{ width: 120 }}
            value={diffA}
            options={versions.map((v) => ({ label: `V${v.version_number}`, value: v.version_number }))}
            onChange={setDiffA}
          />
          <Select
            placeholder="版本 B"
            style={{ width: 120 }}
            value={diffB}
            options={versions.map((v) => ({ label: `V${v.version_number}`, value: v.version_number }))}
            onChange={setDiffB}
          />
          <Button type="primary" onClick={handleDiff}>
            对比
          </Button>
        </Space>
        {diffTextA || diffTextB ? <DiffView oldText={diffTextA} newText={diffTextB} /> : null}
      </Modal>
      </Row>
    </>
  );
}

/** 将版本内容对象渲染为纯文本（供对比） */
function renderContentText(content: VersionContent): string {
  const parts: string[] = [];
  if (content.summary) parts.push(content.summary);
  (content.modules || []).forEach((m) => {
    if (m.content) parts.push(`## ${m.module_title || ''}\n${m.content}`);
  });
  return parts.join('\n\n');
}
