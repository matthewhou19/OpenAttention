# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: AttentionOS

AI-driven RSS reader where Claude Code **is** the AI — no Claude API key needed. Scoring, chat, and interest interpretation all use `claude -p` subprocess calls. Philosophy: **"We save attention, not time."** Pre-compute everything in background; when the user opens the dashboard, the answer is already there.

## Commands

```bash
# Database setup (required before first run — never use create_all())
alembic upgrade head

# Run the API server + dashboard
python cli.py api                        # http://127.0.0.1:8000

# CLI pipeline
python cli.py fetch                      # fetch articles from all feeds
python cli.py score prepare --limit 20   # output unscored articles as JSON
python cli.py score write-file <path>    # write scores from JSON file

# Feed management
python cli.py feeds add <url> -c <category>
python cli.py feeds list
python cli.py feeds remove <id>

# Sections management
python cli.py sections list
python cli.py sections add <name> --icon <emoji> --color <hex> --match <keywords>

# Lint
ruff check .
ruff format .

# Tests
python -m pytest tests/                  # all tests
python -m pytest tests/test_auth.py      # single file
python -m pytest tests/test_auth.py::test_api_returns_401_without_header_when_token_set  # single test
```

## Architecture

**CLI (`cli.py`)** — Click groups: `feeds`, `score`, `sections`, `export`, plus top-level `fetch` and `api` commands. All commands call `init_db()` on startup, which verifies Alembic migrations have been applied.

**Scoring pipeline** — The core loop:
1. `fetch` — RSS via feedparser, dedup by unique URL constraint (IntegrityError skip)
2. `score prepare` — joins unscored articles with `interests.yaml`, outputs JSON
3. Claude evaluates — `subprocess.run(["claude", "-p"], input=prompt, timeout=180)`
4. `score write-file` — upserts Score rows back to DB

The `/api/fetch` endpoint runs this entire pipeline in one call, including the Claude subprocess.

**Database** — SQLite with WAL mode (for concurrent daemon+browser access). 7 tables defined in `src/db/models.py`: `feeds`, `articles`, `scores`, `feedback`, `user_preferences`, `interest_signals`, `chat_messages`. Schema managed exclusively by Alembic (`alembic/versions/`). Session factory in `src/db/session.py` — use `get_session()`, always close in `finally`.

**API** — FastAPI app in `src/api/main.py`. Routers in `src/api/routers/` (articles, feeds, scores). Optional bearer auth via `ATTENTIONOS_TOKEN` env var — if unset, API is open. Auth dependency applied to all `/api/*` routes; dashboard `/` is always public.

**Frontend** — Single `src/api/static/index.html` served at `/`. Vanilla JS, no build step.

**Config** — `src/config.py` defines `DB_PATH`, `DB_URL`, `INTERESTS_PATH`, `SECTIONS_PATH` relative to project root. DB lives at `data/rss.db`.

## Key Conventions

- **Claude integration**: Always `subprocess.run(["claude", "-p"], input=prompt, timeout=N)`. 180s for scoring, 30s for chat.
- **DB migrations**: Alembic only. Never `Base.metadata.create_all()`. Use `render_as_batch=True` in env.py for SQLite ALTER support. New migration: `alembic revision -m "description"`.
- **SQLAlchemy**: Use `select()` for subqueries in IN clauses (not `.subquery()`). Use `get_session()` + `try/finally session.close()` pattern.
- **Frontend**: Vanilla JS + ES modules only. No React, Vue, or build tools.
- **Interests**: `interests.yaml` is the single source of truth for user preferences. `sections.yaml` stores dashboard display config. In Phase 2, interests.yaml absorbs sections.yaml.
- **Windows**: Use `sleep N` not `timeout /t N`. Avoid multi-line shell scripts in subprocess.
- **Ruff**: Line length 120, target Python 3.11, rules E/F/W/I.

## Current State

Phase 1 complete. Phase 2 (interest-first experience) in progress — see `ROADMAP.md` for full plan and technical decisions. Infrastructure prerequisites (Alembic, WAL mode, auth) are done. Next: ranking engine, view modes, chat, onboarding, feedback loop.
