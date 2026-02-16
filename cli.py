import json

import click

from src.db.session import init_db


@click.group()
def cli():
    """AI-driven RSS content system."""
    init_db()


# --- Feed management ---

@cli.group()
def feeds():
    """Manage RSS feeds."""
    pass


@feeds.command("add")
@click.argument("url")
@click.option("--category", "-c", default="", help="Feed category")
def feeds_add(url, category):
    """Add a new RSS feed."""
    from src.feeds.manager import add_feed
    try:
        feed = add_feed(url, category)
        click.echo(f"Added feed #{feed.id}: {feed.title or feed.url}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@feeds.command("list")
@click.option("--enabled-only", is_flag=True, help="Show only enabled feeds")
def feeds_list(enabled_only):
    """List all feeds."""
    from src.feeds.manager import list_feeds
    feed_list = list_feeds(enabled_only)
    if not feed_list:
        click.echo("No feeds found. Add one with: python cli.py feeds add <url>")
        return
    for f in feed_list:
        status = "ON" if f.enabled else "OFF"
        fetched = f.last_fetched_at.strftime("%Y-%m-%d %H:%M") if f.last_fetched_at else "never"
        click.echo(f"  #{f.id} [{status}] {f.title or f.url}")
        click.echo(f"       URL: {f.url}")
        click.echo(f"       Category: {f.category or '-'}  Last fetched: {fetched}")


@feeds.command("remove")
@click.argument("feed_id", type=int)
def feeds_remove(feed_id):
    """Remove a feed by ID."""
    from src.feeds.manager import remove_feed
    if remove_feed(feed_id):
        click.echo(f"Removed feed #{feed_id}")
    else:
        click.echo(f"Feed #{feed_id} not found", err=True)
        raise SystemExit(1)


# --- Fetch ---

@cli.command()
@click.option("--feed-id", type=int, default=None, help="Fetch from specific feed only")
def fetch(feed_id):
    """Fetch new articles from feeds."""
    from src.feeds.fetcher import fetch_all
    click.echo("Fetching articles...")
    results = fetch_all(feed_id)
    total = 0
    for label, count in results.items():
        if count < 0:
            click.echo(f"  {label}: ERROR")
        else:
            click.echo(f"  {label}: {count} new articles")
            total += count
    click.echo(f"Total: {total} new articles")


# --- Scoring ---

@cli.group()
def score():
    """Scoring commands."""
    pass


@score.command("prepare")
@click.option("--limit", "-l", type=int, default=20, help="Max articles to prepare")
def score_prepare(limit):
    """Output unscored articles as JSON for Claude Code evaluation."""
    import sys
    from src.scoring.preparer import prepare_scoring_prompt
    output = prepare_scoring_prompt(limit)
    sys.stdout.buffer.write(output.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


@score.command("write")
@click.argument("scores_json")
def score_write(scores_json):
    """Write scores back to the database. Accepts JSON array string."""
    from src.scoring.preparer import write_scores
    try:
        count = write_scores(scores_json)
        click.echo(f"Wrote {count} scores")
    except (json.JSONDecodeError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@score.command("write-file")
@click.argument("filepath", type=click.Path(exists=True))
def score_write_file(filepath):
    """Write scores from a JSON file."""
    from src.scoring.preparer import write_scores
    with open(filepath, "r", encoding="utf-8") as f:
        data = f.read()
    try:
        count = write_scores(data)
        click.echo(f"Wrote {count} scores")
    except (json.JSONDecodeError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


# --- Export ---

@cli.group()
def export():
    """Export scored articles to external services."""
    pass


@export.command("notion")
@click.option("--min-score", type=float, default=0, help="Minimum relevance score to export")
@click.option("--limit", "-l", type=int, default=50, help="Max articles to export")
def export_notion(min_score, limit):
    """Export scored articles to a Notion database.

    Requires NOTION_TOKEN and NOTION_DATABASE_ID environment variables.
    """
    from src.export.notion import export_to_notion
    try:
        click.echo("Exporting to Notion...")
        stats = export_to_notion(min_score=min_score, limit=limit)
        click.echo(f"Done! Exported: {stats['exported']}, "
                   f"Skipped (duplicate): {stats['skipped_duplicate']}, "
                   f"Errors: {stats['errors']}")
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


# --- API ---

@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", "-p", type=int, default=8000, help="Port to bind to")
def api(host, port):
    """Start the FastAPI server."""
    import uvicorn
    from src.api.main import app
    click.echo(f"Starting API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
