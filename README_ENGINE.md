# 服务部AI洞察平台 — 核心业务引擎

本文档说明平台核心业务引擎：报告生成引擎、数据抓取、模型调用、进度推送、
并发控制、超时终止、Celery 任务与模型成本日志。

## 一、模块架构

```
app/core/concurrency.py       并发控制：Semaphore(5) + Redis FIFO 队列 + Worker ID + TaskControl
app/services/
├── generation_engine.py      ★ 串行模块执行引擎（抓取→构建Prompt→调模型→解析→存储）
├── fetcher.py                ★ 双引擎抓取（Requests + Playwright 智能降级）
├── model_client.py           ★ 多 Provider 适配（ascend/openai/anthropic/custom）
├── cost_logger.py            ★ 模型成本日志（unit_price 用户自填）
├── progress_pusher.py        ★ 进度推送（Callback/QueueSet/Redis）
├── generation.py             GenerationManager 编排（WebSocket 订阅 + 版本规则）
├── email.py                  邮件发送（perform_email_send 供 Celery 复用）
└── ...
app/tasks/                    Celery 任务
├── celery_app.py             Celery 应用（Redis broker/backend + Beat 调度）
├── generate_report.py        generate_report_task / scheduled_generate_task
├── email_tasks.py            send_email_task
└── cleanup.py                cleanup_temp_files
```

## 二、报告生成引擎（generation_engine.py）

### 串行模块执行流程

每个模块严格按 `config.modules` 顺序串行执行：

```
抓取外部数据(10-40%) → 构建Prompt(45%) → 调用模型API(50-90%) → 解析结果 → 存储(95%)
```

### 模块级错误隔离

- 单模块失败时，`ModuleResult.error` 记录错误，`continue` 执行下一模块（不中断整个报告）；
- 全部模块执行完后生成 `GenerationResult`（含 summary、errors 汇总）；
- 版本保存由 `save_report_version` 统一处理（配置变更才 V+1；未变更覆盖；force 强制新版本）。

### 使用示例

```python
from app.services.generation_engine import GenerationEngine
from app.services.progress_pusher import CallbackPusher
from app.core.concurrency import TaskControl

async def run(report, task_id, config):
    pusher = CallbackPusher(lambda ev: print(ev))
    control = TaskControl.with_deadline(seconds=1800)
    async with SessionLocal() as db:
        result = await GenerationEngine().execute(
            report=report, task_id=task_id, config=config,
            pusher=pusher, control=control, db=db, worker_id="worker-1",
        )
        for module in result.module_results:
            print(module.module_title, module.content, module.error)
```

## 三、外部数据抓取（fetcher.py）

| 能力 | 说明 |
|------|------|
| 双引擎 | Requests（静态页，`asyncio.to_thread`）→ 失败/内容为空 → Playwright（JS 渲染） |
| 智能降级 | 自动检测，无需人工干预；`use_playwright` 可强制指定引擎 |
| 代理 | 支持 http/https/socks5（SOCKS5 需 `requests[socks]` / PySocks） |
| Cookie/Header | 模块配置或凭证库引用均可 |
| 超时/重试 | 每 URL 独立配置，指数退避重试 |
| 内容截断 | 按 `max_length`（2000/5000/10000）截断正文 |
| 凭证引用 | `data_sources.credential_id` 从 `user_data_source_credentials` 表加载 |

配置字段（模块 `data_sources.grab_config`）：

```json
{
  "urls": ["https://example.com/news"],
  "credential_id": "uuid",
  "grab_config": {
    "proxy": "http://user:pass@host:8080",
    "cookies": "session_id=abc",
    "custom_headers": {"Referer": "https://google.com"},
    "timeout": 10,
    "retries": 2,
    "max_length": 5000,
    "use_playwright": null
  }
}
```

## 四、模型调用（model_client.py）

