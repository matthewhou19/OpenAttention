"""Acceptance tests for background daemon (Issue #4).

Tests verify:
AC-1:  `python cli.py daemon` is a valid Click command with --interval option
AC-2:  Each cycle calls fetch_all() and logs results
AC-3:  Each cycle calls Claude scoring subprocess for unscored articles
AC-4:  Each cycle runs article retention cleanup
AC-5:  Top-level try/except prevents single failure from killing daemon
AC-6:  Single-feed failures are logged, cycle continues
AC-7:  Claude scoring timeout is caught; articles left for next cycle
AC-8:  Daemon checks needs_rescore flag and re-scores if set
AC-9:  Each cycle logs a summary with fetched/scored/archived counts
AC-10: Daemon calls init_db() once at startup
"""

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.db.models import Article, Base, Feed, Feedback, Score, UserPreference


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_db():
    """Create a temporary SQLite database with all tables for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    url = f"sqlite:///{path}"

    engine = create_engine(url, connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    yield {"engine": engine, "session_factory": Session, "path": path, "url": url}

    engine.dispose()
    import time
    time.sleep(0.1)
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            os.unlink(p)


@pytest.fixture()
def db_session(temp_db):
    """Return a session from the temp DB."""
    session = temp_db["session_factory"]()
    yield session
    session.close()


@pytest.fixture()
def seeded_db(db_session):
    """Seed DB with feeds, articles, scores, and feedback for cleanup tests."""
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=10)

    # Feed
    feed = Feed(url="https://example.com/feed", title="Test Feed", enabled=True)
    db_session.add(feed)
    db_session.flush()

    # Old article, no score (should be archived)
    a1 = Article(feed_id=feed.id, url="https://example.com/1", title="Old No Score",
                 published_at=old, fetched_at=old)
    # Old article, low rank (should be archived)
    a2 = Article(feed_id=feed.id, url="https://example.com/2", title="Old Low Rank",
                 published_at=old, fetched_at=old)
    # Old article, high rank (should NOT be archived)
    a3 = Article(feed_id=feed.id, url="https://example.com/3", title="Old High Rank",
                 published_at=old, fetched_at=old)
    # Old article, low rank but saved/bookmarked (should NOT be archived)
    a4 = Article(feed_id=feed.id, url="https://example.com/4", title="Old Saved",
                 published_at=old, fetched_at=old)
    # Old article, low rank but liked (should NOT be archived)
    a5 = Article(feed_id=feed.id, url="https://example.com/5", title="Old Liked",
                 published_at=old, fetched_at=old)
    # Recent article, low rank (should NOT be archived — too recent)
    a6 = Article(feed_id=feed.id, url="https://example.com/6", title="Recent Low Rank",
                 published_at=now - timedelta(days=2), fetched_at=now - timedelta(days=2))

    db_session.add_all([a1, a2, a3, a4, a5, a6])
    db_session.flush()

    # Scores: a2 low rank, a3 high rank, a4 low rank, a5 low rank, a6 low rank
    db_session.add(Score(article_id=a2.id, relevance=1.0, significance=0.5))
    db_session.add(Score(article_id=a3.id, relevance=8.0, significance=7.0))
    db_session.add(Score(article_id=a4.id, relevance=1.0, significance=0.5))
    db_session.add(Score(article_id=a5.id, relevance=1.0, significance=0.5))
    db_session.add(Score(article_id=a6.id, relevance=1.0, significance=0.5))

    # Feedback: a4 saved, a5 liked
    db_session.add(Feedback(article_id=a4.id, action="save"))
    db_session.add(Feedback(article_id=a5.id, action="like"))

    db_session.commit()

    return {
        "feed": feed,
        "a1": a1, "a2": a2, "a3": a3, "a4": a4, "a5": a5, "a6": a6,
        "session": db_session,
    }


# ---------------------------------------------------------------------------
# AC-1a: CLI command exists with --interval option
# ---------------------------------------------------------------------------

def test_daemon_command_exists_with_interval_option():
    from cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["daemon", "--help"])
    assert result.exit_code == 0, f"daemon --help failed: {result.output}"
    assert "--interval" in result.output, "Missing --interval option"


# ---------------------------------------------------------------------------
# AC-1b: Custom interval accepted
# ---------------------------------------------------------------------------

def test_daemon_accepts_custom_interval():
    from cli import cli
    runner = CliRunner()
    with patch("src.daemon.run_daemon") as mock_run:
        # daemon will call run_daemon — we mock it to prevent infinite loop
        result = runner.invoke(cli, ["daemon", "--interval", "10"])
    assert result.exit_code == 0, f"daemon --interval 10 failed: {result.output}"
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs[1].get("interval") == 10 or (len(call_kwargs[0]) > 0 and call_kwargs[0][0] == 10)


# ---------------------------------------------------------------------------
# AC-2a: Cycle calls fetch_all and logs results
# ---------------------------------------------------------------------------

def test_cycle_calls_fetch_all(temp_db, caplog):
    from src.daemon import run_cycle

    mock_session_factory = temp_db["session_factory"]
    with patch("src.daemon.fetch_all", return_value={"Test Feed": 5}) as mock_fetch, \
         patch("src.daemon.score_unscored", return_value=0), \
         patch("src.daemon.cleanup_articles"), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=mock_session_factory):
        with caplog.at_level(logging.INFO, logger="src.daemon"):
            run_cycle()
    mock_fetch.assert_called_once()


# ---------------------------------------------------------------------------
# AC-2b: Mixed fetch results logged per feed
# ---------------------------------------------------------------------------

def test_cycle_logs_per_feed_results(temp_db, caplog):
    from src.daemon import run_cycle

    results = {"Good Feed": 3, "Bad Feed": -1}
    with patch("src.daemon.fetch_all", return_value=results), \
         patch("src.daemon.score_unscored", return_value=0), \
         patch("src.daemon.cleanup_articles"), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        with caplog.at_level(logging.INFO, logger="src.daemon"):
            run_cycle()

    log_text = caplog.text
    assert "Good Feed" in log_text
    assert "3" in log_text


# ---------------------------------------------------------------------------
# AC-3a: Unscored articles trigger Claude subprocess
# ---------------------------------------------------------------------------

def test_cycle_calls_scoring_when_unscored_exist(temp_db):
    from src.daemon import run_cycle

    with patch("src.daemon.fetch_all", return_value={}), \
         patch("src.daemon.score_unscored", return_value=5) as mock_score, \
         patch("src.daemon.cleanup_articles"), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        run_cycle()
    mock_score.assert_called_once()


# ---------------------------------------------------------------------------
# AC-3b: Claude returns valid JSON → write_scores called
# ---------------------------------------------------------------------------

def test_score_unscored_calls_write_scores_on_valid_json():
    from src.daemon import score_unscored

    fake_batch = json.dumps({
        "interests": {},
        "articles": [{"id": 1, "title": "Test"}],
        "count": 1,
        "instructions": "...",
    })
    fake_scores = json.dumps([{"article_id": 1, "relevance": 7, "significance": 5,
                               "summary": "s", "topics": ["ai"], "reason": "r"}])
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = fake_scores

    with patch("src.daemon.prepare_scoring_prompt", return_value=fake_batch), \
         patch("subprocess.run", return_value=mock_result), \
         patch("src.daemon.write_scores", return_value=1) as mock_write:
        count = score_unscored()

    assert count == 1
    mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# AC-3c: No unscored articles → scoring not called
# ---------------------------------------------------------------------------

def test_score_unscored_skips_when_no_articles():
    from src.daemon import score_unscored

    no_articles = json.dumps({"status": "no_unscored_articles", "count": 0})
    with patch("src.daemon.prepare_scoring_prompt", return_value=no_articles), \
         patch("subprocess.run") as mock_sub:
        count = score_unscored()

    assert count == 0
    mock_sub.assert_not_called()


# ---------------------------------------------------------------------------
# AC-4a: Old article, no score → archived
# ---------------------------------------------------------------------------

def test_cleanup_archives_old_unscored(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    archived = cleanup_articles(session)
    session.refresh(seeded_db["a1"])
    assert seeded_db["a1"].is_archived is True, "Old unscored article should be archived"
    assert archived >= 1


# ---------------------------------------------------------------------------
# AC-4b: Old article, low rank → archived
# ---------------------------------------------------------------------------

def test_cleanup_archives_old_low_rank(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    cleanup_articles(session)
    session.refresh(seeded_db["a2"])
    assert seeded_db["a2"].is_archived is True, "Old low-rank article should be archived"


# ---------------------------------------------------------------------------
# AC-4c: Old article, high rank → NOT archived
# ---------------------------------------------------------------------------

def test_cleanup_keeps_old_high_rank(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    cleanup_articles(session)
    session.refresh(seeded_db["a3"])
    assert seeded_db["a3"].is_archived is not True, "Old high-rank article should NOT be archived"


# ---------------------------------------------------------------------------
# AC-4d: Old article, saved → NOT archived
# ---------------------------------------------------------------------------

def test_cleanup_keeps_saved_articles(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    cleanup_articles(session)
    session.refresh(seeded_db["a4"])
    assert seeded_db["a4"].is_archived is not True, "Saved/bookmarked article should NOT be archived"


# ---------------------------------------------------------------------------
# AC-4e: Old article, liked → NOT archived
# ---------------------------------------------------------------------------

def test_cleanup_keeps_liked_articles(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    cleanup_articles(session)
    session.refresh(seeded_db["a5"])
    assert seeded_db["a5"].is_archived is not True, "Liked article should NOT be archived"


# ---------------------------------------------------------------------------
# AC-4f: Recent article, low rank → NOT archived
# ---------------------------------------------------------------------------

def test_cleanup_keeps_recent_articles(seeded_db):
    from src.daemon import cleanup_articles

    session = seeded_db["session"]
    cleanup_articles(session)
    session.refresh(seeded_db["a6"])
    assert seeded_db["a6"].is_archived is not True, "Recent article should NOT be archived"


# ---------------------------------------------------------------------------
# AC-5a: fetch_all raises → cycle survives
# ---------------------------------------------------------------------------

def test_cycle_survives_fetch_exception(temp_db, caplog):
    from src.daemon import run_cycle

    with patch("src.daemon.fetch_all", side_effect=RuntimeError("Network down")), \
         patch("src.daemon.score_unscored", return_value=0), \
         patch("src.daemon.cleanup_articles", return_value=0), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        with caplog.at_level(logging.ERROR, logger="src.daemon"):
            # Should NOT raise
            run_cycle()

    assert "Network down" in caplog.text or "error" in caplog.text.lower()


# ---------------------------------------------------------------------------
# AC-5b: write_scores raises → cycle survives
# ---------------------------------------------------------------------------

def test_cycle_survives_scoring_exception(temp_db, caplog):
    from src.daemon import run_cycle

    with patch("src.daemon.fetch_all", return_value={}), \
         patch("src.daemon.score_unscored", side_effect=Exception("JSON parse fail")), \
         patch("src.daemon.cleanup_articles", return_value=0), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        with caplog.at_level(logging.ERROR, logger="src.daemon"):
            run_cycle()

    assert "JSON parse fail" in caplog.text or "error" in caplog.text.lower()


# ---------------------------------------------------------------------------
# AC-6: Single feed error (-1) logged, cycle continues
# ---------------------------------------------------------------------------

def test_cycle_logs_feed_error(temp_db, caplog):
    from src.daemon import run_cycle

    results = {"OK Feed": 2, "Broken Feed": -1}
    with patch("src.daemon.fetch_all", return_value=results), \
         patch("src.daemon.score_unscored", return_value=0), \
         patch("src.daemon.cleanup_articles", return_value=0), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        with caplog.at_level(logging.WARNING, logger="src.daemon"):
            run_cycle()

    assert "Broken Feed" in caplog.text


# ---------------------------------------------------------------------------
# AC-7a: TimeoutExpired → returns 0, error logged
# ---------------------------------------------------------------------------

def test_score_unscored_handles_timeout(caplog):
    from src.daemon import score_unscored

    fake_batch = json.dumps({
        "interests": {},
        "articles": [{"id": 1, "title": "Test"}],
        "count": 1,
        "instructions": "...",
    })
    with patch("src.daemon.prepare_scoring_prompt", return_value=fake_batch), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=180)):
        with caplog.at_level(logging.ERROR, logger="src.daemon"):
            count = score_unscored()

    assert count == 0
    assert "timed out" in caplog.text.lower()


# ---------------------------------------------------------------------------
# AC-7b: FileNotFoundError → returns 0, error logged
# ---------------------------------------------------------------------------

def test_score_unscored_handles_missing_claude(caplog):
    from src.daemon import score_unscored

    fake_batch = json.dumps({
        "interests": {},
        "articles": [{"id": 1, "title": "Test"}],
        "count": 1,
        "instructions": "...",
    })
    with patch("src.daemon.prepare_scoring_prompt", return_value=fake_batch), \
         patch("subprocess.run", side_effect=FileNotFoundError("claude not found")):
        with caplog.at_level(logging.ERROR, logger="src.daemon"):
            count = score_unscored()

    assert count == 0
    assert "claude" in caplog.text.lower() or "not found" in caplog.text.lower()


# ---------------------------------------------------------------------------
# AC-8a: needs_rescore=true → re-scores and clears flag
# ---------------------------------------------------------------------------

def test_check_rescore_when_flag_set(temp_db):
    from src.daemon import check_rescore

    session = temp_db["session_factory"]()
    pref = UserPreference(key="needs_rescore", value='"true"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored", return_value=3) as mock_score:
        check_rescore(session)

    mock_score.assert_called_once()
    session.refresh(pref)
    assert json.loads(pref.value) != "true", "needs_rescore should be cleared after rescore"
    session.close()


# ---------------------------------------------------------------------------
# AC-8b: needs_rescore key missing → no rescore, no error
# ---------------------------------------------------------------------------

def test_check_rescore_when_flag_missing(temp_db):
    from src.daemon import check_rescore

    session = temp_db["session_factory"]()
    # No UserPreference with key="needs_rescore"
    with patch("src.daemon.score_unscored") as mock_score:
        check_rescore(session)  # Should not raise

    mock_score.assert_not_called()
    session.close()


# ---------------------------------------------------------------------------
# AC-9: Cycle logs summary with fetched/scored/archived counts
# ---------------------------------------------------------------------------

def test_cycle_logs_summary(temp_db, caplog):
    from src.daemon import run_cycle

    with patch("src.daemon.fetch_all", return_value={"Feed A": 4}), \
         patch("src.daemon.score_unscored", return_value=3), \
         patch("src.daemon.cleanup_articles", return_value=2), \
         patch("src.daemon.check_rescore"), \
         patch("src.daemon.get_session", side_effect=temp_db["session_factory"]):
        with caplog.at_level(logging.INFO, logger="src.daemon"):
            run_cycle()

    log_text = caplog.text
    assert "4" in log_text, "Should log fetched count"
    assert "3" in log_text, "Should log scored count"
    assert "2" in log_text, "Should log archived count"


# ---------------------------------------------------------------------------
# AC-10: Daemon calls init_db() at startup
# ---------------------------------------------------------------------------

def test_daemon_calls_init_db_at_startup():
    from src.daemon import run_daemon

    with patch("src.daemon.init_db") as mock_init, \
         patch("src.daemon.run_cycle"), \
         patch("time.sleep", side_effect=KeyboardInterrupt):
        try:
            run_daemon(interval=3600)
        except KeyboardInterrupt:
            pass

    mock_init.assert_called_once()
