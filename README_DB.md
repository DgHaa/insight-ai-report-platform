# 服务部AI洞察平台 — 数据库设计与初始化指南

本文档说明基于《数据库ER图及表结构设计》实现的 **PostgreSQL 数据库层**：
Alembic 迁移、SQLAlchemy ORM 模型、种子数据、异步连接池。

---

## 一、目录结构

```
Insight/
├── alembic.ini                     # Alembic 配置
├── alembic/
│   ├── env.py                      # 异步迁移环境（asyncpg）
│   ├── script.py.mako              # 迁移脚本模板
│   └── versions/
│       └── 0001_initial_schema.py  # 初始迁移：9 张表 DDL + 索引
├── app/
│   ├── core/
│   │   └── config.py               # 应用配置（数据库连接串、连接池参数）
│   ├── db/
│   │   ├── base.py                 # SQLAlchemy DeclarativeBase
│   │   ├── session.py              # 异步引擎 + 会话 + 连接池（最小5/最大20）
│   │   ├── security.py             # bcrypt 密码哈希
│   │   └── seed.py                 # 种子数据（11部门 + 管理员账号）
│   └── models/                     # 9 张表的 ORM 模型（按表拆分）
│       ├── department.py
│       ├── user.py
│       ├── report.py
│       ├── report_version.py
│       ├── generation_task.py
│       ├── user_data_source_credential.py
│       ├── email_task.py
│       ├── model_cost_log.py
│       ├── global_email_whitelist.py
│       └── mixins.py               # TimestampMixin / SoftDeleteMixin
├── requirements.txt
└── .env.example
```

## 二、环境准备

### 1. 依赖安装（Python 3.10+）

```bash
pip install -r requirements.txt
```

### 2. 创建数据库（PostgreSQL 12+，建议 14+）

```bash
psql -U postgres -h localhost -c "CREATE DATABASE insight_ai;"
```

### 3. 配置环境变量

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # Linux/macOS
```

按实际环境修改 `.env` 中的 `DATABASE_URL` 与连接池参数。

---

## 三、执行步骤

### 第 1 步：执行数据库迁移（建 9 张表）

```bash
cd Insight
alembic upgrade head
```

- 若需先预览 SQL：`alembic upgrade head --sql`
- 查看当前版本：`alembic current`
- 回滚全部：`alembic downgrade base`

### 第 2 步：写入种子数据

```bash
python -m app.db.seed
```

种子数据内容：

| 类型 | 账号 | 密码 | 说明 |
|------|------|------|------|
| 超级管理员 | `admin` | `Admin@2026` | 平台最高权限 |
| 部门管理员 | `dept_admin_<code>` | `Dept@2026` | 每部门 1 个占位账号 |

> ⚠️ 占位账号密码为默认值，**正式上线前务必修改**。

11 个部门（code / 名称）：

| # | code | 部门名称 |
|---|------|----------|
| 1 | `care` | Care业务部[终端BG] |
| 2 | `service_quality` | 服务质量与运营官[终端BG] |
| 3 | `iot_service` | IoT产品服务部[终端BG] |
| 4 | `tablet_pc_service` | 平板与PC产品服务部[终端BG] |
| 5 | `global_hrd` | 全球服务部HRD[终端BG] |
| 6 | `mobile_service` | 手机产品服务部[终端BG] |
| 7 | `bg_spare_parts` | 终端BG备件管理部 |
| 8 | `bg_mkt_solution` | 终端BG服务MKT与解决方案销售部 |
| 9 | `bg_finance` | 终端BG服务财经管理部 |
| 10 | `bg_online_service` | 终端BG线上服务部 |
| 11 | `reserved` | （预留扩展） |

种子脚本为**幂等**设计：可重复执行，已存在的数据会按期望值更新。

### 第 3 步：验证

```bash
# 检查表
alembic current
psql -U postgres -d insight_ai -c "\dt"

# 检查种子数据
psql -U postgres -d insight_ai -c "SELECT username, role, is_active FROM users ORDER BY role, username;"
psql -U postgres -d insight_ai -c "SELECT code, name, admin_id FROM departments ORDER BY code;"
```

### 第 4 步：启动应用（连接池预热）

```python
# 应用启动时调用 warm_up_pool() 预热最小连接数；退出时调用 close_engine()。
from app.db.session import warm_up_pool, close_engine
```

---

## 四、表结构清单（9 张表）

| 表 | 说明 | 关键字段/索引 |
|----|------|--------------|
| `departments` | 部门表 | `code` 唯一；`admin_id` FK→users（循环外键） |
| `users` | 用户表 | `username`/`email` 唯一；`role`（super_admin/dept_admin/user）；`is_active` 软删除 |
| `reports` | 报告表 | `config` JSONB；`tags` TEXT[]；索引：department_id/owner_id/status |
| `report_versions` | 报告历史版本表 | `content`、`config_snapshot` JSONB；唯一索引 `(report_id, version_number)`；report_id 级联删除 |
| `generation_tasks` | 生成任务表 | 索引：report_id/status |
| `user_data_source_credentials` | 用户数据源凭证表 | `custom_headers` JSONB；`proxy`/`cookies` 加密存储；user_id 级联删除 |
| `email_tasks` | 邮件任务表 | `recipients`/`formats` TEXT[]；索引：report_id/status |
| `model_cost_logs` | 模型成本日志表 | `unit_price_per_1k_tokens` DECIMAL(10,6)；索引：task_id |
| `global_email_whitelist` | 全局外部邮箱白名单表 | `domain` 唯一索引 |

## 五、设计与实现说明

1. **循环外键**：`departments.admin_id → users.id` 与 `users.department_id → departments.id`
   构成环。迁移中先建两张表，再 `ALTER TABLE` 追加 `fk_departments_admin_id` 外键；
   ORM 侧使用 `use_alter=True` + `post_update=True` 处理。

2. **软删除**：原设计文档仅 `users` 表含 `is_active`；按统一软删除要求，
   所有表均补充 `is_active BOOLEAN NOT NULL DEFAULT true` 列（在迁移 docstring 中已注明）。

3. **JSONB 字段**：`reports.config`、`report_versions.content`、`report_versions.config_snapshot`、
   `user_data_source_credentials.custom_headers` 均映射为 `postgresql.JSONB`。

4. **数组字段**：`reports.tags`、`email_tasks.recipients`、`email_tasks.formats`
   映射为 `postgresql.ARRAY(Text)`（对应 PG `TEXT[]`）。

5. **UUID 主键**：`gen_random_uuid()` 由 pgcrypto 扩展提供（PG13 之前），
   迁移开头执行 `CREATE EXTENSION IF NOT EXISTS pgcrypto`。

6. **连接池**（`app/db/session.py`）：
   - 最小 5：`pool_size = DB_POOL_MIN_SIZE (5)`，启动时 `warm_up_pool()` 预热；
   - 最大 20：`max_overflow = DB_POOL_MAX_SIZE - DB_POOL_MIN_SIZE (15)`，
     总连接数 = 5 + 15 = 20；
   - 附：`pool_pre_ping=True`、`pool_recycle=1800s`、`pool_timeout=30s`。

7. **密码哈希**：bcrypt（`app/db/security.py`），种子脚本与业务共用同一封装。

## 六、后续开发（新增/修改表结构）

```bash
alembic revision --autogenerate -m "add xxx_table"
alembic upgrade head
```
