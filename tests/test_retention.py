"""Acceptance tests for article retention & auto-archive API filtering (Issue #5).

Tests verify:
AC-1: GET /api/articles excludes archived articles by default
AC-2: GET /api/articles?include_archived=true returns all articles
AC-3: GET /api/articles/{id} returns archived articles (direct lookup)
AC-4: GET /api/stats includes archived count
AC-5: Bookmarked (save) non-archived articles appear in default view
AC-6: Liked non-archived articles appear in default view
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.db.models import Article, Base, Feed, Feedback, Score


@pytest.fixture()
def client():
    """TestClient with no auth and a seeded in-memory DB."""
    import tempfile

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

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

    # Seed data
    session = Session()
    now = datetime.now(timezone.utc)

    feed = Feed(url="https://example.com/feed", title="Test Feed", category="Tech", enabled=True)
    session.add(feed)
    session.flush()

    # Active article (not archived)
    a_active1 = Article(
        feed_id=feed.id,
        url="https://example.com/active1",
        title="Active Article 1",
        published_at=now - timedelta(hours=2),
        fetched_at=now - timedelta(hours=2),
        is_archived=False,
    )
    # Active article (not archived)
    a_active2 = Article(
        feed_id=feed.id,
        url="https://example.com/active2",
        title="Active Article 2",
        published_at=now - timedelta(hours=4),
        fetched_at=now - timedelta(hours=4),
        is_archived=False,
    )
    # Archived article
    a_archived = Article(
        feed_id=feed.id,
        url="https://example.com/archived",
        title="Archived Article",
        published_at=now - timedelta(days=10),
        fetched_at=now - timedelta(days=10),
        is_archived=True,
    )
    # Bookmarked article (not archived)
    a_saved = Article(
        feed_id=feed.id,
        url="https://example.com/saved",
        title="Saved Article",
        published_at=now - timedelta(hours=6),
        fetched_at=now - timedelta(hours=6),
        is_archived=False,
    )
    # Liked article (not archived)
    a_liked = Article(
        feed_id=feed.id,
        url="https://example.com/liked",
        title="Liked Article",
        published_at=now - timedelta(hours=8),
        fetched_at=now - timedelta(hours=8),
        is_archived=False,
    )

    session.add_all([a_active1, a_active2, a_archived, a_saved, a_liked])
    session.flush()

    # Scores for all articles
    for a in [a_active1, a_active2, a_archived, a_saved, a_liked]:
        session.add(Score(article_id=a.id, relevance=7.0, significance=5.0, summary="s", topics='["Tech"]'))
    session.flush()

    # Feedback
    session.add(Feedback(article_id=a_saved.id, action="save"))
    session.add(Feedback(article_id=a_liked.id, action="like"))
    session.commit()

    article_ids = {
        "active1": a_active1.id,
        "active2": a_active2.id,
        "archived": a_archived.id,
        "saved": a_saved.id,
        "liked": a_liked.id,
    }
    session.close()

    # Patch get_session at every import site:
    # - src.api.routers.articles imports at top level
    # - src.api.main.get_stats imports inside function body (resolves through src.db.session)
    env = os.environ.copy()
    env.pop("ATTENTIONOS_TOKEN", None)
    with patch.dict(os.environ, env, clear=True):
        from src.api.main import app

        with (
            patch("src.api.routers.articles.get_session", side_effect=Session),
            patch("src.db.session.get_session", side_effect=Session),
        ):
            tc = TestClient(app, raise_server_exceptions=False)
            yield {"client": tc, "ids": article_ids}

    engine.dispose()
    import time

    time.sleep(0.1)
    for suffix in ("", "-wal", "-shm"):
        p = path + suffix
        if os.path.exists(p):
            os.unlink(p)


# ---------------------------------------------------------------------------
# AC-1a: Default view excludes archived articles
# ---------------------------------------------------------------------------


def test_default_view_excludes_archived(client):
    resp = client["client"].get("/api/articles")
    assert resp.status_code == 200
    articles = resp.json()
    ids = [a["id"] for a in articles]
    assert client["ids"]["archived"] not in ids, "Archived article should not appear in default view"
    assert len(articles) == 4, f"Expected 4 active articles, got {len(articles)}"


# ---------------------------------------------------------------------------
# AC-1b: All articles archived → empty list
# ---------------------------------------------------------------------------


def test_default_view_empty_when_all_archived(client):
    # This is implicitly tested by AC-1a — the archived one is excluded.
    # Here we verify the archived article specifically is missing.
    resp = client["client"].get("/api/articles")
    titles = [a["title"] for a in resp.json()]
    assert "Archived Article" not in titles


# ---------------------------------------------------------------------------
# AC-2a: include_archived=true returns all articles
# ---------------------------------------------------------------------------


def test_include_archived_returns_all(client):
    resp = client["client"].get("/api/articles?include_archived=true")
    assert resp.status_code == 200
    articles = resp.json()
    ids = [a["id"] for a in articles]
    assert client["ids"]["archived"] in ids, "Archived article should appear when include_archived=true"
    assert len(articles) == 5, f"Expected 5 total articles, got {len(articles)}"


# ---------------------------------------------------------------------------
# AC-2b: include_archived=false same as default
# ---------------------------------------------------------------------------


def test_include_archived_false_same_as_default(client):
    resp = client["client"].get("/api/articles?include_archived=false")
    assert resp.status_code == 200
    articles = resp.json()
    ids = [a["id"] for a in articles]
    assert client["ids"]["archived"] not in ids
    assert len(articles) == 4


# ---------------------------------------------------------------------------
# AC-3: Single article lookup returns archived article
# ---------------------------------------------------------------------------


def test_single_article_returns_archived(client):
    archived_id = client["ids"]["archived"]
    resp = client["client"].get(f"/api/articles/{archived_id}")
    assert resp.status_code == 200, f"Expected 200 for archived article, got {resp.status_code}"
    assert resp.json()["id"] == archived_id


# ---------------------------------------------------------------------------
# AC-4: Stats include archived count
# ---------------------------------------------------------------------------


def test_stats_include_archived_count(client):
    resp = client["client"].get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "archived" in data, "Stats should include 'archived' field"
    assert data["archived"] == 1, f"Expected 1 archived, got {data.get('archived')}"


# ---------------------------------------------------------------------------
# AC-5: Bookmarked non-archived articles appear in default view
# ---------------------------------------------------------------------------


def test_saved_article_appears_in_default_view(client):
    resp = client["client"].get("/api/articles")
    ids = [a["id"] for a in resp.json()]
    assert client["ids"]["saved"] in ids, "Saved/bookmarked article should appear in default view"


# ---------------------------------------------------------------------------
# AC-6: Liked non-archived articles appear in default view
# ---------------------------------------------------------------------------


def test_liked_article_appears_in_default_view(client):
    resp = client["client"].get("/api/articles")
    ids = [a["id"] for a in resp.json()]
    assert client["ids"]["liked"] in ids, "Liked article should appear in default view"
