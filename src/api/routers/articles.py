import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db.models import Article, Feed, Score
from src.db.session import get_session

router = APIRouter()


class ScoreOut(BaseModel):
    relevance: float
    significance: float
    summary: str
    topics: list[str]
    reason: str

    model_config = {"from_attributes": True}


class ArticleResponse(BaseModel):
    id: int
    feed_id: int
    feed_title: str
    url: str
    title: str
    author: str
    summary: str
    published_at: str | None
    is_read: bool
    is_starred: bool
    score: ScoreOut | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ArticleResponse])
def list_articles(
    min_score: float = Query(0, description="Minimum relevance score"),
    topic: str = Query("", description="Filter by topic"),
    feed_id: int | None = Query(None, description="Filter by feed"),
    scored_only: bool = Query(False, description="Only show scored articles"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    session = get_session()
    try:
        query = session.query(Article).outerjoin(Score).outerjoin(Feed)

        if scored_only or min_score > 0:
            query = query.filter(Score.id.isnot(None))

        if min_score > 0:
            query = query.filter(Score.relevance >= min_score)

        if topic:
            query = query.filter(Score.topics.contains(topic))

        if feed_id is not None:
            query = query.filter(Article.feed_id == feed_id)

        # Order by score descending (scored first), then by published date
        query = query.order_by(
            Score.relevance.desc().nullslast(),
            Article.published_at.desc().nullslast(),
        )
        articles = query.offset(offset).limit(limit).all()

        result = []
        for a in articles:
            score_out = None
            if a.score:
                topics = json.loads(a.score.topics) if a.score.topics else []
                score_out = ScoreOut(
                    relevance=a.score.relevance,
                    significance=a.score.significance,
                    summary=a.score.summary or "",
                    topics=topics,
                    reason=a.score.reason or "",
                )

            feed_title = ""
            if a.feed:
                feed_title = a.feed.title or a.feed.url

            result.append(ArticleResponse(
                id=a.id,
                feed_id=a.feed_id,
                feed_title=feed_title,
                url=a.url,
                title=a.title or "",
                author=a.author or "",
                summary=a.summary or "",
                published_at=a.published_at.isoformat() if a.published_at else None,
                is_read=a.is_read,
                is_starred=a.is_starred,
                score=score_out,
            ))
        return result
    finally:
        session.close()


@router.get("/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int):
    session = get_session()
    try:
        a = session.query(Article).outerjoin(Score).outerjoin(Feed).filter(Article.id == article_id).first()
        if not a:
            raise HTTPException(status_code=404, detail="Article not found")

        score_out = None
        if a.score:
            topics = json.loads(a.score.topics) if a.score.topics else []
            score_out = ScoreOut(
                relevance=a.score.relevance,
                significance=a.score.significance,
                summary=a.score.summary or "",
                topics=topics,
                reason=a.score.reason or "",
            )

        feed_title = ""
        if a.feed:
            feed_title = a.feed.title or a.feed.url

        return ArticleResponse(
            id=a.id,
            feed_id=a.feed_id,
            feed_title=feed_title,
            url=a.url,
            title=a.title or "",
            author=a.author or "",
            summary=a.summary or "",
            published_at=a.published_at.isoformat() if a.published_at else None,
            is_read=a.is_read,
            is_starred=a.is_starred,
            score=score_out,
        )
    finally:
        session.close()
