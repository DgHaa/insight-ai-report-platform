"""补充性能索引

为高频查询路径补索引，解决看板/列表/定时派发的全表扫描：

- generation_tasks：created_at（看板趋势按时间聚合、详情按时间倒序）
                    (report_id, created_at)（单报告任务时间线）
- email_tasks：(status, scheduled_at)（定时派发抢占 WHERE status='pending' AND scheduled_at<=now()）
              created_at（列表按创建时间倒序）

Revision ID: 0006_perf_indexes
Revises: 0005_email_send_enhancements
"""

revision = "0006_perf_indexes"
down_revision = "0005_email_send_enhancements"

from alembic import op  # noqa: E402

NEW_INDEXES = (
    ("idx_tasks_created_at", "generation_tasks", ["created_at"]),
    ("idx_tasks_report_created", "generation_tasks", ["report_id", "created_at"]),
    ("idx_email_status_scheduled", "email_tasks", ["status", "scheduled_at"]),
    ("idx_email_created_at", "email_tasks", ["created_at"]),
)


def upgrade() -> None:
    for name, table, columns in NEW_INDEXES:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table, _columns in NEW_INDEXES:
        op.drop_index(name, table_name=table)
