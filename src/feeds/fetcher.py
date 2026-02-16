import time
from datetime import datetime, timezone

import feedparser
from sqlalchemy.exc import IntegrityError

from src.db.models import Article, Feed
from src.db.session import get_session


def _parse_date(entry) -> datetime | None:
    """Extract published date from a feed entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
    return None


def _get_content(entry) -> str:
    """Extract the best content from a feed entry."""
    # Try content field first (usually full article)
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    # Fall back to summary
    return getattr(entry, "summary", "") or ""


def _get_url(entry) -> str | None:
    """Extract article URL from a feed entry."""
    url = getattr(entry, "link", None)
    if url:
        return url
    # Some feeds use id as the URL
    entry_id = getattr(entry, "id", None)
    if entry_id and entry_id.startswith("http"):
        return entry_id
    return None


def fetch_feed(feed: Feed) -> int:
    """Fetch new articles from a single feed. Returns count of new articles."""
    session = get_session()
    new_count = 0
    try:
        parsed = feedparser.parse(feed.url)

        for entry in parsed.entries:
            url = _get_url(entry)
            if not url:
                continue

            article = Article(
                feed_id=feed.id,
                url=url,
                title=getattr(entry, "title", "") or "",
                author=getattr(entry, "author", "") or "",
                summary=getattr(entry, "summary", "") or "",
                content=_get_content(entry),
                published_at=_parse_date(entry),
            )
            session.add(article)
            try:
                session.flush()
                new_count += 1
            except IntegrityError:
                # Duplicate URL — skip
                session.rollback()

        # Update last_fetched_at
        db_feed = session.query(Feed).filter(Feed.id == feed.id).first()
        if db_feed:
            db_feed.last_fetched_at = datetime.now(timezone.utc)

        session.commit()
        return new_count
    except Exception as e:
        session.rollback()
        raise RuntimeError(f"Error fetching {feed.url}: {e}") from e
    finally:
        session.close()


def fetch_all(feed_id: int | None = None) -> dict[str, int]:
    """Fetch from all enabled feeds (or a specific one). Returns {feed_title: new_count}."""
    session = get_session()
    try:
        query = session.query(Feed).filter(Feed.enabled == True)
        if feed_id is not None:
            query = query.filter(Feed.id == feed_id)
        feeds = query.all()
    finally:
        session.close()

    results = {}
    for feed in feeds:
        label = feed.title or feed.url
        try:
            count = fetch_feed(feed)
            results[label] = count
        except RuntimeError as e:
            results[label] = -1  # Signal error
            print(f"  Error: {e}")
    return results
