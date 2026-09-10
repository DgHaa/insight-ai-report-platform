# 服务部AI洞察平台 — 后端 API 层

本文档说明基于《前后端接口定义文档（V1.0）》实现的 **FastAPI 后端 API 层**，
涵盖认证、报告、生成、版本、导出、邮件、模型、凭证、部门、统计、系统管理等全部模块。

## 一、技术栈

- **Web 框架**：FastAPI（自动生成 OpenAPI 文档）
- **数据校验**：Pydantic v2
- **ORM / 数据库**：SQLAlchemy 2.0 Async + asyncpg（PostgreSQL）
- **认证**：JWT（PyJWT，HS256）
- **并发控制**：`asyncio.Semaphore(5)`（全局并发生成任务数）
- **实时进度**：WebSocket 推送

## 二、目录结构

```
app/
├── main.py                 # 应用入口（路由注册 + 全局异常 + 连接池预热）
├── core/
│   ├── config.py           # 配置（数据库/JWT/SMTP/模拟开关）
│   ├── exceptions.py       # 自定义异常 + 全局异常处理器
│   ├── response.py         # 统一响应 ApiResponse
│   ├── security.py         # JWT 生成/解析/注销
│   └── utils.py            # utcnow 工具
├── api/                    # 路由层
│   ├── deps.py             # 依赖注入：get_current_user / require_role
│   ├── router.py           # 全部路由注册汇总
│   ├── auth.py             # 认证
│   ├── reports.py          # 报告管理
│   ├── generation.py       # 报告生成（含 WebSocket 进度）
│   ├── versions.py         # 历史版本
│   ├── export.py           # 导出
│   ├── email.py            # 邮件
│   ├── models_api.py       # 模型配置
│   ├── credentials.py      # 数据源凭证
│   ├── department.py       # 部门用户管理
│   ├── dashboard.py        # 统计看板
│   └── admin.py            # 系统管理
├── schemas/                # Pydantic 请求/响应模式
├── services/               # 业务逻辑层
│   ├── generation.py       # 生成管理器（Semaphore + 进度广播 + 版本规则）
│   ├── export.py           # 导出（md/docx/pdf）
│   ├── email.py            # 邮件（白名单校验 + SMTP）
│   ├── model_client.py     # 模型 API 客户端
│   ├── stats.py            # 看板统计
│   ├── system_config.py    # 系统配置
│   ├── access.py           # 报告访问权限控制
│   └── serializers.py      # ORM → dict
├── db/
│   ├── session.py          # 异步引擎 + 连接池
│   ├── security.py         # bcrypt 密码哈希
│   └── operation_log.py    # 操作日志写入
└── models/                 # ORM 模型（11 张表）
```

## 三、启动方式

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 执行迁移（建表：9 张核心表 + operation_logs + system_configs）
alembic upgrade head

# 3. 写入种子数据（11 部门 + admin/Admin@2026 + 部门管理员占位账号）
python -m app.db.seed

# 4. 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**API 文档**：
- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc
- 健康检查：http://localhost:8000/health

> 开发模式默认 `GENERATION_SIMULATE=true`、`EMAIL_SIMULATE=true`（不调用真实模型/SMTP）。
> 生产环境请在 `.env` 中关闭并配置真实密钥。

## 四、统一响应格式与错误码

所有接口（WebSocket 除外）返回：

```json
{ "code": 0, "message": "success", "data": { ... } }
```

| code | 说明 | HTTP |
|------|------|------|
| 0 | 成功 | 200 |
| 1001 | 未认证 | 401 |
| 1002 | 无权限 | 403 |
| 1003 | 参数错误 | 400 |
| 1004 | 资源不存在 | 404 |
| 2001 | 任务已存在 | 409 |
| 2002 | 并发限制 | 429 |
| 3001 | 模型调用失败 | 502 |
| 3002 | 数据抓取失败 | 502 |
| 4001 | 邮件发送失败 | 502 |
| 5000 | 服务器内部错误 | 500 |

## 五、接口总览（Base URL：/api/v1）

