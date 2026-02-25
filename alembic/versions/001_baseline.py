"""Baseline: capture Phase 1 schema (5 tables).

Revision ID: 001
Revises:
Create Date: 2026-02-24
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feeds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("url", sa.String, unique=True, nullable=False),
        sa.Column("title", sa.String, server_default=""),
        sa.Column("site_url", sa.String, server_default=""),
        sa.Column("category", sa.String, server_default=""),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("1")),
        sa.Column("last_fetched_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "articles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("feed_id", sa.Integer, sa.ForeignKey("feeds.id"), nullable=False),
        sa.Column("url", sa.String, unique=True, nullable=False),
        sa.Column("title", sa.String, server_default=""),
        sa.Column("author", sa.String, server_default=""),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("content", sa.Text, server_default=""),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("fetched_at", sa.DateTime),
        sa.Column("is_read", sa.Boolean, server_default=sa.text("0")),
        sa.Column("is_starred", sa.Boolean, server_default=sa.text("0")),
    )

    op.create_table(
        "scores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), unique=True, nullable=False),
        sa.Column("relevance", sa.Float, server_default=sa.text("0.0")),
        sa.Column("significance", sa.Float, server_default=sa.text("0.0")),
        sa.Column("summary", sa.Text, server_default=""),
        sa.Column("topics", sa.Text, server_default="[]"),
        sa.Column("reason", sa.Text, server_default=""),
        sa.Column("scored_at", sa.DateTime),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer, sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String, unique=True, nullable=False),
        sa.Column("value", sa.Text, server_default="{}"),
        sa.Column("updated_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("feedback")
    op.drop_table("scores")
    op.drop_table("articles")
    op.drop_table("feeds")
