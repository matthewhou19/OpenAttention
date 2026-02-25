"""Acceptance tests for interest-change re-scoring trigger (Issue #6).

Tests verify:
AC-1: load_interests() returns parsed interests.yaml or default
AC-2: save_interests() sets needs_rescore flag on structural topic changes
AC-3: Weight-only or keyword-only changes do NOT set the rescore flag
AC-4: check_rescore() deletes recent scores and calls score_unscored when flag set
AC-5: check_rescore() only deletes scores for articles within 7 days
AC-6: check_rescore() clears the flag after successful re-score
AC-7: check_rescore() does nothing when flag is not set or missing
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.db.models import Article, Base, Feed, Score, UserPreference

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_db():
    """Temporary SQLite DB with all tables."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)

    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    yield {"engine": engine, "session_factory": Session, "path": path}

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
def temp_interests(tmp_path):
    """Temporary interests.yaml file with a known profile."""
    interests_file = tmp_path / "interests.yaml"
    profile = {
        "description": "Test interests",
        "topics": [
            {"name": "AI/ML", "weight": 10, "keywords": ["LLM", "transformer"]},
            {"name": "DevTools", "weight": 7, "keywords": ["CLI", "IDE"]},
            {"name": "Startups", "weight": 5, "keywords": ["funding", "YC"]},
        ],
        "exclude": ["sports"],
    }
    interests_file.write_text(yaml.dump(profile, allow_unicode=True), encoding="utf-8")
    return {"path": interests_file, "profile": profile}


@pytest.fixture()
def seeded_rescore_db(db_session):
    """DB with a feed and articles at different ages, all scored."""
    now = datetime.now(timezone.utc)

    feed = Feed(url="https://example.com/feed", title="Test Feed", enabled=True)
    db_session.add(feed)
    db_session.flush()

    # Recent article (2 days ago) — should be re-scored
    a_recent = Article(
        feed_id=feed.id, url="https://example.com/recent", title="Recent Article",
        published_at=now - timedelta(days=2), fetched_at=now - timedelta(days=2),
    )
    # Old article (10 days ago) — should NOT be re-scored
    a_old = Article(
        feed_id=feed.id, url="https://example.com/old", title="Old Article",
        published_at=now - timedelta(days=10), fetched_at=now - timedelta(days=10),
    )
    # Borderline article (exactly 7 days ago) — should NOT be re-scored (> 7 days cutoff)
    a_border = Article(
        feed_id=feed.id, url="https://example.com/border", title="Borderline Article",
        published_at=now - timedelta(days=7), fetched_at=now - timedelta(days=7),
    )

    db_session.add_all([a_recent, a_old, a_border])
    db_session.flush()

    # All have scores
    s_recent = Score(article_id=a_recent.id, relevance=3.0, significance=2.0, summary="old score")
    s_old = Score(article_id=a_old.id, relevance=5.0, significance=4.0, summary="old score")
    s_border = Score(article_id=a_border.id, relevance=4.0, significance=3.0, summary="old score")
    db_session.add_all([s_recent, s_old, s_border])
    db_session.commit()

    return {
        "session": db_session,
        "a_recent": a_recent,
        "a_old": a_old,
        "a_border": a_border,
    }


# ---------------------------------------------------------------------------
# AC-1a: load_interests — valid file
# ---------------------------------------------------------------------------

def test_load_interests_returns_parsed_dict(temp_interests):
    from src.interests.manager import load_interests

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]):
        result = load_interests()

    assert isinstance(result, dict)
    assert "topics" in result
    assert len(result["topics"]) == 3
    assert result["topics"][0]["name"] == "AI/ML"


# ---------------------------------------------------------------------------
# AC-1b: load_interests — missing file
# ---------------------------------------------------------------------------

def test_load_interests_returns_default_when_missing(tmp_path):
    from src.interests.manager import load_interests

    missing = tmp_path / "nonexistent.yaml"
    with patch("src.interests.manager.INTERESTS_PATH", missing):
        result = load_interests()

    assert result == {"description": "", "topics": [], "exclude": []}


# ---------------------------------------------------------------------------
# AC-2a: save_interests — topic added → flag set
# ---------------------------------------------------------------------------

def test_save_interests_sets_flag_on_topic_added(temp_interests, temp_db):
    from src.interests.manager import save_interests

    new_profile = temp_interests["profile"].copy()
    new_profile["topics"] = list(new_profile["topics"]) + [
        {"name": "Rust", "weight": 6, "keywords": ["rust", "cargo"]}
    ]

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]), \
         patch("src.interests.manager.get_session", side_effect=temp_db["session_factory"]):
        save_interests(new_profile)

    session = temp_db["session_factory"]()
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    assert pref is not None, "needs_rescore key should exist"
    assert json.loads(pref.value) == "true", "Flag should be 'true' after topic added"
    session.close()


# ---------------------------------------------------------------------------
# AC-2b: save_interests — topic removed → flag set
# ---------------------------------------------------------------------------

def test_save_interests_sets_flag_on_topic_removed(temp_interests, temp_db):
    from src.interests.manager import save_interests

    new_profile = temp_interests["profile"].copy()
    # Remove "Startups"
    new_profile["topics"] = [t for t in new_profile["topics"] if t["name"] != "Startups"]

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]), \
         patch("src.interests.manager.get_session", side_effect=temp_db["session_factory"]):
        save_interests(new_profile)

    session = temp_db["session_factory"]()
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    assert pref is not None
    assert json.loads(pref.value) == "true"
    session.close()


# ---------------------------------------------------------------------------
# AC-2c: save_interests — add + remove simultaneously → flag set
# ---------------------------------------------------------------------------

