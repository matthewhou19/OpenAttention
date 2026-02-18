import feedparser

from src.db.models import Feed
from src.db.session import get_session


def add_feed(url: str, category: str = "") -> Feed:
    """Add a new RSS feed. Fetches title from the feed URL."""
    session = get_session()
    try:
        existing = session.query(Feed).filter(Feed.url == url).first()
        if existing:
            raise ValueError(f"Feed already exists: {existing.title or existing.url} (id={existing.id})")

        # Try to fetch feed metadata
        parsed = feedparser.parse(url)
        title = getattr(parsed.feed, "title", "") or ""
        site_url = getattr(parsed.feed, "link", "") or ""

        feed = Feed(
            url=url,
            title=title,
            site_url=site_url,
            category=category,
        )
        session.add(feed)
        session.commit()
        session.refresh(feed)
        return feed
    finally:
        session.close()


def list_feeds(enabled_only: bool = False) -> list[Feed]:
    """List all feeds."""
    session = get_session()
    try:
        query = session.query(Feed)
        if enabled_only:
            query = query.filter(Feed.enabled.is_(True))
        return query.order_by(Feed.id).all()
    finally:
        session.close()


def remove_feed(feed_id: int) -> bool:
    """Remove a feed by ID. Returns True if found and removed."""
    session = get_session()
    try:
        feed = session.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            return False
        session.delete(feed)
        session.commit()
        return True
    finally:
        session.close()


def toggle_feed(feed_id: int, enabled: bool) -> bool:
    """Enable or disable a feed."""
    session = get_session()
    try:
        feed = session.query(Feed).filter(Feed.id == feed_id).first()
        if not feed:
            return False
        feed.enabled = enabled
        session.commit()
        return True
    finally:
        session.close()
