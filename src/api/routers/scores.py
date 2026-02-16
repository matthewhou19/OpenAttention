import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db.models import Article, Feedback, Score
from src.db.session import get_session

router = APIRouter()


class ScoreItem(BaseModel):
    article_id: int
    relevance: float = 0
    significance: float = 0
    summary: str = ""
    topics: list[str] = []
    reason: str = ""


class FeedbackCreate(BaseModel):
    article_id: int
    action: str  # like, dislike, save, skip


@router.post("/scores", status_code=201)
def write_scores(items: list[ScoreItem]):
    """Batch write scores from Claude Code evaluation."""
    session = get_session()
    written = 0
    try:
        for item in items:
            article = session.query(Article).filter(Article.id == item.article_id).first()
            if not article:
                continue

            existing = session.query(Score).filter(Score.article_id == item.article_id).first()
            if existing:
                existing.relevance = item.relevance
                existing.significance = item.significance
                existing.summary = item.summary
                existing.topics = json.dumps(item.topics)
                existing.reason = item.reason
                existing.scored_at = datetime.now(timezone.utc)
            else:
                score = Score(
                    article_id=item.article_id,
                    relevance=item.relevance,
                    significance=item.significance,
                    summary=item.summary,
                    topics=json.dumps(item.topics),
                    reason=item.reason,
                )
                session.add(score)
            written += 1

        session.commit()
        return {"written": written}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/feedback", status_code=201)
def create_feedback(body: FeedbackCreate):
    """Record user feedback on an article."""
    valid_actions = {"like", "dislike", "save", "skip"}
    if body.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Action must be one of: {valid_actions}")

    session = get_session()
    try:
        article = session.query(Article).filter(Article.id == body.article_id).first()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        fb = Feedback(article_id=body.article_id, action=body.action)
        session.add(fb)
        session.commit()
        return {"status": "ok", "article_id": body.article_id, "action": body.action}
    finally:
        session.close()
