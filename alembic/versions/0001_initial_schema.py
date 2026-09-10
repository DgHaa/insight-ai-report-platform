"""初始化数据库表结构：全部 9 张核心表

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-17

设计说明：
- 严格对照设计文档《数据库ER图及表结构设计》2.2 核心表 DDL；
- 在原始设计基础上，为所有表补充 is_active 布尔列（默认 true）作为软删除标记
  （设计文档仅 users 表包含 is_active，本迁移按统一软删除要求补齐其余表）；
- departments.admin_id 与 users.department_id 构成循环外键，采用建表后追加
  外键约束（ALTER TABLE ADD CONSTRAINT）的方式解决；
- gen_random_uuid() 在 PostgreSQL 13 之前由 pgcrypto 扩展提供，
  本迁移开头执行 CREATE EXTENSION IF NOT EXISTS pgcrypto 兼容旧版本；
- 时间戳字段按设计文档使用 TIMESTAMP（不带时区）。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级：创建全部 9 张表及索引。"""
    # gen_random_uuid() 支持（PG13 之前来自 pgcrypto 扩展）
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ============ (1) departments 部门表 ============
    op.create_table(
        "departments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False, comment="部门名称"),
        sa.Column("code", sa.String(length=50), nullable=False, comment="部门编码（唯一）"),
        sa.Column("description", sa.Text(), nullable=True, comment="部门描述"),
        sa.Column("admin_id", postgresql.UUID(as_uuid=True), nullable=True, comment="部门管理员用户ID"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
    )
    op.create_index("ix_departments_code", "departments", ["code"], unique=True)

    # ============ (2) users 用户表 ============
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(length=50), nullable=False, comment="用户名"),
        sa.Column("email", sa.String(length=100), nullable=False, comment="邮箱"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码哈希"),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属部门ID"),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'user'"),
            comment="角色：super_admin/dept_admin/user",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name="fk_users_department_id"
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_department_id", "users", ["department_id"])

    # 循环外键：departments.admin_id -> users.id（两张表均存在后追加）
    op.create_foreign_key(
        "fk_departments_admin_id", "departments", "users", ["admin_id"], ["id"]
    )
    op.create_index("ix_departments_admin_id", "departments", ["admin_id"])

    # ============ (3) reports 报告表 ============
    op.create_table(
        "reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(length=200), nullable=False, comment="报告标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="报告描述"),
        sa.Column(
            "type", sa.String(length=20), nullable=False, comment="报告类型：department/personal"
        ),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属部门ID"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True, comment="创建者用户ID"),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否公开",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'draft'"),
            comment="状态：draft/generating/completed/failed/timeout/terminated",
        ),
        sa.Column(
            "config", postgresql.JSONB(), nullable=False, comment="报告模块配置（JSONB）"
        ),
        sa.Column(
            "current_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="当前版本号",
        ),
        sa.Column(
            "generate_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="生成次数",
        ),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True, comment="标签（TEXT[]）"),
        sa.Column(
            "last_generated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="最近生成时间",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="更新时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name="fk_reports_department_id"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_reports_owner_id"),
    )
    op.create_index("idx_reports_department", "reports", ["department_id"])
    op.create_index("idx_reports_owner", "reports", ["owner_id"])
    op.create_index("idx_reports_status", "reports", ["status"])

    # ============ (4) report_versions 报告历史版本表 ============
    op.create_table(
        "report_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属报告ID"),
        sa.Column("version_number", sa.Integer(), nullable=False, comment="版本号"),
        sa.Column(
            "content", postgresql.JSONB(), nullable=False, comment="报告内容（JSONB）"
        ),
        sa.Column(
            "config_snapshot",
            postgresql.JSONB(),
            nullable=False,
            comment="生成时的配置快照（JSONB）",
        ),
        sa.Column("model_used", sa.String(length=100), nullable=True, comment="使用的模型"),
        sa.Column("status", sa.String(length=20), nullable=True, comment="生成状态"),
        sa.Column("content_hash", sa.String(length=64), nullable=True, comment="内容哈希"),
        sa.Column(
            "generated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="生成时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name="fk_report_versions_report_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_versions_report", "report_versions", ["report_id"])
    op.create_index(
        "idx_versions_report_number",
        "report_versions",
        ["report_id", "version_number"],
        unique=True,
    )

    # ============ (5) generation_tasks 生成任务表 ============
    op.create_table(
        "generation_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属报告ID"),
        sa.Column(
            "trigger_type",
            sa.String(length=20),
            nullable=True,
            comment="触发方式：manual/scheduled",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=True,
            comment="状态：pending/running/success/failed/timeout/terminated",
        ),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="开始时间",
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="完成时间",
        ),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("worker_id", sa.String(length=50), nullable=True, comment="执行 Worker ID"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["reports.id"], name="fk_generation_tasks_report_id"
        ),
    )
    op.create_index("idx_tasks_report", "generation_tasks", ["report_id"])
    op.create_index("idx_tasks_status", "generation_tasks", ["status"])

    # ============ (6) user_data_source_credentials 用户数据源凭证表 ============
    op.create_table(
        "user_data_source_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属用户ID"),
        sa.Column("name", sa.String(length=100), nullable=False, comment="凭证名称"),
        sa.Column("proxy", sa.Text(), nullable=True, comment="代理配置（加密存储）"),
        sa.Column("cookies", sa.Text(), nullable=True, comment="Cookie（加密存储）"),
        sa.Column(
            "custom_headers",
            postgresql.JSONB(),
            nullable=True,
            comment="自定义请求头（JSONB）",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="更新时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_credentials_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index("idx_credentials_user", "user_data_source_credentials", ["user_id"])

    # ============ (7) email_tasks 邮件任务表 ============
    op.create_table(
        "email_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属报告ID"),
        sa.Column(
            "trigger_type",
            sa.String(length=20),
            nullable=True,
            comment="触发方式：auto/manual/scheduled",
        ),
        sa.Column(
            "recipients", postgresql.ARRAY(sa.Text()), nullable=False, comment="收件人列表（TEXT[]）"
        ),
        sa.Column(
            "formats",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            comment="附件格式（TEXT[]）：['pdf','docx','md']",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending'"),
            comment="状态：pending/sent/failed",
        ),
        sa.Column(
            "scheduled_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="计划发送时间",
        ),
        sa.Column(
            "sent_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="实际发送时间",
        ),
        sa.Column("error_msg", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], name="fk_email_tasks_report_id"),
    )
    op.create_index("idx_email_report", "email_tasks", ["report_id"])
    op.create_index("idx_email_status", "email_tasks", ["status"])

    # ============ (8) model_cost_logs 模型成本日志表 ============
    op.create_table(
        "model_cost_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True, comment="所属生成任务ID"),
        sa.Column("model_provider", sa.String(length=50), nullable=True, comment="模型提供商"),
        sa.Column("model_name", sa.String(length=100), nullable=True, comment="模型名称"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True, comment="输入 token 数"),
        sa.Column("completion_tokens", sa.Integer(), nullable=True, comment="输出 token 数"),
        sa.Column("total_tokens", sa.Integer(), nullable=True, comment="总 token 数"),
        sa.Column(
            "unit_price_per_1k_tokens",
            sa.Numeric(10, 6),
            nullable=True,
            comment="每千 token 单价",
        ),
        sa.Column(
            "estimated_cost",
            sa.Numeric(10, 4),
            nullable=True,
            comment="估算成本",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["generation_tasks.id"], name="fk_model_cost_logs_task_id"
        ),
    )
    op.create_index("idx_cost_task", "model_cost_logs", ["task_id"])

    # ============ (9) global_email_whitelist 全局外部邮箱白名单表 ============
    op.create_table(
        "global_email_whitelist",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("domain", sa.String(length=255), nullable=False, comment="白名单域名"),
        sa.Column("description", sa.Text(), nullable=True, comment="备注"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True, comment="创建人用户ID"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="软删除标记",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_whitelist_created_by"
        ),
    )
    # domain 唯一约束即使用该唯一索引（对应设计文档 idx_whitelist_domain）
    op.create_index(
        "idx_whitelist_domain", "global_email_whitelist", ["domain"], unique=True
    )


def downgrade() -> None:
    """回滚：按依赖逆序删除全部表。"""
    # 按依赖逆序删除：先删引用其他表的表，最后删 departments
    op.drop_table("global_email_whitelist")
    op.drop_table("model_cost_logs")
    op.drop_table("email_tasks")
    op.drop_table("user_data_source_credentials")
    op.drop_table("generation_tasks")
    op.drop_table("report_versions")
    op.drop_table("reports")
    op.drop_table("users")
    op.drop_table("departments")
