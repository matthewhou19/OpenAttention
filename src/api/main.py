from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routers import articles, feeds, scores
from src.db.session import init_db

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="AI RSS", version="0.1.0")

app.include_router(feeds.router, prefix="/api/feeds", tags=["feeds"])
app.include_router(articles.router, prefix="/api/articles", tags=["articles"])
app.include_router(scores.router, prefix="/api", tags=["scores"])


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def startup():
    init_db()


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
