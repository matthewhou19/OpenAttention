"""Acceptance tests for Issue #1: Alembic migration setup.

Tests verify:
1. Fresh DB gets all 7 tables from `alembic upgrade head`
2. Existing DB preserves data after stamp + upgrade
3. New tables have correct schema
4. New columns have correct defaults
5. init_db() raises helpful error when migrations not run
6. env.py uses DB_URL from src.config with render_as_batch
"""

import os
import tempfile

from sqlalchemy import create_engine, inspect, text

from src.db.models import Article, Score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_db():
    """Return (path, url) for a fresh temp SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # alembic / create_all will create it
    url = f"sqlite:///{path}"
    return path, url


def _run_alembic_upgrade(url, revision="head"):
    """Run alembic upgrade to a given revision against a custom DB URL."""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, revision)


def _run_alembic_stamp(url, revision):
    """Stamp a revision without running migration SQL."""
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.stamp(cfg, revision)


def _seed_phase1_db(url):
    """Create a Phase-1-style DB (only 5 original tables) with test data."""
    # Use alembic upgrade 001 to create only Phase 1 tables
    _run_alembic_upgrade(url, "001")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO feeds (url, title, category, enabled) "
                "VALUES ('https://example.com/feed', 'Test Feed', 'tech', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO articles (feed_id, url, title, is_read, is_starred) "
                "VALUES (1, 'https://example.com/1', 'Test Article', 0, 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO scores (article_id, relevance, significance, summary, topics, reason) "
                "VALUES (1, 8.5, 7.0, 'A test summary', '[\"AI\"]', 'Good article')"
            )
        )
    engine.dispose()
    return engine


# ---------------------------------------------------------------------------
# AC-1: Fresh DB creates all 7 tables
# ---------------------------------------------------------------------------


def test_fresh_db_creates_all_tables():
    path, url = _make_temp_db()
    try:
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        engine.dispose()

        expected = {
            "feeds",
            "articles",
            "scores",
            "feedback",
            "user_preferences",
            "interest_signals",
            "chat_messages",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-2: Existing DB preserved after stamp + upgrade
# ---------------------------------------------------------------------------


def test_existing_db_data_preserved():
    path, url = _make_temp_db()
    try:
        # Create Phase-1 DB with real data
        _seed_phase1_db(url)

        # Stamp baseline (skip 001), then upgrade to head (apply 002)
        _run_alembic_stamp(url, "001")
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        with engine.connect() as conn:
            feed = conn.execute(text("SELECT title FROM feeds WHERE id = 1")).fetchone()
            assert feed[0] == "Test Feed", "Feed data lost after migration"

            article = conn.execute(text("SELECT title FROM articles WHERE id = 1")).fetchone()
            assert article[0] == "Test Article", "Article data lost after migration"

            score = conn.execute(text("SELECT relevance, summary FROM scores WHERE id = 1")).fetchone()
            assert score[0] == 8.5, "Score data lost after migration"
            assert score[1] == "A test summary", "Score summary lost after migration"
        engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-3: interest_signals table has correct schema
# ---------------------------------------------------------------------------


def test_interest_signals_schema():
    path, url = _make_temp_db()
    try:
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        inspector = inspect(engine)

        columns = {c["name"]: c for c in inspector.get_columns("interest_signals")}
        assert "id" in columns
        assert "topic" in columns
        assert "signal_type" in columns
        assert "count" in columns
        assert "updated_at" in columns

        # Verify composite unique constraint on (topic, signal_type)
        uniques = inspector.get_unique_constraints("interest_signals")
        assert any(set(uc["column_names"]) == {"topic", "signal_type"} for uc in uniques), (
            "Missing composite unique constraint on (topic, signal_type)"
        )

        engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-4: chat_messages table has correct schema
# ---------------------------------------------------------------------------


def test_chat_messages_schema():
    path, url = _make_temp_db()
    try:
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        inspector = inspect(engine)

        columns = {c["name"]: c for c in inspector.get_columns("chat_messages")}
        assert "id" in columns
        assert "role" in columns
        assert "content" in columns
        assert "created_at" in columns

        engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-5: scores.confidence column with default 1.0
# ---------------------------------------------------------------------------


def test_scores_confidence_column():
    path, url = _make_temp_db()
    try:
        # Seed existing DB, stamp baseline, upgrade
        _seed_phase1_db(url)
        _run_alembic_stamp(url, "001")
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT confidence FROM scores WHERE id = 1")).fetchone()
            assert row[0] == 1.0, f"Expected default confidence 1.0, got {row[0]}"
        engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-6: articles.is_archived column with default False
# ---------------------------------------------------------------------------


def test_articles_is_archived_column():
    path, url = _make_temp_db()
    try:
        _seed_phase1_db(url)
        _run_alembic_stamp(url, "001")
        _run_alembic_upgrade(url)

        engine = create_engine(url)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT is_archived FROM articles WHERE id = 1")).fetchone()
            assert row[0] == 0 or row[0] is False, f"Expected default is_archived=False, got {row[0]}"
        engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-7: init_db() raises helpful error when migrations not run
# ---------------------------------------------------------------------------


def test_init_db_raises_on_missing_migrations():
    """init_db() should raise RuntimeError with 'alembic upgrade head' when DB has no alembic_version."""
    from unittest.mock import patch

    path, url = _make_temp_db()
    try:
        # Create empty DB (touch file so SQLite connects, but no tables)
        test_engine = create_engine(url)
        with test_engine.connect():
            pass  # creates the file

        with patch("src.db.session.engine", test_engine):
            try:
                from src.db import session as session_mod

                session_mod.init_db()
                assert False, "init_db() should have raised RuntimeError"
            except RuntimeError as e:
                assert "alembic upgrade head" in str(e), f"Error should mention 'alembic upgrade head', got: {e}"
        test_engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_init_db_succeeds_when_migrations_applied():
    """init_db() should succeed silently when alembic_version table exists."""
    from unittest.mock import patch

    path, url = _make_temp_db()
    try:
        _run_alembic_upgrade(url)
        test_engine = create_engine(url)
        with patch("src.db.session.engine", test_engine):
            from src.db import session as session_mod

            # Should not raise
            session_mod.init_db()
        test_engine.dispose()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# AC-8: Models importable and have new fields
# ---------------------------------------------------------------------------


def test_models_have_new_fields():
    from src.db.models import ChatMessage, InterestSignal

    # InterestSignal exists and has expected columns
    assert hasattr(InterestSignal, "topic")
    assert hasattr(InterestSignal, "signal_type")
    assert hasattr(InterestSignal, "count")

    # ChatMessage exists and has expected columns
    assert hasattr(ChatMessage, "role")
    assert hasattr(ChatMessage, "content")

    # Score has confidence
    assert hasattr(Score, "confidence")

    # Article has is_archived
    assert hasattr(Article, "is_archived")


# ---------------------------------------------------------------------------
# AC-9: env.py uses DB_URL from src.config (not just alembic.ini)
# ---------------------------------------------------------------------------


def test_env_py_imports_db_url():
    """alembic/env.py should import and use DB_URL from src.config."""
    with open("alembic/env.py") as f:
        source = f.read()
    assert "from src.config import" in source and "DB_URL" in source, "env.py should import DB_URL from src.config"
    assert "set_main_option" in source, "env.py should call config.set_main_option to override alembic.ini URL"


# ---------------------------------------------------------------------------
# AC-10: env.py has render_as_batch=True
# ---------------------------------------------------------------------------


def test_env_py_render_as_batch():
    """Both context.configure() calls in env.py should have render_as_batch=True."""
    with open("alembic/env.py") as f:
        source = f.read()
    assert "render_as_batch=True" in source, "env.py should set render_as_batch=True for SQLite safety"
