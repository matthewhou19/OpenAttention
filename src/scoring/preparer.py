import json
from datetime import datetime, timezone

from src.db.models import Article, Score
from src.db.session import get_session
from src.interests.manager import load_interests


def get_unscored_articles(limit: int = 20) -> list[dict]:
    """Get articles that haven't been scored yet, formatted for Claude Code evaluation."""
    session = get_session()
    try:
        from sqlalchemy import select

        scored_ids = select(Score.article_id)
        articles = (
            session.query(Article)
            .filter(Article.id.notin_(scored_ids))
            .order_by(Article.published_at.desc().nullslast())
            .limit(limit)
            .all()
        )

        result = []
        for a in articles:
            # Use summary if available, fall back to truncated content
            text = a.summary or a.content or ""
            if len(text) > 1000:
                text = text[:1000] + "..."

            result.append(
                {
                    "id": a.id,
                    "title": a.title,
                    "url": a.url,
                    "author": a.author,
                    "text": text,
                    "published_at": a.published_at.isoformat() if a.published_at else None,
                    "feed_id": a.feed_id,
                }
            )
        return result
    finally:
        session.close()


def prepare_scoring_prompt(limit: int = 20) -> str:
    """Prepare the full scoring context: interests + unscored articles as JSON."""
    interests = load_interests()
    articles = get_unscored_articles(limit)

    if not articles:
        return json.dumps({"status": "no_unscored_articles", "count": 0})

    return json.dumps(
        {
            "interests": interests,
            "articles": articles,
            "count": len(articles),
            "instructions": (
                "Score each article. For each, return: "
                "article_id, relevance (0-10), significance (0-10), "
                "confidence (0.0-1.0, how confident you are in the topic tags), "
                "summary (1-2 sentences), topics (list of tags), "
                "reason (why this score). Output as a JSON array."
            ),
        },
        indent=2,
        ensure_ascii=False,
    )


def write_scores(scores_json: str) -> int:
    """Write a batch of scores to the database. Returns count written."""
    scores_data = json.loads(scores_json)
    if not isinstance(scores_data, list):
        raise ValueError("Expected a JSON array of score objects")

    session = get_session()
    written = 0
    try:
        for s in scores_data:
            article_id = s.get("article_id") or s.get("id")
            if not article_id:
                continue

            # Check article exists
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                continue

            # Upsert score
            existing = session.query(Score).filter(Score.article_id == article_id).first()
            if existing:
                existing.relevance = float(s.get("relevance", 0))
                existing.significance = float(s.get("significance", 0))
                existing.summary = s.get("summary", "")
                existing.topics = json.dumps(s.get("topics", []))
                existing.reason = s.get("reason", "")
                existing.confidence = float(s.get("confidence", 1.0))
                existing.scored_at = datetime.now(timezone.utc)
            else:
                score = Score(
                    article_id=article_id,
                    relevance=float(s.get("relevance", 0)),
                    significance=float(s.get("significance", 0)),
                    summary=s.get("summary", ""),
                    topics=json.dumps(s.get("topics", [])),
                    reason=s.get("reason", ""),
                    confidence=float(s.get("confidence", 1.0)),
                )
                session.add(score)
            written += 1

        session.commit()
        return written
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
