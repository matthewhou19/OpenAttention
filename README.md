# OpenAttention

**An attention-first RSS reader where AI is the gatekeeper.** A background daemon fetches your feeds, a Claude scoring pipeline reads every article against your interest profile, and an API serves only the ranked, high-value remainder. You don't skim 200 headlines — you open the feed and the answer is already computed.

> Internal codename: *AttentionOS* (you'll see it in the API title and the `ATTENTIONOS_TOKEN` env var).

## Why

A professional tracking 30+ sources spends an hour a day separating signal from noise. OpenAttention inverts that: **we save attention, not time.** Slow AI work (30-180s scoring runs) happens asynchronously in the background; reading happens instantly against pre-computed scores.

## How it works

```
 RSS/Atom feeds                    interests.yaml (your profile)
       │                                   │
       ▼                                   ▼
 ┌──────────┐    ┌──────────┐    ┌──────────────────┐    ┌─────────────┐
 │ fetcher  │───▶│  SQLite  │───▶│ Claude scoring   │───▶│ ranked      │
 │ (hourly) │    │  (WAL)   │    │ (claude -p sub-  │    │ "For You"   │
 └──────────┘    └──────────┘    │  process, JSON)  │    │ API feed    │
       ▲                          └──────────────────┘    └─────────────┘
       │                                   │
 ┌─────┴────────────────────────────────── ▼ ─────┐
 │ background daemon: fetch → score → archive old │
 │ low-value articles → re-score on profile change │
 └──────────────────────────────────────────────────┘
```

- **No API key required.** Scoring shells out to the [Claude Code CLI](https://claude.com/claude-code) (`claude -p`), so it runs on your existing Claude subscription. Timeouts, malformed-output recovery, and skip-and-retry are built in.
- **Daemon and API share one SQLite database safely** (WAL mode, busy timeout).
- **Interest changes trigger re-scoring**: edit your profile, and recent articles are automatically re-evaluated on the next cycle.
- **Self-cleaning**: articles older than 7 days that scored poorly (or never got scored) are archived; bookmarked/liked items are exempt.

## Quickstart (~10 minutes)

Prerequisites: Python 3.11+, and the Claude Code CLI installed and authenticated (`npm install -g @anthropic-ai/claude-code`). Without Claude Code, everything except automatic scoring still works — see [Scoring without Claude](#scoring-without-claude).

```bash
git clone https://github.com/matthewhou19/OpenAttention.git
cd OpenAttention

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e .
alembic upgrade head               # create the SQLite schema (required)
```

Add feeds and run one cycle:

```bash
rss feeds add https://hnrss.org/frontpage --category tech
rss feeds add https://simonwillison.net/atom/everything/ --category ai

rss fetch                          # pull new articles
rss api                            # serve at http://127.0.0.1:8000
```

Score the backlog (uses `claude -p` under the hood):

```bash
curl -X POST http://127.0.0.1:8000/api/score?limit=20
```

Then open your ranked feed:

```bash
curl "http://127.0.0.1:8000/api/articles?view=foryou&limit=10"
```

Edit `interests.yaml` to describe what you actually care about — topics, weights, and context notes all feed directly into the scoring prompt.

## Run it unattended

```bash
rss daemon                 # fetch + score + cleanup every hour
rss daemon --interval 1800 # every 30 minutes
```

The daemon logs every cycle (`fetched / scored / archived` counts) and degrades gracefully: if Claude is unavailable or times out, scoring is skipped and retried next cycle — fetching never stops.

## CLI reference

| Command | What it does |
|---|---|
| `rss feeds add <url> [-c category]` | Add an RSS/Atom feed (feedparser handles both) |
| `rss feeds list` / `remove <id>` | Manage feeds |
| `rss fetch [--feed-id N]` | Fetch new articles (URL-level dedup) |
| `rss score prepare [-l N]` | Emit unscored articles + interest profile as a JSON scoring batch |
| `rss score write '<json>'` / `write-file <path>` | Write scores back (validated) |
| `rss sections list/add/remove/update` | Manage dashboard topic sections (`sections.yaml`) |
| `rss export notion` | Push scored articles to a Notion database |
| `rss daemon [--interval secs]` | Background loop: fetch → score → cleanup |
| `rss api [--host H] [--port P]` | Start the FastAPI server |

(`rss` is installed by `pip install -e .`; `python cli.py …` works identically.)

## API reference

All routes accept `Authorization: Bearer <token>` when `ATTENTIONOS_TOKEN` is set; without the env var the API runs open in dev mode and interactive docs are available at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/articles?view=foryou&cursor=…` | Ranked "For You" feed (composite score + confidence, cursor pagination) |
| `GET /api/articles?min_score=…&topic=…` | Filtered article list |
| `POST /api/fetch` | Fetch all feeds, then auto-score new articles |
| `POST /api/score?limit=N` | Score the unscored backlog via Claude |
| `POST /api/feedback` | Record like/save/skip signals |
| `GET /api/stats` | Feed/article/score counts |
| `GET /api/feeds` · `POST /api/feeds` · `DELETE /api/feeds/{id}` | Feed management |
| `GET /api/sections` · `PUT /api/sections` | Dashboard section config |

## Scoring without Claude

The scoring layer is deliberately decoupled — `score prepare` emits a self-contained JSON batch (articles + your interest profile), and `score write` validates and persists whatever scores come back:

```bash
rss score prepare -l 20 > batch.json
# … run batch.json through any LLM you like …
rss score write-file scores.json
```

This is also the escape hatch for CI, air-gapped boxes, or swapping in a different model.

## Configuration

| File / env var | Purpose |
|---|---|
| `interests.yaml` | Your interest profile — the single source of truth the scorer reads |
| `sections.yaml` | Topic sections (name, icon, color, keyword matchers) |
| `ATTENTIONOS_TOKEN` | Optional bearer token; also disables public `/docs` when set |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID` | Only needed for `rss export notion` |

## Project layout

```
cli.py              # Click CLI (entry point: rss)
src/feeds/          # fetch + dedup (feedparser)
src/scoring/        # batch preparer, score writer, composite ranker
src/interests/      # interest profile loader
src/api/            # FastAPI app, bearer auth, routers
src/export/         # Notion exporter
src/daemon.py       # hourly fetch → score → cleanup loop
alembic/            # schema migrations
tests/              # pytest suite (daemon, ranker, re-scoring, auth, migrations)
```

## Tests

```bash
pip install pytest
pytest
```

The suite covers the daemon cycle, composite ranker, interest-change re-scoring, bearer auth, retention/cleanup rules, and Alembic migrations.

## Roadmap

See [ROADMAP.md](ROADMAP.md). Headline items: web dashboard UI, feedback-driven weight adjustment, smarter exploration slots.
