from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class FeedCreate(BaseModel):
    url: str
    category: str = ""


class FeedResponse(BaseModel):
    id: int
    url: str
    title: str
    site_url: str
    category: str
    enabled: bool
    last_fetched_at: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[FeedResponse])
def list_feeds(enabled_only: bool = False):
    from src.feeds.manager import list_feeds

    feeds = list_feeds(enabled_only)
    result = []
    for f in feeds:
        result.append(
            FeedResponse(
                id=f.id,
                url=f.url,
                title=f.title or "",
                site_url=f.site_url or "",
                category=f.category or "",
                enabled=f.enabled,
                last_fetched_at=f.last_fetched_at.isoformat() if f.last_fetched_at else None,
            )
        )
    return result


@router.post("", response_model=FeedResponse, status_code=201)
def create_feed(body: FeedCreate):
    from src.feeds.manager import add_feed

    try:
        f = add_feed(body.url, body.category)
        return FeedResponse(
            id=f.id,
            url=f.url,
            title=f.title or "",
            site_url=f.site_url or "",
            category=f.category or "",
            enabled=f.enabled,
            last_fetched_at=f.last_fetched_at.isoformat() if f.last_fetched_at else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{feed_id}", status_code=204)
def delete_feed(feed_id: int):
    from src.feeds.manager import remove_feed

    if not remove_feed(feed_id):
        raise HTTPException(status_code=404, detail="Feed not found")