| Provider | 适配器 | 请求格式 |
|----------|--------|----------|
| openai | OpenAICompatible | `/chat/completions`，Bearer |
| custom | OpenAICompatible | 同 OpenAI |
| ascend | OpenAICompatible | 华为云 MaaS / MindIE 兼容 OpenAI 格式 |
| anthropic | AnthropicAdapter | Messages API（x-api-key + anthropic-version） |

统一返回 `ModelCallResult`：text / prompt_tokens / completion_tokens / total_tokens / latency_ms。
模型未返回 `usage` 时按 4 字符/token 估算兜底。

## 五、模型成本日志（cost_logger.py）

- 模型调用成功后写入 `model_cost_logs`（provider/model/tokens/unit_price/estimated_cost）；
- `unit_price_per_1k_tokens` 由用户在模块 `model_config` 中自行填写，**平台不做任何确认和保障**；
- `estimated_cost = total_tokens / 1000 × unit_price`（未填单价时为空）。

## 六、并发控制（core/concurrency.py）

| 组件 | 说明 |
|------|------|
| GlobalConcurrencyLimiter | 异步：`asyncio.Semaphore(5)` + Redis FIFO 队列（LPUSH/LPOP 公平排队） |
| GlobalConcurrencyLimiterSync | Celery 同步：Redis FIFO + 运行计数（跨进程限流） |
| get_worker_id | `hostname:pid:uuid6`，写入 `generation_tasks.worker_id` |
| TaskControl | 取消（Event / Redis 标记）+ 30 分钟硬止损 |
| request_remote_cancel | 终止接口写入 Redis 取消标记，Celery worker 轮询感知 |

Redis 不可用时自动降级为进程内信号量（异步）/直接放行（Celery），并记录告警。

## 七、超时与终止

- **30 分钟硬止损**：`TaskControl.check()` 在每步执行前校验 deadline（默认 1800s，
  可经 `/admin/system/config` 调整）；
- **手动终止**：
  1. 终止接口将任务与报告标记为 `terminated`（丢弃本次生成内容，历史版本不变）；
  2. 写入 Redis 取消标记（Celery 跨进程）；
  3. 进程内取消后台任务 → 正在等待的子调用（模型/抓取）抛出 `asyncio.CancelledError`。

## 八、Celery 任务

```bash
# 启动 worker（建议 4 并发）
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4

# 启动 Beat（定时调度：cleanup_temp_files 每小时执行）
celery -A app.tasks.celery_app beat --loglevel=info
```

| 任务 | 说明 |
|------|------|
| generate_report_task(report_id, force) | 异步生成报告（asyncio.run 调用引擎） |
| scheduled_generate_task(report_id) | 定时调度入口（Beat 调用，trigger_type=scheduled） |
| send_email_task(email_task_id) | 执行真实 SMTP 发送（复用 perform_email_send） |
| cleanup_temp_files() | 清理 `TEMP_DIR` 下过期临时文件（默认 1 小时） |

> 动态报告定时调度：每个报告的 `schedule` 配置（daily/weekly/monthly + cron）可调用
> `celery_app.add_periodic_task` 动态注册到 Beat，或由外部调度器触发
> `scheduled_generate_task.delay(report_id)`。

## 九、与既有 API 层的集成

- FastAPI 异步路径：`POST /reports/{id}/generate` → `GenerationManager`（保留 WebSocket 进度、
  版本规则），内部改为委托 `GenerationEngine` 串行执行，并发控制统一走 `get_async_limiter()`；
- Celery 路径：`generate_report_task` 复用同一引擎与 `save_report_version`，进度通过
  `RedisPusher` 发布（快照 + 频道）；
- 终止接口同时兼容两条路径（DB 标记 + Redis 取消标记 + 进程内取消）。

## 十、依赖清单（requirements.txt 新增）

```
redis>=5.0.0            # FIFO 队列 / 跨进程取消 / 进度广播
celery[redis]>=5.3.0    # 异步任务与定时调度
requests[socks]>=2.31.0 # 静态页抓取 + SOCKS5 代理
beautifulsoup4>=4.12.0  # HTML → 文本
playwright>=1.44.0      # JS 渲染抓取（需 playwright install chromium）
```
