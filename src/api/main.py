from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api.routers import articles, feeds, scores
from src.config import SECTIONS_PATH
from src.db.session import init_db

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AttentionOS", version="0.1.0")

app.include_router(feeds.router, prefix="/api/feeds", tags=["feeds"])
app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(scores.router, prefix="/api", tags=["scores"])


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/sections")
def get_sections():
    if not SECTIONS_PATH.exists():
        return []
    data = yaml.safe_load(SECTIONS_PATH.read_text(encoding="utf-8"))
    return data.get("sections", [])


class SectionItem(BaseModel):
    name: str
    icon: str
    color: str
    match: list[str]
    visible: bool = True


@app.put("/api/sections")
def put_sections(items: list[SectionItem]):
    data = {"sections": [s.model_dump() for s in items]}
    SECTIONS_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "count": len(items)}


@app.get("/api/stats")
def get_stats():
    from src.db.models import Article, Feed, Feedback, Score
    from src.db.session import get_session

    session = get_session()
    try:
        return {
            "feeds": session.query(Feed).count(),
            "feeds_enabled": session.query(Feed).filter(Feed.enabled == True).count(),
            "articles": session.query(Article).count(),
            "scored": session.query(Score).count(),
            "feedback": session.query(Feedback).count(),
        }
    finally:
        session.close()
