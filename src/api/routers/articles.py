import base64
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db.models import Article, Feed, Score
from src.db.session import get_session
from src.interests.manager import load_interests
from src.scoring.ranker import compute_rank, max_topic_weight

logger = logging.getLogger(__name__)

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
    feed_category: str
    url: str
    title: str
    author: str
    summary: str
    published_at: str | None
    is_read: bool
    is_starred: bool
    score: ScoreOut | None
    rank: float | None = None

    model_config = {"from_attributes": True}


class ForYouPage(BaseModel):
    articles: list[ArticleResponse]
    next_cursor: str | None = None


def _build_article_response(a: Article, *, rank: float | None = None) -> ArticleResponse:
    """Convert an Article ORM object to an ArticleResponse."""
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
    feed_category = ""
    if a.feed:
        feed_title = a.feed.title or a.feed.url
        feed_category = a.feed.category or ""

    return ArticleResponse(
        id=a.id,
        feed_id=a.feed_id,
        feed_title=feed_title,
        feed_category=feed_category,
        url=a.url,
        title=a.title or "",
        author=a.author or "",
        summary=a.summary or "",
        published_at=a.published_at.isoformat() if a.published_at else None,
        is_read=a.is_read,
        is_starred=a.is_starred,
        score=score_out,
        rank=rank,
    )


def _encode_cursor(rank: float, article_id: int) -> str:
    """Encode rank:id as a base64 cursor string."""
    raw = f"{rank}:{article_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[float, int] | None:
    """Decode a base64 cursor into (rank, id). Returns None on failure."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        rank_str, id_str = raw.split(":", 1)
        return float(rank_str), int(id_str)
    except Exception:
        logger.warning("Invalid cursor value, falling back to first page")
        return None


def _foryou_view(
    limit: int,
    cursor: str | None,
) -> ForYouPage:
    """Return articles ranked by composite score with exploration slots."""
    interests = load_interests()
    session = get_session()
    try:
        # Fetch all scored, non-archived articles (join(Score) = INNER JOIN, excludes unscored)
        articles = (
            session.query(Article)
            .join(Score)
            .outerjoin(Feed)
            .filter(Article.is_archived != True)  # noqa: E712
            .all()
        )

        if not articles:
            return ForYouPage(articles=[], next_cursor=None)

        # Compute ranks for all articles
        ranked = []
        for a in articles:
            r = compute_rank(a, a.score, interests)
            ranked.append((a, r))

        # Split into main (high-weight topics) and exploration (floor-weight topics)
        main_pool = []
        explore_pool = []
        for a, r in ranked:
            weight = max_topic_weight(a.score.topics_list, interests)
            if weight <= 1.0:
                explore_pool.append((a, r))
            else:
                main_pool.append((a, r))

        # Sort both pools by rank descending, then by id descending for deterministic ordering
        main_pool.sort(key=lambda x: (-x[1], -x[0].id))
        explore_pool.sort(key=lambda x: (-x[1], -x[0].id))

        # Interleave exploration at every 10th position
        merged = []
        main_idx = 0
        explore_idx = 0
        position = 0

        while main_idx < len(main_pool) or explore_idx < len(explore_pool):
            position += 1
            # Every 10th slot is an exploration slot
            if position % 10 == 0 and explore_idx < len(explore_pool):
                merged.append(explore_pool[explore_idx])
                explore_idx += 1
            elif main_idx < len(main_pool):
                merged.append(main_pool[main_idx])
                main_idx += 1
            elif explore_idx < len(explore_pool):
                merged.append(explore_pool[explore_idx])
                explore_idx += 1

        # Apply cursor filtering — find the cursor item by ID, skip everything before and including it
        cursor_data = _decode_cursor(cursor) if cursor else None
        if cursor_data:
            cursor_rank, cursor_id = cursor_data
            # Find the index of the cursor item in the merged list
            cursor_pos = None
            for i, (a, r) in enumerate(merged):
                if a.id == cursor_id:
                    cursor_pos = i
                    break
            if cursor_pos is not None:
                merged = merged[cursor_pos + 1 :]
            else:
                # Cursor ID not found — fall back to rank-based filtering
                merged = [(a, r) for a, r in merged if r < cursor_rank or (r == cursor_rank and a.id < cursor_id)]

        # Paginate
        page = merged[:limit]
        has_more = len(merged) > limit

        # Build response
        result_articles = [_build_article_response(a, rank=round(r, 4)) for a, r in page]

        next_cursor = None
        if has_more and page:
            last_a, last_r = page[-1]
            next_cursor = _encode_cursor(round(last_r, 4), last_a.id)

        return ForYouPage(articles=result_articles, next_cursor=next_cursor)
    finally:
        session.close()


@router.get("")
def list_articles(
    view: str = Query("", description="View mode: 'foryou' or empty for legacy"),
    min_score: float = Query(0, description="Minimum relevance score"),
    topic: str = Query("", description="Filter by topic"),
    feed_id: int | None = Query(None, description="Filter by feed"),
    scored_only: bool = Query(False, description="Only show scored articles"),
    include_archived: bool = Query(False, description="Include archived articles"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None, description="Cursor for pagination (foryou view only)"),
):
    if view == "foryou":
        return _foryou_view(limit=limit, cursor=cursor)

    # Legacy behavior — unchanged
    session = get_session()
    try:
        query = session.query(Article).outerjoin(Score).outerjoin(Feed)

        if not include_archived:
            query = query.filter(Article.is_archived != True)  # noqa: E712

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

        return [_build_article_response(a) for a in articles]
    finally:
        session.close()


@router.get("/{article_id}", response_model=ArticleResponse)
def get_article(article_id: int):
    session = get_session()
    try:
        a = session.query(Article).outerjoin(Score).outerjoin(Feed).filter(Article.id == article_id).first()
        if not a:
            raise HTTPException(status_code=404, detail="Article not found")
        return _build_article_response(a)
    finally:
        session.close()
