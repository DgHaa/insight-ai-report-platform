import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Slider,
  Space,
  Switch,
  Typography,
  message,
} from 'antd';
import { PlusOutlined, DeleteOutlined, ApiOutlined } from '@ant-design/icons';
import type { Credential, Framework, ModuleConfig } from '../../types';
import { modelApi, departmentApi } from '../../api/system';
import { reportApi } from '../../api/reports';
import CronEditor from '../../components/CronEditor';

const PROVIDERS = [
  { label: '昇腾（华为云MaaS/MindIE）', value: 'ascend' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic（Claude）', value: 'anthropic' },
  { label: '自定义（OpenAI兼容）', value: 'custom' },
];

const PROMPT_TEMPLATES = [
  { label: '行业舆情分析', value: '你是一名行业舆情分析专家，请围绕关键词「{keywords}」分析近期热点、风险与趋势，并给出{urls}等来源的要点提炼。' },
  { label: '服务质量报告', value: '你是一名服务质量分析专家，请基于以下数据源内容，输出服务质量分析报告：问题分类、根因、改进建议。' },
  { label: '竞品监测', value: '你是竞品分析专家，请分析以下来源中与「{keywords}」相关的竞品动态，并输出对比表格。' },
];

/** 部门是否已配置公共模型配置（决定是否展示复用开关） */
function useDepartmentModelConfig() {
  const [deptCfg, setDeptCfg] = useState<Awaited<ReturnType<typeof departmentApi.modelConfig>>>(
    null,
  );
  useEffect(() => {
    departmentApi
      .modelConfig()
      .then(setDeptCfg)
      .catch(() => setDeptCfg(null));
  }, []);
  return deptCfg;
}

interface Props {
  open: boolean;
  initial?: ModuleConfig | null;
  credentials: Credential[];
  onOk: (module: ModuleConfig) => void;
  onCancel: () => void;
}

function defaultModule(): ModuleConfig {
  return {
    module_title: '',
    model_config: {
      provider: 'custom',
      endpoint: '',
      api_key: '',
      // 默认指向非推理模型，避免推理模型把大量 token 消耗在思考上（deepseek-chat 为 DeepSeek 的非推理模型）
      model_name: 'deepseek-chat',
      // 非推理模型单模块 4096 已足够（含结构化 JSON 信封）；远超此值只会空耗 token。
      // 后端另有 MODEL_MAX_TOKENS_CAP=8000 硬上限兜底，防止误设超大预算。
      parameters: { temperature: 0.7, max_tokens: 4096 },
    },
    keywords: [],
    prompt: '',
    data_sources: {
      urls: [],
      credential_id: undefined,
      grab_config: { timeout: 10, retries: 2, max_length: 5000 },
    },
    schedule: { type: 'manual', cron: '' },
    output_format: 'text',
    framework: 'general',
  };
}

export default function ModuleFormModal({ open, initial, credentials, onOk, onCancel }: Props) {
  const [form] = Form.useForm<ModuleConfig>();
  const [testing, setTesting] = useState(false);
  const deptCfg = useDepartmentModelConfig();
  const [frameworks, setFrameworks] = useState<Framework[]>([]);

  // 加载分析框架模板目录（供「分析框架」下拉）
  useEffect(() => {
    reportApi
      .frameworks()
      .then((d) => setFrameworks(d.frameworks))
      .catch(() => setFrameworks([]));
  }, []);

  // 按 category 分组，供下拉分组展示（label 直接渲染名称 + 描述）
  const frameworkOptions = useMemo(() => {
    const map = new Map<string, { label: React.ReactNode; value: string }[]>();
    frameworks.forEach((f) => {
      if (!map.has(f.category)) map.set(f.category, []);
      map.get(f.category)!.push({
        label: (
          <div>
            <div>{f.name}</div>
            <div style={{ fontSize: 12, color: '#999' }}>{f.description}</div>
          </div>
        ),
        value: f.id,
      });
    });
    return Array.from(map.entries()).map(([category, options]) => ({
      label: category,
      options,
    }));
  }, [frameworks]);

  // Prompt 实时预览：演示 {keywords} / {urls} / {date} 占位符的实际替换效果
  const watchedPrompt = Form.useWatch('prompt', form);
  const watchedKeywords = Form.useWatch('keywords', form);
  const promptPreview = useMemo(() => {
    const kw = (watchedKeywords || []) as string[];
    const today = new Date().toISOString().slice(0, 10);
    return (watchedPrompt || '')
      .replace(/\{keywords\}/g, kw.length ? kw.join('、') : '（未指定关键词）')
      .replace(/\{urls\}/g, '（生成时替换为实际抓取的来源 URL）')
      .replace(/\{date\}/g, today);
  }, [watchedPrompt, watchedKeywords]);

  useEffect(() => {
    if (open) {
      form.setFieldsValue(initial || defaultModule());
    }
  }, [open, initial, form]);

  const handleTest = async () => {
    const mc = form.getFieldValue('model_config') || {};
    if (!mc.endpoint || !mc.model_name) {
      message.warning('请先填写 API 地址与模型名称');
      return;
    }
    setTesting(true);
    try {
      const res = await modelApi.test({
        provider: mc.provider || 'custom',
        endpoint: mc.endpoint,
        api_key: mc.api_key,
        model_name: mc.model_name,
        temperature: mc.parameters?.temperature,
        max_tokens: mc.parameters?.max_tokens,
      });
      message.success(res.message || `连接成功，延迟 ${res.latency_ms}ms`);
    } catch {
      /* 错误已统一提示 */
    } finally {
      setTesting(false);
    }
  };

  const handleOk = async () => {
    const values = await form.validateFields();
    onOk(values);
  };

  return (
    <Modal
      open={open}
      title="配置模块"
      width={760}
      okText="保存"
      onOk={handleOk}
      onCancel={onCancel}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="module_title"
          label="模块标题"
          rules={[{ required: true, message: '请输入模块标题' }]}
        >
          <Input placeholder="如：质量舆情监测" />
        </Form.Item>

        {/* 模型配置 */}
        <div style={{ fontWeight: 600, marginBottom: 8 }}>模型配置</div>
        {deptCfg?.has_api_key || deptCfg?.endpoint ? (
          <Form.Item
            name={['model_config', 'use_department_default']}
            label="使用部门公共模型配置"
            valuePropName="checked"
            tooltip="勾选后，未单独填写的 API 地址 / 密钥 / 模型名将自动使用部门公共配置，无需在每个模块重复填写密钥"
          >
            <Switch
              checkedChildren="启用"
              unCheckedChildren="关闭"
              onChange={(checked) => {
                if (checked && deptCfg) {
                  // 仅填充未填写的字段作为默认值展示，密钥不回填（保持脱敏安全）
                  const cur = form.getFieldValue('model_config') || {};
                  form.setFieldsValue({
                    model_config: {
                      ...cur,
                      endpoint: cur.endpoint || deptCfg.endpoint || undefined,
                      model_name: cur.model_name || deptCfg.model_name || undefined,
                    },
                  });
                }
              }}
            />
          </Form.Item>
        ) : null}
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name={['model_config', 'provider']} label="模型提供商">
              <Select options={PROVIDERS} />
            </Form.Item>
          </Col>
          <Col span={16}>
            <Form.Item name={['model_config', 'endpoint']} label="API 地址">
              <Input placeholder="https://xxx/v1/chat/completions" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name={['model_config', 'api_key']} label="API 密钥">
              <Input.Password placeholder="sk-..." />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name={['model_config', 'model_name']} label="模型名称">
              <Input placeholder="如 Qwen3.8-27B / GPT-4o" />
            </Form.Item>
          </Col>
          <Col span={14}>
            <Form.Item name={['model_config', 'parameters', 'temperature']} label="Temperature">
              <Slider min={0} max={2} step={0.1} marks={{ 0: '0', 1: '1', 2: '2' }} />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item name={['model_config', 'parameters', 'max_tokens']} label="Max Tokens">
              <InputNumber min={1} max={128000} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={5}>
            <Form.Item
              name={['model_config', 'unit_price_per_1k_tokens']}
              label="单价(千token)"
              tooltip="用户自填，平台不做保障"
            >
              <InputNumber min={0} step={0.0001} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
        <Button icon={<ApiOutlined />} loading={testing} onClick={handleTest}>
          测试连接
        </Button>

        {/* 内容配置 */}
        <div style={{ fontWeight: 600, margin: '16px 0 8px' }}>内容配置</div>
        <Form.Item
          name="framework"
          label="分析框架"
          tooltip="选择分析视角模板，引擎会在提示词后追加对应引导语，约束模型的分析角度与结构（纯 Prompt 工程，零额外成本、杠杆最大）"
        >
          <Select
            placeholder="选择分析框架"
            options={frameworkOptions}
          />
        </Form.Item>
        <Form.Item name="keywords" label="关键词（回车添加）">
          <Select mode="tags" placeholder="输入关键词后回车" open={false} suffixIcon={null} />
        </Form.Item>
        <Space style={{ marginBottom: 8 }}>
          <span>快速插入模板：</span>
          <Select
            style={{ width: 200 }}
            placeholder="选择 Prompt 模板"
            options={PROMPT_TEMPLATES}
            onChange={(v) => {
              const cur = form.getFieldValue('prompt') || '';
              form.setFieldsValue({ prompt: cur ? `${cur}\n${v}` : v });
            }}
          />
        </Space>
        <Form.Item
          name="prompt"
          label="查询 Prompt"
          tooltip="支持 {keywords}（关键词）、{urls}（抓取到的来源 URL）、{date}（当天日期）占位符，生成时自动替换"
        >
          <Input.TextArea rows={4} placeholder="自定义提示词，支持 {keywords}、{urls}、{date} 占位符" />
        </Form.Item>
        {promptPreview ? (
          <div
            style={{
              background: '#f6f8fa',
              border: '1px solid #e6e8ec',
              borderRadius: 8,
              padding: '8px 12px',
              marginBottom: 12,
            }}
          >
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Prompt 预览（生成时 {`{urls}`} 将替换为实际抓取内容）：
            </Typography.Text>
            <div style={{ fontSize: 12, whiteSpace: 'pre-wrap', marginTop: 4 }}>{promptPreview}</div>
          </div>
        ) : null}
        <Form.Item
          name="output_format"
          label="输出格式"
          tooltip="structured（结构化）会在叙述之外，额外提取关键数据点 + 图表规格，前端以卡片/图表呈现，显著提升洞察可读性"
        >
          <Select
            options={[
              { label: 'Markdown 文本', value: 'text' },
              { label: 'JSON 结构化', value: 'json' },
              { label: '结构化（数据点 + 图表）', value: 'structured' },
            ]}
          />
        </Form.Item>

        {/* 数据源配置 */}
        <div style={{ fontWeight: 600, margin: '16px 0 8px' }}>数据源</div>
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          可选：不填数据源时，模型将仅基于 Prompt 与关键词生成内容（无外部资料依据）。
        </Typography.Text>
        <Form.List name={['data_sources', 'urls']}>
          {(fields, { add, remove }) => (
            <>
              {fields.map((field, idx) => (
                <Space key={field.key} style={{ display: 'flex', marginBottom: 8 }} align="baseline">
                  <Form.Item
                    name={field.name}
                    rules={[{ required: true, message: '请输入URL' }]}
                    style={{ marginBottom: 0, flex: 1 }}
                  >
                    <Input placeholder={`外部链接 ${idx + 1}`} />
                  </Form.Item>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => remove(field.name)}
                    disabled={fields.length <= 0}
                  />
                </Space>
              ))}
              <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add('')}>
                添加 URL
              </Button>
            </>
          )}
        </Form.List>
        <Row gutter={12} style={{ marginTop: 12 }}>
          <Col span={12}>
            <Form.Item name={['data_sources', 'credential_id']} label="引用数据源凭证">
              <Select
                allowClear
                placeholder="从我的凭证库选择"
                options={credentials.map((c) => ({ label: c.name, value: c.id }))}
              />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name={['data_sources', 'grab_config', 'timeout']} label="超时(s)">
              <InputNumber min={1} max={120} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name={['data_sources', 'grab_config', 'retries']} label="重试">
              <InputNumber min={0} max={3} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name={['data_sources', 'grab_config', 'max_length']} label="截断长度">
              <Select
                options={[
                  { label: '2000', value: 2000 },
                  { label: '5000', value: 5000 },
                  { label: '10000', value: 10000 },
                ]}
              />
            </Form.Item>
          </Col>
        </Row>

        {/* 调度配置 */}
        <div style={{ fontWeight: 600, margin: '16px 0 8px' }}>调度配置</div>
        <Form.Item name="schedule" label="调度频率">
          <CronEditor />
        </Form.Item>
      </Form>
    </Modal>
  );
}
