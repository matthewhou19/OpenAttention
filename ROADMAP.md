# AI RSS - Roadmap

This file persists the future development plan across conversations.

## Current: Phase 1 - Core Pipeline (MVP)
- [x] Project setup
- [x] Database layer (SQLite + SQLAlchemy)
- [x] Feed management CLI (add/remove/list)
- [x] Article fetcher (RSS parsing, dedup)
- [x] Scoring system (prepare for Claude Code, write-back)
- [x] FastAPI API server
- [x] Claude Code slash command (/check-feeds)
- [ ] Full self-test (Stage 2)
- [ ] Content experience layer (Stage 3: dashboard / Obsidian / Notion)

---

## Phase 2: Additional Sources

Add content collectors beyond RSS:

- **Reddit**: PRAW library, subscribe to subreddits, store as articles
- **Hacker News**: HN API (no auth needed), fetch top/new/best stories
- **Twitter/X**: Nitter scraping or API, keyword monitoring
- **GitHub**: Trending repos, release notifications via API
- **Web scraping**: Monitor specific pages for changes (e.g., blog indexes)

Architecture: Each source gets its own collector in `src/sources/` with a common interface:
```python
class Source:
    async def fetch_new() -> list[Article]
```
Add `source_type` field to articles table to distinguish sources.

---

## Phase 3: Learning Loop

- Track feedback (like/dislike/save/skip) on scored articles
- Periodically analyze feedback patterns to update `interests.yaml`
- Claude Code reviews feedback: "Based on what you liked/disliked, I suggest updating your interests..."
- Embedding-based similarity: store article embeddings (pgvector), find patterns in liked articles
- A/B testing: score some articles with old profile vs new, measure accuracy
- Goal: interests.yaml evolves automatically over time

---

## Phase 4: Active Search

- Claude Code proactively searches the web based on interests
- Scheduled topic searches ("what's new in LLM agents this week?")
- New source discovery ("find blogs I should follow about X")
- arXiv/academic paper monitoring (arXiv RSS + semantic filtering)
- High-significance content alerts
- Goal: system finds content you didn't know to look for

---

## Phase 5: Automation

- Scheduled fetching via Windows Task Scheduler / cron
- Replace Claude Code scoring with Claude API calls for background processing
- Push notifications for high-priority content (email, Telegram, etc.)
- Auto-export to Obsidian/Notion
- Goal: system runs fully autonomously, only surfaces what matters
