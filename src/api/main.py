import json
import os
import subprocess
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.api.auth import verify_token
from src.api.routers import articles, feeds, scores
from src.config import SECTIONS_PATH
from src.db.session import init_db

STATIC_DIR = Path(__file__).parent / "static"

# Disable OpenAPI docs when auth is active — prevents schema leak on protected deployments
_token_set = bool(os.environ.get("ATTENTIONOS_TOKEN", "").strip())
app = FastAPI(
    title="AttentionOS",
    version="0.1.0",
    docs_url=None if _token_set else "/docs",
    redoc_url=None if _token_set else "/redoc",
    openapi_url=None if _token_set else "/openapi.json",
)

_auth = [Depends(verify_token)]

app.include_router(feeds.router, prefix="/api/feeds", tags=["feeds"], dependencies=_auth)
app.include_router(articles.router, prefix="/api/articles", tags=["articles"], dependencies=_auth)
app.include_router(scores.router, prefix="/api", tags=["scores"], dependencies=_auth)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/sections", dependencies=_auth)
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


@app.put("/api/sections", dependencies=_auth)
def put_sections(items: list[SectionItem]):
    data = {"sections": [s.model_dump() for s in items]}
    SECTIONS_PATH.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "count": len(items)}


@app.get("/api/stats", dependencies=_auth)
def get_stats():
    from src.db.models import Article, Feed, Feedback, Score
    from src.db.session import get_session

    session = get_session()
    try:
        return {
            "feeds": session.query(Feed).count(),
            "feeds_enabled": session.query(Feed).filter(Feed.enabled).count(),
            "articles": session.query(Article).count(),
            "scored": session.query(Score).count(),
            "feedback": session.query(Feedback).count(),
        }
    finally:
        session.close()


@app.post("/api/fetch", dependencies=_auth)
def api_fetch():
    """Fetch new articles from all feeds, then auto-score with Claude CLI."""
    from src.feeds.fetcher import fetch_all
    from src.scoring.preparer import prepare_scoring_prompt, write_scores

    # 1. Fetch
    results = fetch_all()
    total = sum(c for c in results.values() if c >= 0)

    # 2. Auto-score unscored articles
    scored = 0
    score_error = None
    batch = prepare_scoring_prompt(limit=30)
    batch_data = json.loads(batch)

    if batch_data.get("status") != "no_unscored_articles":
        prompt = (
            "You are scoring articles for AttentionOS. "
            "Given the user interests and articles below, score each article.\n\n"
            f"{batch}\n\n"
            "Return ONLY a valid JSON array. No markdown fences, no extra text. "
            'Each element: {"article_id": <id>, "relevance": <0-10>, '
            '"significance": <0-10>, "summary": "<1-2 sentences>", '
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
            if result.returncode == 0:
                output = result.stdout.strip()
                start = output.find("[")
                end = output.rfind("]") + 1
                if start != -1 and end > 0:
                    scored = write_scores(output[start:end])
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
            score_error = str(e)

    return {
        "results": results,
        "total_new": total,
        "scored": scored,
        "score_error": score_error,
    }


@app.post("/api/score", dependencies=_auth)
def api_score(limit: int = 20):
    from src.scoring.preparer import prepare_scoring_prompt, write_scores

    batch = prepare_scoring_prompt(limit=limit)
    batch_data = json.loads(batch)

    if batch_data.get("status") == "no_unscored_articles":
        return {"status": "no_unscored", "scored": 0}

    prompt = (
        "You are scoring articles for AttentionOS. "
        "Given the user interests and articles below, score each article.\n\n"
        f"{batch}\n\n"
        "Return ONLY a valid JSON array. No markdown fences, no extra text. "
        'Each element: {"article_id": <id>, "relevance": <0-10>, '
        '"significance": <0-10>, "summary": "<1-2 sentences>", '
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
        return {"status": "error", "error": "Claude CLI not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Scoring timed out (180s)"}

    if result.returncode != 0:
        return {"status": "error", "error": result.stderr[:500]}

    output = result.stdout.strip()
    start = output.find("[")
    end = output.rfind("]") + 1
    if start == -1 or end == 0:
        return {"status": "error", "error": "No JSON array in response"}

    try:
        count = write_scores(output[start:end])
        return {"status": "ok", "scored": count}
    except (json.JSONDecodeError, ValueError) as e:
        return {"status": "error", "error": str(e)}
