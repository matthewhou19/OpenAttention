"""Acceptance tests for 'For You' ranked article feed (Issue #8).

Tests verify:
AC-1: Articles sorted by composite rank descending
AC-2: Archived and unscored articles excluded
AC-3: Cursor-based pagination
AC-4: ~10% exploration slots for low-weight topics
AC-5: Response includes rank field
AC-6: Default view (no view param) unchanged — no regression
AC-9: Empty state returns empty list with next_cursor=null
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.db.models import Article, Base, Feed, Score

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INTERESTS = {
    "description": "Test interests",
    "topics": [
        {"name": "AI/ML Engineering", "weight": 10, "keywords": ["LLM", "transformer"]},
        {"name": "AI Agents", "weight": 9, "keywords": ["autonomous agents", "tool use"]},
        {"name": "Developer Tools", "weight": 7, "keywords": ["CLI", "IDE", "devtools"]},
        {"name": "Open Source", "weight": 6, "keywords": ["github", "FOSS"]},
        {"name": "Startups", "weight": 5, "keywords": ["funding", "YC"]},
    ],
    "exclude": ["sports"],
}


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
    session = temp_db["session_factory"]()
    yield session
    session.close()


@pytest.fixture()
def client(temp_db):
    """TestClient with patched DB session and interests."""
    with (
        patch("src.db.session.get_session", side_effect=temp_db["session_factory"]),
        patch("src.api.routers.articles.get_session", side_effect=temp_db["session_factory"]),
        patch("src.api.routers.articles.load_interests", return_value=SAMPLE_INTERESTS),
    ):
        from src.api.main import app

        yield TestClient(app, raise_server_exceptions=False)


def _make_feed(session, *, url="https://example.com/feed", title="Test Feed", category="AI"):
    feed = Feed(url=url, title=title, category=category, enabled=True)
    session.add(feed)
    session.flush()
    return feed


def _make_article(
    session, feed, *, url_suffix="1", title="Test Article", published_hours_ago=0, is_read=False, is_archived=False
):
    now = datetime.now(timezone.utc)
    article = Article(
        feed_id=feed.id,
        url=f"https://example.com/{url_suffix}",
        title=title,
        published_at=now - timedelta(hours=published_hours_ago),
        fetched_at=now - timedelta(hours=published_hours_ago),
        is_read=is_read,
        is_archived=is_archived,
    )
    session.add(article)
    session.flush()
    return article


def _make_score(session, article, *, relevance=5.0, significance=3.0, topics=None):
    score = Score(
        article_id=article.id,
        relevance=relevance,
        significance=significance,
        topics=json.dumps(topics or []),
        summary=f"Summary for article {article.id}",
    )
    session.add(score)
    session.flush()
    return score


# ---------------------------------------------------------------------------
# AC-1a: Articles sorted by composite rank descending
# ---------------------------------------------------------------------------


def test_foryou_sorted_by_rank_descending(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    # High relevance + high-weight topic = high rank
    a1 = _make_article(session, feed, url_suffix="high", title="High Rank", published_hours_ago=0)
    _make_score(session, a1, relevance=9.0, significance=8.0, topics=["AI/ML Engineering"])

    # Medium
    a2 = _make_article(session, feed, url_suffix="mid", title="Mid Rank", published_hours_ago=0)
    _make_score(session, a2, relevance=5.0, significance=3.0, topics=["Developer Tools"])

    # Low relevance + no matching topic = low rank
    a3 = _make_article(session, feed, url_suffix="low", title="Low Rank", published_hours_ago=0)
    _make_score(session, a3, relevance=2.0, significance=1.0, topics=["Unknown Topic"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    articles = data["articles"]
    assert len(articles) >= 3

    ranks = [a["rank"] for a in articles]
    assert ranks == sorted(ranks, reverse=True), f"Articles not sorted by rank desc: {ranks}"


# ---------------------------------------------------------------------------
# AC-1b: High-weight topic ranks higher than low-weight
# ---------------------------------------------------------------------------


def test_foryou_high_weight_topic_ranks_higher(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    # Same relevance/significance but different topics
    a_high = _make_article(session, feed, url_suffix="ai", title="AI Article", published_hours_ago=0)
    _make_score(session, a_high, relevance=7.0, significance=5.0, topics=["AI/ML Engineering"])  # weight 10

    a_low = _make_article(session, feed, url_suffix="startup", title="Startup Article", published_hours_ago=0)
    _make_score(session, a_low, relevance=7.0, significance=5.0, topics=["Startups"])  # weight 5

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    data = resp.json()
    articles = data["articles"]

    ai_rank = next(a["rank"] for a in articles if a["title"] == "AI Article")
    startup_rank = next(a["rank"] for a in articles if a["title"] == "Startup Article")
    assert ai_rank > startup_rank, f"AI ({ai_rank}) should rank higher than Startup ({startup_rank})"


# ---------------------------------------------------------------------------
# AC-2a: Archived articles excluded
# ---------------------------------------------------------------------------


def test_foryou_excludes_archived(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a_active = _make_article(session, feed, url_suffix="active", title="Active", is_archived=False)
    _make_score(session, a_active, relevance=8.0, significance=5.0, topics=["AI/ML Engineering"])

    a_archived = _make_article(session, feed, url_suffix="archived", title="Archived", is_archived=True)
    _make_score(session, a_archived, relevance=9.0, significance=9.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    data = resp.json()
    titles = [a["title"] for a in data["articles"]]
    assert "Active" in titles
    assert "Archived" not in titles


# ---------------------------------------------------------------------------
# AC-2b: Unscored articles excluded
# ---------------------------------------------------------------------------


def test_foryou_excludes_unscored(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a_scored = _make_article(session, feed, url_suffix="scored", title="Scored")
    _make_score(session, a_scored, relevance=7.0, significance=5.0, topics=["AI/ML Engineering"])

    _make_article(session, feed, url_suffix="unscored", title="Unscored")  # no score

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    data = resp.json()
    titles = [a["title"] for a in data["articles"]]
    assert "Scored" in titles
    assert "Unscored" not in titles


# ---------------------------------------------------------------------------
# AC-3a: First page returns next_cursor
# ---------------------------------------------------------------------------


def test_foryou_pagination_first_page_has_cursor(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    for i in range(5):
        a = _make_article(session, feed, url_suffix=f"p{i}", title=f"Article {i}", published_hours_ago=i)
        _make_score(session, a, relevance=float(9 - i), significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=2")
    data = resp.json()
    assert len(data["articles"]) == 2
    assert data["next_cursor"] is not None, "Should have next_cursor when more articles exist"


# ---------------------------------------------------------------------------
# AC-3b: Cursor returns next page with lower ranks
# ---------------------------------------------------------------------------


def test_foryou_pagination_cursor_returns_next_page(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    for i in range(5):
        a = _make_article(session, feed, url_suffix=f"c{i}", title=f"Article {i}", published_hours_ago=i)
        _make_score(session, a, relevance=float(9 - i), significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    # Get first page
    resp1 = client.get("/api/articles?view=foryou&limit=2")
    data1 = resp1.json()
    cursor = data1["next_cursor"]

    # Get second page
    resp2 = client.get(f"/api/articles?view=foryou&limit=2&cursor={cursor}")
    data2 = resp2.json()

    assert len(data2["articles"]) == 2
    # Second page ranks should all be <= first page's lowest rank
    first_page_min_rank = min(a["rank"] for a in data1["articles"])
    second_page_max_rank = max(a["rank"] for a in data2["articles"])
    assert second_page_max_rank <= first_page_min_rank + 0.01, (
        f"Page 2 max rank ({second_page_max_rank}) should be <= page 1 min rank ({first_page_min_rank})"
    )


# ---------------------------------------------------------------------------
# AC-3c: Last page has next_cursor=null
# ---------------------------------------------------------------------------


def test_foryou_pagination_last_page_cursor_null(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    for i in range(3):
        a = _make_article(session, feed, url_suffix=f"l{i}", title=f"Article {i}")
        _make_score(session, a, relevance=float(7 - i), significance=3.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    # Get first page of 2
    resp1 = client.get("/api/articles?view=foryou&limit=2")
    data1 = resp1.json()
    cursor = data1["next_cursor"]

    # Get second (last) page
    resp2 = client.get(f"/api/articles?view=foryou&limit=2&cursor={cursor}")
    data2 = resp2.json()
    assert len(data2["articles"]) == 1  # only 1 left
    assert data2["next_cursor"] is None, "Last page should have next_cursor=null"


# ---------------------------------------------------------------------------
# AC-3d: Invalid cursor falls back to page 1
# ---------------------------------------------------------------------------


def test_foryou_invalid_cursor_falls_back(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a = _make_article(session, feed, url_suffix="fb1", title="Fallback Article")
    _make_score(session, a, relevance=7.0, significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=10&cursor=invalidbase64garbage")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["articles"]) >= 1, "Should fall back to first page"


# ---------------------------------------------------------------------------
# AC-4a: ~10% exploration slots
# ---------------------------------------------------------------------------


def test_foryou_exploration_slots(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    # Create 20 high-weight articles
    for i in range(20):
        a = _make_article(session, feed, url_suffix=f"main{i}", title=f"Main {i}", published_hours_ago=i)
        _make_score(session, a, relevance=8.0, significance=5.0, topics=["AI/ML Engineering"])

    # Create 5 articles with topics that won't match any interest (floor weight 1.0)
    for i in range(5):
        a = _make_article(session, feed, url_suffix=f"explore{i}", title=f"Explore {i}", published_hours_ago=i)
        _make_score(session, a, relevance=3.0, significance=2.0, topics=["Cryptocurrency"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    data = resp.json()
    articles = data["articles"]

    # With 25 total articles, expect ~2-3 exploration slots (10% of ~25)
    explore_titles = [a["title"] for a in articles if a["title"].startswith("Explore")]
    assert len(explore_titles) >= 1, "Should have at least 1 exploration article"
    assert len(explore_titles) <= 5, "Should not have more exploration articles than available"


# ---------------------------------------------------------------------------
# AC-4b: No exploration articles available — no crash
# ---------------------------------------------------------------------------


def test_foryou_no_exploration_articles_no_crash(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    # All articles match high-weight topics — no floor-weight articles exist
    for i in range(5):
        a = _make_article(session, feed, url_suffix=f"nomatch{i}", title=f"HighWeight {i}")
        _make_score(session, a, relevance=8.0, significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=50")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["articles"]) == 5


# ---------------------------------------------------------------------------
# AC-5a: Response includes rank field
# ---------------------------------------------------------------------------


def test_foryou_response_includes_rank(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a = _make_article(session, feed, url_suffix="rank1", title="Ranked Article")
    _make_score(session, a, relevance=7.0, significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=10")
    data = resp.json()
    article = data["articles"][0]
    assert "rank" in article, "Article should have 'rank' field"
    assert isinstance(article["rank"], float), f"rank should be float, got {type(article['rank'])}"
    assert article["rank"] > 0, "Rank should be positive for a scored article"


# ---------------------------------------------------------------------------
# AC-5b: rank field is float in response schema
# ---------------------------------------------------------------------------


def test_foryou_rank_is_float(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a = _make_article(session, feed, url_suffix="rf1", title="Float Rank")
    _make_score(session, a, relevance=5.0, significance=3.0, topics=["Developer Tools"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?view=foryou&limit=10")
    data = resp.json()
    rank = data["articles"][0]["rank"]
    assert isinstance(rank, float)
    # Score object still present with R/S values (backend exposes them; frontend hides them)
    assert "score" in data["articles"][0]


# ---------------------------------------------------------------------------
# AC-6a: Default view (no view param) returns legacy behavior
# ---------------------------------------------------------------------------


def test_default_view_returns_legacy_list(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    a = _make_article(session, feed, url_suffix="legacy1", title="Legacy Article")
    _make_score(session, a, relevance=7.0, significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp = client.get("/api/articles?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    # Legacy returns a plain list, not a ForYouPage object
    assert isinstance(data, list), f"Default view should return a list, got {type(data)}"
    assert len(data) >= 1
    assert data[0]["title"] == "Legacy Article"


# ---------------------------------------------------------------------------
# AC-6b: Legacy offset pagination still works
# ---------------------------------------------------------------------------


def test_default_view_offset_pagination(temp_db, client):
    session = temp_db["session_factory"]()
    feed = _make_feed(session)

    for i in range(5):
        a = _make_article(session, feed, url_suffix=f"off{i}", title=f"Offset {i}", published_hours_ago=i)
        _make_score(session, a, relevance=float(9 - i), significance=5.0, topics=["AI/ML Engineering"])

    session.commit()
    session.close()

    resp1 = client.get("/api/articles?limit=2&offset=0&scored_only=true")
    resp2 = client.get("/api/articles?limit=2&offset=2&scored_only=true")
    data1 = resp1.json()
    data2 = resp2.json()

    assert isinstance(data1, list)
    assert isinstance(data2, list)
    assert len(data1) == 2
    assert len(data2) == 2
    # No overlap
    ids1 = {a["id"] for a in data1}
    ids2 = {a["id"] for a in data2}
    assert ids1.isdisjoint(ids2), "Pages should not overlap"


# ---------------------------------------------------------------------------
# AC-9: Empty state returns empty list with next_cursor=null
# ---------------------------------------------------------------------------


def test_foryou_empty_state(temp_db, client):
    # No articles in DB at all
    resp = client.get("/api/articles?view=foryou&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["articles"] == []
    assert data["next_cursor"] is None
