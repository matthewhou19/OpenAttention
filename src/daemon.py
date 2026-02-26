"""Background daemon: hourly fetch + score + cleanup loop (Issue #4).

Core pattern: pre-compute everything in the background.
When the user opens the dashboard, data is already ready.
"""

import json
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.db.models import Article, Feedback, Score, UserPreference
from src.db.session import get_session, init_db
from src.feeds.fetcher import fetch_all
from src.scoring.preparer import prepare_scoring_prompt, write_scores

logger = logging.getLogger(__name__)


def score_unscored(limit: int = 30) -> int:
    """Score unscored articles via Claude CLI subprocess. Returns count scored."""
    batch = prepare_scoring_prompt(limit=limit)
    batch_data = json.loads(batch)

    if batch_data.get("status") == "no_unscored_articles":
        return 0

    prompt = (
        "You are scoring articles for AttentionOS. "
        "Given the user interests and articles below, score each article.\n\n"
        f"{batch}\n\n"
        "Return ONLY a valid JSON array. No markdown fences, no extra text. "
        'Each element: {"article_id": <id>, "relevance": <0-10>, '
        '"significance": <0-10>, "confidence": <0.0-1.0>, '
        '"summary": "<1-2 sentences>", '
        '"topics": ["tag1"], "reason": "<why>"}'
    )

    try:
        result = subprocess.run(
            ["claude", "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=180,
            encoding="utf-8",
        )
    except FileNotFoundError:
        logger.error("Claude CLI not found in PATH — scoring skipped")
        return 0
    except subprocess.TimeoutExpired:
        logger.error("Claude scoring timed out (180s) — skipped, will retry next cycle")
        return 0

    if result.returncode != 0:
        logger.error("Claude scoring failed (exit %d): %s", result.returncode, result.stderr[:500])
        return 0

    output = result.stdout.strip()
    start = output.find("[")
    end = output.rfind("]") + 1
    if start == -1 or end == 0:
        logger.error("No JSON array in Claude response — scoring skipped")
        return 0

    return write_scores(output[start:end])


def cleanup_articles(session) -> int:
    """Archive old, low-value articles. Returns count archived.

    Rules:
    - Articles older than 7 days with no score OR relevance+significance < 3 → archived
    - Bookmarked (save) and liked articles are exempt
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Find exempt article IDs (have "save" or "like" feedback)
    exempt_ids = session.query(Feedback.article_id).filter(Feedback.action.in_(["save", "like"])).distinct().all()
    exempt_set = {row[0] for row in exempt_ids}

    # Find old, non-archived articles
    old_articles = (
        session.query(Article)
        .outerjoin(Score)
        .filter(
            Article.fetched_at < cutoff,
            Article.is_archived != True,  # noqa: E712
        )
        .all()
    )

    archived = 0
    for article in old_articles:
        if article.id in exempt_set:
            continue

        # No score → archive
        if article.score is None:
            article.is_archived = True
            archived += 1
            continue

        # Low combined score → archive
        combined = article.score.relevance + article.score.significance
        if combined < 3:
            article.is_archived = True
            archived += 1

    if archived > 0:
        session.commit()

    return archived


def check_rescore(session) -> None:
    """Check needs_rescore flag and re-score recent articles if set.

    When interests undergo a structural change (topic added/removed),
    delete scores for articles from the last 7 days so they get re-scored
    with the updated interest profile.
    """
    pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
    if pref is None:
        return

    try:
        value = json.loads(pref.value)
    except (json.JSONDecodeError, TypeError):
        return

    if value != "true":
        return

    logger.info("needs_rescore flag set — re-scoring recent articles")

    # Delete scores for articles fetched within the last 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent_article_ids = select(Article.id).where(Article.fetched_at > cutoff)
    deleted = session.query(Score).filter(Score.article_id.in_(recent_article_ids)).delete(synchronize_session="fetch")
    if deleted > 0:
        session.commit()
        logger.info("Deleted %d scores for re-scoring", deleted)

    try:
        score_unscored(limit=50)
    except Exception:
        logger.exception("Re-scoring failed; articles will be scored in next normal cycle")

    # Always clear the flag — articles are unscored and will be picked up normally
    pref.value = json.dumps("false")
    pref.updated_at = datetime.now(timezone.utc)
    session.commit()


def run_cycle() -> None:
    """Execute one daemon cycle: fetch → score → cleanup → rescore check."""
    fetched_total = 0
    scored = 0
    archived = 0

    try:
        # Fetch
        results = fetch_all()
        for feed_name, count in results.items():
            if count < 0:
                logger.warning("Feed '%s': fetch error", feed_name)
            else:
                logger.info("Feed '%s': %d new articles", feed_name, count)
                fetched_total += count
    except Exception:
        logger.exception("Fetch phase failed")

    try:
        # Score
        scored = score_unscored()
    except Exception:
        logger.exception("Score phase failed")

    try:
        # Cleanup
        session = get_session()
        try:
            archived = cleanup_articles(session)
        finally:
            session.close()
    except Exception:
        logger.exception("Cleanup phase failed")

    try:
        # Rescore check
        session = get_session()
        try:
            check_rescore(session)
        finally:
            session.close()
    except Exception:
        logger.exception("Rescore check failed")

    logger.info(
        "Cycle complete — fetched: %d, scored: %d, archived: %d",
        fetched_total,
        scored,
        archived,
    )


def run_daemon(interval: int = 3600) -> None:
    """Run the daemon loop: init_db once, then cycle forever."""
    init_db()
    logger.info("Daemon started (interval=%ds)", interval)

    while True:
        logger.info("Starting cycle at %s", datetime.now(timezone.utc).isoformat())
        run_cycle()
        time.sleep(interval)
