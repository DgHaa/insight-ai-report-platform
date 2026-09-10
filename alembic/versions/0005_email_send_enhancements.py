"""邮件发送能力增强：状态/版本/尝试次数/逐收件人结果/终止。

Revision ID: 0005_email_send_enhancements
Revises: 0004_add_report_styles
Create Date: 2026-08-18

说明：
- email_tasks.version          ：发送的报告版本号（原为空壳参数，未落库）；
- email_tasks.status           ：扩充为 pending/sending/sent/failed/cancelled；
- email_tasks.attempts         ：发送尝试次数（供失败重试追踪）；
- email_tasks.deliveries       ：逐收件人发送结果（JSONB），支撑进度展示与终止；
- email_tasks.cancel_requested_at：用户发起终止请求的时间。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0005_email_send_enhancements"
down_revision = "0004_add_report_styles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_tasks",
        sa.Column("version", sa.Integer(), nullable=True, comment="发送的报告版本号（空=当前版本）"),
    )
    op.add_column(
        "email_tasks",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="发送尝试次数",
        ),
    )
    op.add_column(
        "email_tasks",
        sa.Column(
            "deliveries",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="逐收件人发送结果（JSONB）",
        ),
    )
    op.add_column(
        "email_tasks",
        sa.Column(
            "cancel_requested_at",
            sa.TIMESTAMP(timezone=False),
            nullable=True,
            comment="终止请求时间",
        ),
    )
    # 历史数据回填：既有已发送任务的状态保持 sent/failed，其余置为 pending 兜底
    op.execute(
        sa.text(
            "UPDATE email_tasks SET deliveries = "
            "(SELECT COALESCE(jsonb_agg(jsonb_build_object("
            "'recipient', r, 'status', CASE WHEN email_tasks.status = 'sent' THEN 'sent' ELSE 'failed' END, "
            "'error_msg', NULL, 'sent_at', NULL)), '[]'::jsonb) "
            "FROM unnest(email_tasks.recipients) AS r) "
            "WHERE deliveries = '[]'::jsonb AND recipients IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("email_tasks", "cancel_requested_at")
    op.drop_column("email_tasks", "deliveries")
    op.drop_column("email_tasks", "attempts")
    op.drop_column("email_tasks", "version")