| 模块 | 方法 | 路径 | 权限 |
|------|------|------|------|
| 认证 | POST | /auth/login | 公开 |
| 认证 | POST | /auth/logout | 登录用户 |
| 报告 | GET | /reports?view=my/department/public/all | 登录用户（all 仅超级管理员） |
| 报告 | POST | /reports | 登录用户（department 类型仅部门管理员） |
| 报告 | GET | /reports/{id} | 属主/同部门/公开/超管 |
| 报告 | PUT | /reports/{id} | 属主/部门管理员/超管 |
| 报告 | DELETE | /reports/{id} | 属主/部门管理员/超管（仅草稿） |
| 生成 | POST | /reports/{id}/generate | 属主/部门管理员/超管 |
| 生成 | WS | /reports/{id}/generate/progress?token=JWT | 登录用户 |
| 生成 | POST | /reports/{id}/generate/terminate | 属主/部门管理员/超管 |
| 版本 | GET | /reports/{id}/versions | 可查看者 |
| 版本 | GET | /reports/{id}/versions/{version} | 可查看者 |
| 版本 | POST | /reports/{id}/versions/{version}/rollback | 属主/部门管理员/超管 |
| 导出 | GET | /reports/{id}/export?format=pdf\|docx\|md&version=N | 可查看者 |
| 邮件 | POST | /reports/{id}/email | 可查看者 |
| 邮件 | GET | /email/tasks | 本人/本部门/超管 |
| 模型 | POST | /models/test | 登录用户 |
| 模型 | GET | /models/providers | 登录用户 |
| 凭证 | GET/POST | /credentials | 本人 |
| 凭证 | PUT/DELETE | /credentials/{id} | 本人 |
| 部门 | GET/POST | /department/users | 部门管理员/超管 |
| 部门 | PUT/DELETE | /department/users/{id} | 部门管理员/超管 |
| 统计 | GET | /dashboard/statistics?time_range=week/month/quarter | 部门管理员/超管 |
| 系统 | GET/POST/DELETE | /admin/email-whitelist[/{id}] | 超级管理员 |
| 系统 | GET | /admin/all-reports | 超级管理员 |
| 系统 | GET/PUT | /admin/system/config | 超级管理员 |

## 六、权限依赖注入

```python
# 认证：所有受保护接口默认携带
user: User = Depends(get_current_user)

# 角色校验
require_role("dept_admin", "super_admin")   # 部门管理员（含超管）
require_role("super_admin")                  # 超级管理员
require_dept_admin / require_super_admin     # 预置组合
```

报告级权限通过 `ensure_can_view` / `ensure_can_manage` 在业务层校验。

## 七、WebSocket 进度订阅示例

```bash
# 1. 登录获取 token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@2026"}'

# 2. 触发生成
curl -X POST http://localhost:8000/api/v1/reports/{report_id}/generate \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"force": false}'

# 3. 订阅进度（browser / wscat）
# ws://localhost:8000/api/v1/reports/{report_id}/generate/progress?token=<token>
```

推送事件示例：

```json
{"phase": "init",        "progress": 5,   "message": "正在解析报告配置..."}
{"phase": "fetching",    "progress": 25,  "message": "正在抓取 https://example.com/news (1/3)..."}
{"phase": "generating",  "progress": 60,  "message": "正在调用 Qwen3.8-27B 生成..."}
{"phase": "storing",     "progress": 95,  "message": "正在生成历史版本并保存..."}
{"phase": "complete",    "progress": 100, "message": "生成成功！", "version": 3}
```

## 八、关键实现说明

1. **并发控制**：`GenerationManager` 持有全局 `asyncio.Semaphore(5)`，超出上限的任务自动 FIFO 排队；同一报告同时只允许一个生成任务（重复触发返回 2001）。
2. **版本规则**：配置与最近成功版本 `config_snapshot` 一致时**覆盖**当前版本（不累加版本号）；不一致或 `force=true` 时版本号 **V+1**。
3. **超时与终止**：默认 30 分钟硬止损（可在系统配置调整）；手动终止后完全丢弃本次生成内容，历史版本不变。
4. **操作日志**：关键操作（登录/登出、报告增删改、生成、终止、回滚、导出、邮件、凭证、部门用户、白名单、系统配置）写入 `operation_logs` 表。
5. **邮件白名单**：收件人为内部域名（`INTERNAL_EMAIL_DOMAINS`）直接放行；外部域名必须命中 `global_email_whitelist`，否则返回 4001 拦截。
6. **导出**：md 直接生成文本；docx 使用 python-docx；pdf 使用 reportlab。
7. **系统配置**：`/admin/system/config` 读写 `system_configs` 表（SMTP、max_concurrent_tasks、task_timeout_seconds），SMTP 密码不回显明文。
8. **登出**：JWT 为无状态方案，登出时将令牌 jti 加入内存黑名单（生产环境可替换为 Redis）。

