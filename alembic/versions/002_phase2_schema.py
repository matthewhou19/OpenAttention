"""Phase 2 schema: new tables + columns.

- Add interest_signals table (per-topic engagement counters)
- Add chat_messages table (chat history)
- Add confidence column to scores (default 1.0)
- Add is_archived column to articles (default False)

Revision ID: 002
Revises: 001
Create Date: 2026-02-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interest_signals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("topic", sa.String, nullable=False),
        sa.Column("signal_type", sa.String, nullable=False),
        sa.Column("count", sa.Integer, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("topic", "signal_type"),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime),
    )

    with op.batch_alter_table("scores") as batch_op:
        batch_op.add_column(sa.Column("confidence", sa.Float, server_default=sa.text("1.0")))

    with op.batch_alter_table("articles") as batch_op:
        batch_op.add_column(sa.Column("is_archived", sa.Boolean, server_default=sa.text("0")))


def downgrade() -> None:
    with op.batch_alter_table("articles") as batch_op:
        batch_op.drop_column("is_archived")

    with op.batch_alter_table("scores") as batch_op:
        batch_op.drop_column("confidence")

    op.drop_table("chat_messages")
    op.drop_table("interest_signals")
