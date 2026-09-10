"""新增部门公共模型配置表

Revision ID: 0003_add_department_model_configs
Revises: 0002_add_operation_logs_system_configs
Create Date: 2026-08-17

说明：
- department_model_configs：各部门可复用的公共模型配置（provider/endpoint/api_key/model_name），
  供超级管理员按部门统一管理；api_key 在接口返回时必须脱敏，不返回明文。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_add_department_model_configs"
down_revision = "0002_add_operation_logs_system_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "department_model_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="所属部门ID",
        ),
        sa.Column("name", sa.String(length=100), nullable=False, comment="配置名称"),
        sa.Column("provider", sa.String(length=50), nullable=True, comment="模型提供商"),
        sa.Column("endpoint", sa.Text(), nullable=True, comment="API 地址"),
        sa.Column("api_key", sa.Text(), nullable=True, comment="API Key（返回时脱敏）"),
        sa.Column("model_name", sa.String(length=100), nullable=True, comment="模型名称"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="创建人用户ID",
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
            ["department_id"],
            ["departments.id"],
            name="fk_dmc_department_id",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_dmc_created_by",
        ),
    )
    op.create_index(
        "ix_dmc_department_id", "department_model_configs", ["department_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_dmc_department_id", table_name="department_model_configs")
    op.drop_table("department_model_configs")
