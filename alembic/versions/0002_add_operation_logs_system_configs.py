"""新增操作日志表与系统配置表

Revision ID: 0002_add_operation_logs_system_configs
Revises: 0001_initial_schema
Create Date: 2026-08-17

说明：
- operation_logs：关键操作审计日志（登录、报告增删改、生成、导出、邮件等）；
- system_configs：系统级 key-value 配置（SMTP、并发上限、任务超时），
  初始化写入默认系统配置，供 /admin/system/config 接口读写。
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_add_operation_logs_system_configs"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============ operation_logs 操作日志表 ============
    op.create_table(
        "operation_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True, comment="操作用户ID"),
        sa.Column("username", sa.String(length=50), nullable=True, comment="操作用户名（冗余）"),
        sa.Column("action", sa.String(length=50), nullable=False, comment="操作动作"),
        sa.Column("resource_type", sa.String(length=50), nullable=True, comment="资源类型"),
        sa.Column("resource_id", sa.String(length=64), nullable=True, comment="资源ID"),
        sa.Column("detail", postgresql.JSONB(), nullable=True, comment="操作详情（JSONB）"),
        sa.Column("ip_address", sa.String(length=45), nullable=True, comment="来源IP"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_operation_logs_user_id"
        ),
    )
    op.create_index("idx_logs_user", "operation_logs", ["user_id"])
    op.create_index("idx_logs_action", "operation_logs", ["action"])
    op.create_index("idx_logs_created_at", "operation_logs", ["created_at"])

    # ============ system_configs 系统配置表 ============
    op.create_table(
        "system_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key", sa.String(length=50), nullable=False, comment="配置键（唯一）"),
        sa.Column("value", postgresql.JSONB(), nullable=False, comment="配置值（JSONB）"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True, comment="最后更新人"),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name="fk_system_configs_updated_by"
        ),
    )
    op.create_index("ix_system_configs_key", "system_configs", ["key"], unique=True)

    # 初始化默认系统配置（使用 bind 参数避免 JSON 中的冒号被解析为绑定参数）
    op.execute(
        text(
            "INSERT INTO system_configs (key, value) VALUES ('system', CAST(:cfg AS jsonb))"
        ).bindparams(
            cfg=json.dumps(
                {
                    "smtp": {
                        "host": "",
                        "port": 587,
                        "username": "",
                        "password": "",
                        "tls": True,
                        "sender": "",
                    },
                    "max_concurrent_tasks": 5,
                    "task_timeout_seconds": 1800,
                },
                ensure_ascii=False,
            )
        )
    )


def downgrade() -> None:
    op.drop_index("ix_system_configs_key", table_name="system_configs")
    op.drop_table("system_configs")
    op.drop_index("idx_logs_created_at", table_name="operation_logs")
    op.drop_index("idx_logs_action", table_name="operation_logs")
    op.drop_index("idx_logs_user", table_name="operation_logs")
    op.drop_table("operation_logs")