def test_save_interests_sets_flag_on_add_and_remove(temp_interests, temp_db):
    from src.interests.manager import save_interests

    new_profile = temp_interests["profile"].copy()
    # Remove Startups, add Rust
    new_profile["topics"] = [t for t in new_profile["topics"] if t["name"] != "Startups"]
    new_profile["topics"].append({"name": "Rust", "weight": 6, "keywords": ["rust"]})

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]), \
         patch("src.interests.manager.get_session", side_effect=temp_db["session_factory"]):
        save_interests(new_profile)

    session = temp_db["session_factory"]()
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    assert pref is not None
    assert json.loads(pref.value) == "true"
    session.close()


# ---------------------------------------------------------------------------
# AC-3a: save_interests — weight change only → flag NOT set
# ---------------------------------------------------------------------------

def test_save_interests_no_flag_on_weight_change(temp_interests, temp_db):
    from src.interests.manager import save_interests

    new_profile = temp_interests["profile"].copy()
    new_profile["topics"] = [dict(t) for t in new_profile["topics"]]
    new_profile["topics"][0]["weight"] = 8  # AI/ML 10 → 8

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]), \
         patch("src.interests.manager.get_session", side_effect=temp_db["session_factory"]):
        save_interests(new_profile)

    session = temp_db["session_factory"]()
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    # Flag should not exist or not be "true"
    if pref is not None:
        assert json.loads(pref.value) != "true", "Weight-only change should not trigger rescore"
    session.close()


# ---------------------------------------------------------------------------
# AC-3b: save_interests — keyword change only → flag NOT set
# ---------------------------------------------------------------------------

def test_save_interests_no_flag_on_keyword_change(temp_interests, temp_db):
    from src.interests.manager import save_interests

    new_profile = temp_interests["profile"].copy()
    new_profile["topics"] = [dict(t) for t in new_profile["topics"]]
    new_profile["topics"][0]["keywords"] = ["LLM", "transformer", "GPT"]

    with patch("src.interests.manager.INTERESTS_PATH", temp_interests["path"]), \
         patch("src.interests.manager.get_session", side_effect=temp_db["session_factory"]):
        save_interests(new_profile)

    session = temp_db["session_factory"]()
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    if pref is not None:
        assert json.loads(pref.value) != "true", "Keyword-only change should not trigger rescore"
    session.close()


# ---------------------------------------------------------------------------
# AC-4a: check_rescore — flag set, recent scored articles → scores deleted, score_unscored called
# ---------------------------------------------------------------------------

def test_check_rescore_deletes_recent_scores_and_rescores(seeded_rescore_db, temp_db):
    from src.daemon import check_rescore

    session = seeded_rescore_db["session"]

    # Set the flag
    pref = UserPreference(key="needs_rescore", value='"true"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored", return_value=1) as mock_score:
        check_rescore(session)

    mock_score.assert_called_once()

    # Recent article should have lost its score
    session.refresh(seeded_rescore_db["a_recent"])
    assert seeded_rescore_db["a_recent"].score is None, "Recent article score should be deleted"


# ---------------------------------------------------------------------------
# AC-4b: check_rescore — flag set, no recent articles → score_unscored still called
# ---------------------------------------------------------------------------

def test_check_rescore_no_recent_articles(temp_db):
    from src.daemon import check_rescore

    session = temp_db["session_factory"]()
    pref = UserPreference(key="needs_rescore", value='"true"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored", return_value=0) as mock_score:
        check_rescore(session)

    mock_score.assert_called_once()
    session.close()


# ---------------------------------------------------------------------------
# AC-5a: check_rescore — old article scores untouched
# ---------------------------------------------------------------------------

def test_check_rescore_keeps_old_article_scores(seeded_rescore_db, temp_db):
    from src.daemon import check_rescore

    session = seeded_rescore_db["session"]

    pref = UserPreference(key="needs_rescore", value='"true"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored", return_value=0):
        check_rescore(session)

    # Old article should still have its score
    session.refresh(seeded_rescore_db["a_old"])
    assert seeded_rescore_db["a_old"].score is not None, "Old article score should be preserved"
    assert seeded_rescore_db["a_old"].score.relevance == 5.0

    # Borderline (exactly 7 days) should also be preserved
    session.refresh(seeded_rescore_db["a_border"])
    assert seeded_rescore_db["a_border"].score is not None, "Borderline article score should be preserved"


# ---------------------------------------------------------------------------
# AC-6a: check_rescore — flag cleared after rescore
# ---------------------------------------------------------------------------

def test_check_rescore_clears_flag(seeded_rescore_db, temp_db):
    from src.daemon import check_rescore

    session = seeded_rescore_db["session"]

    pref = UserPreference(key="needs_rescore", value='"true"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored", return_value=1):
        check_rescore(session)

    session.refresh(pref)
    assert json.loads(pref.value) != "true", "Flag should be cleared after rescore"


# ---------------------------------------------------------------------------
# AC-7a: check_rescore — flag is "false" → no action
# ---------------------------------------------------------------------------

def test_check_rescore_noop_when_flag_false(temp_db):
    from src.daemon import check_rescore

    session = temp_db["session_factory"]()
    pref = UserPreference(key="needs_rescore", value='"false"')
    session.add(pref)
    session.commit()

    with patch("src.daemon.score_unscored") as mock_score:
        check_rescore(session)

    mock_score.assert_not_called()
    session.close()


# ---------------------------------------------------------------------------
# AC-7b: check_rescore — flag key missing → no action
# ---------------------------------------------------------------------------

def test_check_rescore_noop_when_flag_missing(temp_db):
    from src.daemon import check_rescore

    session = temp_db["session_factory"]()
    # No UserPreference with key="needs_rescore"

    with patch("src.daemon.score_unscored") as mock_score:
        check_rescore(session)

    mock_score.assert_not_called()
    session.close()
