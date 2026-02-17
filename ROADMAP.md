# AttentionOS - Roadmap

> In the AI era, you tell AI what matters to you. You don't search. You don't browse. You don't scroll. Your attention only touches the most valuable information. AI is your attention gatekeeper.

---

## Phase 1: Foundation (COMPLETE)

The core pipeline — AI reads the internet for you, scores everything, and presents only what matters.

- [x] Database layer (SQLite + SQLAlchemy, 5 tables)
- [x] Feed management CLI (add/remove/list RSS sources)
- [x] Article fetcher (RSS parsing, dedup via unique URLs)
- [x] AI scoring pipeline (prepare -> Claude Code evaluates -> write-back)
- [x] Interest profile (`interests.yaml` — tell AI what you care about)
- [x] FastAPI API server (articles, feeds, scores, feedback, stats)
- [x] Claude Code slash command (`/check-feeds` — full pipeline in one command)
- [x] Full self-test (65 articles scored across 3 feeds)
- [x] Kanban dashboard (topic columns, score filters, feedback buttons)
- [x] Persistent sections (`sections.yaml` — configurable via AI conversation)
- [x] Dashboard in-app controls: fetch, score, add feed from browser (#8, #9 — DONE)
- [x] Notion export (optional)
- [x] GitHub repo: [AttentionOS](https://github.com/matthewhou19/AttentionOS)

---

## Phase 2: Interest-First Experience — You Only Say What Matters

Phase 1 built a power-user tool: visible scores, manual feed management, threshold sliders. But users shouldn't care about any of that. You tell the system what interests you — it handles the rest. This phase flips the entire UX.

### Pillar 1: Onboarding & Conversational Interface (#13)

The user's first and primary interaction is **conversation** — not buttons, not forms, not config files.

**Onboarding:**
- First-visit detection: if `interests.yaml` is empty or missing, show onboarding instead of dashboard
- Single text box: user describes interests in their own words, as vague or specific as they want
- Claude interprets the free text into a structured interest profile (topics with weights, keywords, exclusions)
- User sees an editable summary — topic chips they can tweak, remove, or add to — then confirms
- One interaction, done. No multi-step wizard. No forced topic picker.
- `interests.yaml` becomes the single source of truth — absorbs display properties (icon, color) from `sections.yaml`

**AI Chatbox** (#13):
- Floating chatbox in dashboard corner — the single point of interaction
- Natural language for everything: "I'm getting tired of ChatGPT wrapper articles", "Show me more about Rust", "What's new today?"
- Replaces manual dashboard controls (#8, #9) — fetch, score, add feed, edit interests all through conversation
- Backend: `/api/chat` endpoint, Claude interprets intent → calls existing services → returns conversational results
- Context-aware: knows current dashboard state, recent feedback, user's interest profile

New backend:
- `src/interests/manager.py` — read/write/merge logic for `interests.yaml`
- `POST /api/interests/interpret` — free text → structured profile via Claude
- `GET/PUT /api/interests` — read and save the interest profile
- `POST /api/chat` — conversational interface to all system actions

**Technical Decisions:**
- **Chat backend**: `POST /api/chat` calls `claude -p` subprocess (same pattern as existing `/api/fetch` and `/api/score`). No Claude API key required. 30s response time is acceptable — *"we save attention, not time."* Future: optional Claude API upgrade path for users who want faster responses.
- **Chat history**: New `chat_messages` DB table (`id`, `role`, `content`, `created_at`). Last 10 messages sent as context per call. Chat prompt includes current interests profile and recent feedback actions for context awareness.
- **interests.yaml absorbs sections.yaml**: Add `icon` and `color` fields to each topic in `interests.yaml`. `src/interests/manager.py` auto-generates `sections.yaml` from interests on write. The existing "nba" section (contradicts `exclude: sports`) is dropped during migration.
- **Frontend architecture**: Split `src/api/static/index.html` (currently 631 lines) into ES modules: `app.js`, `chat.js`, `focus.js`, `onboarding.js`, `styles.css`. No framework, no build step — `<script type="module">` in a minimal `index.html` shell.
- **Chat → Dashboard reactivity**: Chat response includes an `action` field that tells the frontend what to refresh. Examples: `{action: "refresh_articles"}` after a fetch, `{action: "refresh_interests"}` after a profile change, `{action: null}` for pure Q&A. Frontend calls the corresponding API reload on receiving the action.

### Pillar 2: Invisible Curation & Focus View (#10, #11)

Scores, feeds, and thresholds disappear from the main UI. The system still scores everything — it just never shows the numbers. The presentation is designed around **focused attention**, not information overload.

**"For You" view** (default):
- Single vertically-scrolling feed, ranked by a composite score that blends relevance, significance, topic weight, and recency. Best stuff first.
- Article cards show: title (link), AI summary, topic chips (colored), source name (small), time ago. No score pills, no R/S numbers.
- Composite ranking replaces the min_score filter. Low-quality articles simply fall below the fold — nothing to configure.

**"Focus" view** (#10, #11):
- One interest section fills the viewport at a time — full attention on one topic before moving on
- 3 articles per section, rendered large and prominent (spotlight/magnifying glass effect)
- Scroll-snap between sections (`scroll-snap-type: y mandatory`), scroll within section to reveal more articles
- Section nav sidebar (dot indicators) for quick jumping
- Sections ordered by learned interest weight — most relevant topic first
- Sections with 0 articles auto-skipped

> *"Attention is not just about what you show — it's about what you don't show."*
> Showing 3 items at a time forces the system (and the user) to trust the scoring algorithm. It's a product statement: **we've already done the filtering for you.**

**Settings panel** (gear icon): interests editor, source list, advanced/debug scores. Power features still accessible, just not in your face.

New backend:
- `src/scoring/ranker.py` — composite rank formula
- Updated `GET /api/articles` — sort by rank, auto-hide low-rank, support `?view=feed|focus|topics`

**Technical Decisions:**
- **Composite rank formula (fully specified)**: `composite = (relevance × max_topic_weight / 10) + (significance × 0.3) + recency_bonus` where `recency_bonus = 2 × exp(-age_hours / 48)` — 2pts when fresh, ~1pt at 48h, ~0 at 96h. Multi-topic articles use the highest matching topic weight. Total range: 0–15. No re-scoring needed — recency_bonus handles staleness naturally.
- **Topic confidence**: Add `confidence` field (0.0–1.0) to AI scoring instructions and `Score` model. Low-confidence topic tags have halved weight in the feedback loop. Prevents misclassified-topic signals from corrupting interest weights.
- **Three view modes**: "For You" (default, composite-ranked feed), "Focus" (scroll-snap, 3 articles/section), "Classic" (kanban — existing behavior preserved). View switcher lives in settings panel (gear icon).
- **Pagination**: Cursor-based for "For You" (rank-ordered). Offset-based for "Classic" (existing behavior, sufficient at single-user scale).
- **Empty states**: Post-onboard no articles → "Your interests are set! Fetching articles..." + auto-fetch trigger. Focus view all sections empty → "Nothing yet — check back soon" + fetch button. Filter no results → "No articles match this filter."
- **Read tracking & de-prioritization**: Clicking an article link auto-marks `is_read = True` (piggybacks on dwell time tracking). Read articles get rank × 0.3 in "For You", pushing unread content above the fold. Prevents stale "same top 5 articles every day" problem.
- **Focus View multi-topic**: Articles matching multiple topics appear in the **highest-weight section only**, no duplication. Consistent with the rank formula (use max topic weight).

### Pillar 3: Active Feedback Loop (#12 — Phase 1)

The system actively but gently collects feedback, then silently adjusts your interest profile. You never touch a config — you just see better content over time.

This is the **first stage** of #12 (Interest Profiles). Simple weight adjustments now; full preference vectors and pattern extraction come in Phase 4.

**Collecting signals:**
- Thumbs up / thumbs down / bookmark on every article card
- **Dwell time tracking**: when you click an article link, the system starts a timer. When you return to the dashboard (tab regains focus), it measures how long you were reading.
- **Gentle prompts**: if you spent 60+ seconds on an article, a subtle toast appears: *"Enjoyed that?"* with thumbs up/down. Auto-dismisses after 5 seconds if ignored.
- **Conversational feedback** via chatbox (#13): "I'm getting tired of ChatGPT wrapper articles" → directly updates profile

**Accumulating signals:**
- New `interest_signals` DB table: per-topic engagement counters (likes, dislikes, saves, dwells)
- Every feedback action maps back to the article's scored topics and increments the relevant counters
- New API: `POST /api/feedback/dwell` for time-based signals

**Invisible adjustment:**
- After enough signals accumulate, the system auto-adjusts `interests.yaml` weights in the background
- High like-ratio topics → weight increases. High dislike-ratio → weight decreases.
- If engagement clusters on an unrecognized topic, surface a one-tap prompt: *"You've been reading a lot about Kubernetes — see more?"*
- User never sees weight numbers, never manages a config. Content just gets better.

**Technical Decisions:**
- **Cold-start threshold**: 5 actions (not 20) before first weight adjustment. Users need to feel the system learning quickly to build trust. Step sizes decay with volume: first 10 actions → ±0.5 weight change; 10–50 → ±0.2; 50+ → ±0.1.
- **Exploration floor (anti filter-bubble)**: No topic weight drops below 1.0 (hard floor). Reserve 10% of "For You" slots for articles from low-weight topics. Prevents the negative feedback loop where one dislike starves an entire topic of future exposure.
- **Dwell time implementation**: Page Visibility API (`visibilitychange` event). Cap at 5 minutes (beyond = user left). Ignore < 10 seconds (accidental click). Stored in `interest_signals` table via `POST /api/feedback/dwell`.
- **Prompt fatigue guard**: Max 3 gentle prompts per session. Minimum 10-minute cooldown between prompts. Dismissed prompts count toward the cap. No opt-out toggle needed — the cap itself prevents fatigue.
- **Bookmark signal weight**: `save` (bookmark) = 2× like signal strength. A deliberate save — "I want this later" — is a stronger interest indicator than a thumbs-up. Bookmarked articles are also exempt from retention cleanup.

### Infrastructure Prerequisites (Phase 2)

These must be in place before Phase 2 features are built.

**Implementation order:**
```
Infrastructure Prerequisites
  ↓
Pillar 2 (Ranking + Views)     ← independent, no dependencies
  ↓
Pillar 1 (Chat + Onboarding)   ← needs interests manager
  ↓
Pillar 3 (Feedback Loop)       ← needs For You view to exist
```

**DB migrations — Alembic:**
- Set up Alembic before any new tables. New tables for Phase 2: `interest_signals` (per-topic engagement counters), `chat_messages` (chat history).
- `UserPreference` table (already exists, unused) — repurpose as key/value store for session preferences and view state.

**SQLite WAL mode:**
- Enable `PRAGMA journal_mode=WAL` at engine creation — required for daemon (writer) + browser (reader) concurrent access. Without WAL, SQLite throws `database is locked` under concurrent use.
- Add `connect_args={"timeout": 15}` to `create_engine` for write contention grace period.

**Auth — optional bearer token:**
- Single env var `ATTENTIONOS_TOKEN` in `.env`. If not set, API is open (dev mode).
- FastAPI dependency reads `Authorization: Bearer <token>` header.
- No login page, no session management — single-user tool.

**Background daemon:**
- New CLI command: `python cli.py daemon` — runs fetch + score every hour in a loop.
- Alternative: Windows Task Scheduler for always-on operation.
- Resilience: top-level `try/except` around each cycle — one failed run never kills the daemon. Single-feed failures already isolated by `fetch_all`. Claude timeouts skip scoring; unscored articles picked up next cycle automatically.
- This is the core architectural pattern: **pre-compute everything in the background. When the user opens the dashboard, data is already ready.** Chat is just the preference layer; ranking is just the presentation layer — both over pre-computed scores.

**Article retention:**
- Articles older than 7 days with rank < 3 are auto-archived (soft delete: `is_archived = True`).
- Bookmarked (`save` feedback) and liked articles are exempt — never auto-archived.
- Archived articles hidden from all views but retained in DB for feedback history.
- Daemon runs cleanup after each fetch+score cycle.

**Interest-change re-scoring:**
- When interests undergo a **structural change** (topic added or removed, not just weight tweak), flag `needs_rescore = True` in `UserPreference`.
- Daemon checks the flag each cycle. If set: re-score articles from the last 7 days, then clear the flag.
- Not immediate — aligns with "save attention, not time". User sees updated results within one daemon cycle (≤1 hour).

---

## Phase 3: Wider Intake — AI Expands Its Listening Range

Now that the UX is interest-driven, source management becomes fully automatic. The system discovers and manages sources based on your interests — you never add a feed URL.

Architecture: Common `Source` interface in `src/sources/`, each source maps to the same articles table with a `source_type` field. Sources are provisioned and managed by the system, not the user.

### Phase 3A: Foundation + Easy Wins

The lowest-hanging fruit — free public APIs, no auth, no legal risk.

- **Source interface** (`src/sources/base.py`): base `Source` class with `fetch() -> list[Article]`, add `source_type` column to articles table, migrate existing RSS fetcher to implement the interface (#1 — planned)
- **Hacker News API** (`src/sources/hn.py`): HN Firebase API — free, no auth, richer than RSS (exact scores, comment counts). Top/new/best stories, dedup against existing RSS-sourced HN articles (#3 — planned)
- **Reddit** (`src/sources/reddit.py`): public JSON API (`reddit.com/r/{sub}/hot.json`) — no auth needed for public subreddits. Proper User-Agent header for rate limiting. Include upvotes/comments in summary for better AI scoring (#2 — planned)
- **Curated feed registry** (`src/feeds/registry.py`): topic keywords → high-quality RSS feeds, auto-add when interests are saved

### Phase 3B: GitHub Integration

Medium complexity, no legal risk. Official API with generous free tier.

- **GitHub releases** (`src/sources/github.py`): watch specific repos for new releases via GitHub API. Straightforward, `gh` CLI already authenticated (#5 — planned)
- **GitHub trending**: no stable official API — requires parsing the trending page or using unofficial endpoints. Lower priority than releases

### Phase 3C: Advanced Sources

Higher implementation complexity, but legally safe for personal use.

- **Web scraping** (`src/sources/web_scraper.py`): monitor pages for changes using `httpx` + `beautifulsoup4`. Needs diff storage, CSS selector config per site. Good for blog indexes, changelogs, release pages (#6 — planned)
- **Newsletters** (`src/sources/newsletter.py`): email-to-article parser. MVP: watch a local directory for `.eml` files. Advanced: IMAP polling. Challenge: every newsletter format (Substack, Mailchimp, Buttondown) has unique HTML templates (#7 — planned)

### Phase 3D: Deferred — Twitter/X

**Status: On hold** due to high cost and legal risk. (#4 — deferred)

- Twitter API v2 requires paid access ($100/mo minimum for Basic tier; search is Premium-only at $5000/mo)
- Scraping violates Twitter/X ToS — X Corp has filed lawsuits against scrapers
- Nitter instances are largely dead after Twitter blocked them
- RSS bridges are unreliable and frequently break
- **Decision**: revisit if API pricing changes or a viable alternative emerges. For now, Twitter content can be captured indirectly when other sources (HN, Reddit, blogs) link to tweets

### Feed Health (cross-cutting)

- Auto-disable stale sources, auto-discover replacements
- Implemented incrementally as sources are added

Goal: You state your interests once. The system figures out where to listen.

---

## Phase 4: Adaptive Intelligence — AI Understands You Deeply (#12 — Full Vision)

Building on Phase 2's feedback signals (already collecting data), the system develops a deep, nuanced understanding of your interests. This is the **full realization** of #12's interest profile vision — moving beyond simple weight adjustments to rich preference vectors.

**Living Interest Profiles** (#12):
- Migrate from `interests.yaml` to database-backed `interest_profiles` table
- Per-topic **preference vectors**: what subtopics excite you, what angles bore you, what depth you prefer, which sources you trust
- **Positive/negative signal patterns**: "user liked 12 articles matching `agent + code + autonomous`", "user disliked 8 matching `chatbot + customer service`"
- **AI-driven keyword expansion**: if you keep liking LangGraph articles, the system learns "LangGraph" without being told
- **Calibration, not overreaction**: exponential moving averages — one dislike doesn't nuke a topic

**Deep Analysis:**
- **Embedding-based similarity**: find hidden patterns in articles you liked — discover connections you didn't know you had
- **Interest clustering**: detect when your reading patterns suggest an entirely new interest area
- **A/B scoring**: test an evolved profile against the current one, measure which surfaces better content
- **Claude-mediated deep recalibration**: periodic review where Claude analyzes your full engagement history and suggests structural profile changes
- **Temporal patterns**: learn when you care about different topics (work topics on weekdays, side projects on weekends)

Goal: The system gets smarter every week. It knows you better than you know yourself.

---

## Phase 5: Active Discovery — AI Hunts For You

Shift from passive listening to active seeking. AI doesn't just filter what arrives — it goes out and finds what you need before you know you need it.

- Proactive web searches based on your interest profile
- Scheduled deep dives: "What's new in AI agents this week?"
- Source discovery: "Find blogs and researchers I should follow about X"
- Academic paper monitoring (arXiv, Semantic Scholar)
- Trend detection: spot emerging topics across all your sources
- High-significance alerts: push notification when something truly important happens

Goal: Information comes to you, not the other way around.

---

## Phase 6: Zero Touch — Complete Autonomy

The system runs itself. You do nothing. You only see the output: the highest-value information, perfectly curated, delivered when you need it.

- Scheduled fetching via Task Scheduler / cron
- Claude API for background scoring (no human-in-the-loop needed)
- Smart delivery: daily digest, real-time alerts, or weekly summary — AI picks the right cadence
- Push notifications (email, Telegram, mobile push) for high-priority content
- Auto-export to your knowledge base (Obsidian, Notion, Readwise)
- Self-monitoring: AI detects when sources go stale and suggests replacements

Goal: You open your dashboard or inbox and everything important is already there.

---

## Phase 7: Attention Network — Curated Streams for Everyone

Your curated intelligence becomes shareable. Other people can subscribe to your attention stream, and you can subscribe to theirs.

- Publish your curated feed as a public or private stream
- Subscribe to other people's AttentionOS streams
- Collaborative filtering: "People with similar interests also found this valuable"
- Team mode: shared interest profiles for organizations
- API for third-party integrations (Slack bots, Discord feeds, RSS re-export)

Goal: AttentionOS becomes a platform — not just personal curation, but a network of curated intelligence.

---

## Issue Tracker Cross-Reference

| Issue | Title | Status | Phase |
|-------|-------|--------|-------|
| #1 | Source interface: common abstraction | Planned | 3A |
| #2 | Reddit source | Planned | 3A |
| #3 | Hacker News API source | Planned | 3A |
| #4 | Twitter/X source | Deferred | 3D |
| #5 | GitHub source | Planned | 3B |
| #6 | Web scraping source | Planned | 3C |
| #7 | Newsletter source | Planned | 3C |
| #8 | Dashboard in-app controls | Done | 1 |
| #9 | Dashboard action bar | Done | 1 |
| #10 | Focus View: 3-article carousel | Open | 2 (Pillar 2) |
| #11 | Section-level focus: scroll sections | Open | 2 (Pillar 2) |
| #12 | Interest Profiles: learning engine | Open | 2 (Pillar 3) + 4 |
| #13 | AI Chatbox: natural language interface | Open | 2 (Pillar 1) |
