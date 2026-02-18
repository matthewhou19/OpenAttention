import json
import os
import time

from notion_client import Client

from src.db.models import Article, Feed, Score
from src.db.session import get_session


def _get_client() -> Client:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError(
            "NOTION_TOKEN environment variable not set.\nSet up at: https://www.notion.so/my-integrations"
        )
    return Client(auth=token)


def _get_database_id() -> str:
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not db_id:
        raise RuntimeError(
            "NOTION_DATABASE_ID environment variable not set.\n"
            "Open your Notion database as full page and copy the ID from the URL."
        )
    return db_id


def _get_existing_urls(notion: Client, database_id: str) -> set[str]:
    """Fetch all existing article URLs from the Notion database to avoid duplicates."""
    urls = set()
    has_more = True
    next_cursor = None

    while has_more:
        kwargs = {"database_id": database_id, "page_size": 100}
        if next_cursor:
            kwargs["start_cursor"] = next_cursor

        response = notion.databases.query(**kwargs)
        for page in response["results"]:
            url = page["properties"].get("URL", {}).get("url")
            if url:
                urls.add(url)

        has_more = response.get("has_more", False)
        next_cursor = response.get("next_cursor")

    return urls


def _build_page(database_id: str, article: Article, score: Score, feed_title: str) -> dict:
    """Build a Notion page payload from an article + score."""
    topics = json.loads(score.topics) if score.topics else []

    # Truncate summary to 2000 chars (Notion rich_text limit)
    summary = (score.summary or "")[:2000]
    reason = (score.reason or "")[:2000]

    properties = {
        "Title": {"title": [{"text": {"content": (article.title or "Untitled")[:2000]}}]},
        "URL": {"url": article.url},
        "Relevance": {"number": score.relevance},
        "Significance": {"number": score.significance},
        "Summary": {"rich_text": [{"text": {"content": summary}}] if summary else []},
        "Topics": {"multi_select": [{"name": t[:100]} for t in topics[:10]]},
        "Source": {"select": {"name": (feed_title or "Unknown")[:100]}},
        "Reason": {"rich_text": [{"text": {"content": reason}}] if reason else []},
    }

    # Add published date if available
    if article.published_at:
        properties["Published"] = {"date": {"start": article.published_at.strftime("%Y-%m-%d")}}

    return {"parent": {"database_id": database_id}, "properties": properties}


def export_to_notion(min_score: float = 0, limit: int = 50) -> dict:
    """Export scored articles to Notion database.

    Returns dict with counts: {"exported": N, "skipped_duplicate": N, "skipped_no_score": N, "errors": N}
    """
    notion = _get_client()
    database_id = _get_database_id()

    # Get existing URLs to avoid duplicates
    print("Checking existing Notion pages for duplicates...")
    existing_urls = _get_existing_urls(notion, database_id)
    print(f"Found {len(existing_urls)} existing articles in Notion.")

    # Query scored articles from our DB
    session = get_session()
    try:
        query = (
            session.query(Article, Score, Feed)
            .join(Score, Article.id == Score.article_id)
            .join(Feed, Article.feed_id == Feed.id)
        )

        if min_score > 0:
            query = query.filter(Score.relevance >= min_score)

        query = query.order_by(Score.relevance.desc()).limit(limit)
        rows = query.all()
    finally:
        session.close()

    stats = {"exported": 0, "skipped_duplicate": 0, "errors": 0}

    for article, score, feed in rows:
        if article.url in existing_urls:
            stats["skipped_duplicate"] += 1
            continue

        page_data = _build_page(database_id, article, score, feed.title or feed.url)

        try:
            notion.pages.create(**page_data)
            stats["exported"] += 1
            existing_urls.add(article.url)  # Track locally too
            print(f"  Exported: {article.title[:60]}")

            # Respect rate limit (3 req/s)
            time.sleep(0.35)

        except Exception as e:
            stats["errors"] += 1
            print(f"  Error exporting '{article.title[:40]}': {e}")

    return stats
