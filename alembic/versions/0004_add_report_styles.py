"""新增报告风格表 report_styles 并预置 5 套内置风格。
Revision ID: 0004_add_report_styles
Revises: 0003_add_department_model_configs
Create Date: 2026-08-17

说明：
- report_styles：内置/自定义报告风格，config 为 JSONB（CSS 变量键值对）；
- reports.style_id / report_versions.style_id：报告当前风格与版本生成时风格快照；
- 预置 5 套内置风格：科技蓝(默认)/商务灰/清新绿/学术/暗黑（固定 UUID，幂等插入）。
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_add_report_styles"
down_revision = "0003_add_department_model_configs"
branch_labels = None
depends_on = None

# ---- 内置风格（固定 UUID，幂等种子数据） ----
BUILTIN_STYLES: list = [
    (
        "11111111-1111-4111-8111-111111111111",
        "科技蓝",
        {
            "primary_color": "#1677ff",
            "background_color": "#ffffff",
            "font_family": "sans-serif",
            "title_color": "#0f1b33",
            "title_font_size": 24,
            "body_font_size": 15,
            "line_height": 1.8,
            "table_border_color": "#d6e4ff",
            "blockquote_bg": "#f0f5ff",
            "blockquote_border_color": "#1677ff",
            "code_bg": "#f6f8fa",
            "code_color": "#c41d7f",
        },
    ),
    (
        "22222222-2222-4222-8222-222222222222",
        "商务灰",
        {
            "primary_color": "#434c5e",
            "background_color": "#fafbfc",
            "font_family": "sans-serif",
            "title_color": "#2b313b",
            "title_font_size": 24,
            "body_font_size": 15,
            "line_height": 1.75,
            "table_border_color": "#dfe2e8",
            "blockquote_bg": "#f3f4f6",
            "blockquote_border_color": "#6b7280",
            "code_bg": "#f3f4f6",
            "code_color": "#374151",
        },
    ),
    (
        "33333333-3333-4333-8333-333333333333",
        "清新绿",
        {
            "primary_color": "#16a34a",
            "background_color": "#ffffff",
            "font_family": "sans-serif",
            "title_color": "#14532d",
            "title_font_size": 24,
            "body_font_size": 15,
            "line_height": 1.8,
            "table_border_color": "#dcfce7",
            "blockquote_bg": "#f0fdf4",
            "blockquote_border_color": "#16a34a",
            "code_bg": "#f0fdf4",
            "code_color": "#15803d",
        },
    ),
    (
        "44444444-4444-4444-8444-444444444444",
        "学术",
        {
            "primary_color": "#7c3aed",
            "background_color": "#fdfcff",
            "font_family": "serif",
            "title_color": "#3b0764",
            "title_font_size": 26,
            "body_font_size": 16,
            "line_height": 2.0,
            "table_border_color": "#ede9fe",
            "blockquote_bg": "#f5f3ff",
            "blockquote_border_color": "#7c3aed",
            "code_bg": "#f5f3ff",
            "code_color": "#6d28d9",
        },
    ),
    (
        "55555555-5555-4555-8555-555555555555",
        "暗黑",
        {
            "primary_color": "#60a5fa",
            "background_color": "#0f172a",
            "font_family": "sans-serif",
            "title_color": "#e2e8f0",
            "title_font_size": 24,
            "body_font_size": 15,
            "line_height": 1.8,
            "table_border_color": "#1e293b",
            "blockquote_bg": "#1e293b",
            "blockquote_border_color": "#60a5fa",
            "code_bg": "#1e293b",
            "code_color": "#7dd3fc",
        },
    ),
]


def upgrade() -> None:
    op.create_table(
        "report_styles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=100), nullable=False, comment="风格名称"),
        sa.Column(
            "type",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'custom'"),
            comment="风格类型：builtin / custom",
        ),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="样式属性（JSONB）",
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="创建者用户ID（内置风格为空）",
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="共享目标部门ID",
        ),
        sa.Column(
            "is_shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="是否对部门共享",
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
            ["owner_id"], ["users.id"], name="fk_report_styles_owner_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_report_styles_department_id",
            ondelete="SET NULL",
        ),
    )

    # reports / report_versions 增加 style_id
    op.add_column(
        "reports",
        sa.Column("style_id", postgresql.UUID(as_uuid=True), nullable=True, comment="当前报告风格ID"),
    )
    op.create_foreign_key(
        "fk_reports_style_id",
        "reports",
        "report_styles",
        ["style_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "report_versions",
        sa.Column("style_id", postgresql.UUID(as_uuid=True), nullable=True, comment="生成时风格ID"),
    )
    op.create_foreign_key(
        "fk_report_versions_style_id",
        "report_versions",
        "report_styles",
        ["style_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 预置内置风格（幂等）
    for style_id, name, cfg in BUILTIN_STYLES:
        op.execute(
            sa.text(
                "INSERT INTO report_styles (id, name, type, config, is_shared, created_at, updated_at) "
                "VALUES (CAST(:id AS uuid), :name, 'builtin', CAST(:config AS JSONB), false, now(), now()) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                id=style_id, name=name, config=json.dumps(cfg, ensure_ascii=False)
            )
        )


def downgrade() -> None:
    op.drop_constraint("fk_report_versions_style_id", "report_versions", type_="foreignkey")
    op.drop_column("report_versions", "style_id")
    op.drop_constraint("fk_reports_style_id", "reports", type_="foreignkey")
    op.drop_column("reports", "style_id")
    op.drop_table("report_styles")
