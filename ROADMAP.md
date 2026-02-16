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
- [x] Notion export (optional)
- [x] GitHub repo: [AttentionOS](https://github.com/matthewhou19/AttentionOS)

---

## Phase 2: Wider Intake — AI Listens Everywhere

Right now AI only listens to RSS feeds. But valuable information lives everywhere. This phase makes AI monitor all the channels you'd normally have to check yourself.

- **Reddit**: Subscribe to subreddits, AI filters signal from noise
- **Hacker News**: HN API — top/new/best stories, automatically scored
- **Twitter/X**: Keyword monitoring, follow key voices without the timeline
- **GitHub**: Trending repos, release notifications for projects you use
- **Web scraping**: Monitor specific pages for changes (blog indexes, changelog pages)
- **Newsletters**: Email-to-article parser — forward newsletters, AI extracts and scores

Architecture: Common `Source` interface in `src/sources/`, each source maps to the same articles table with a `source_type` field. You never need to check these platforms yourself.

---

## Phase 3: Adaptive Intelligence — AI Learns What You Value

The system observes what you engage with and evolves its understanding of your interests. You never have to manually tune settings again.

- Analyze feedback patterns (like/dislike/save) to detect shifting interests
- Claude Code reviews your engagement: "You've been reading more about infrastructure lately — should I increase that weight?"
- Auto-update `interests.yaml` and `sections.yaml` based on observed behavior
- Embedding-based similarity: find hidden patterns in articles you liked
- A/B scoring: test evolved profile vs current, measure improvement
- New sections emerge organically when AI detects a new interest cluster

Goal: The system gets smarter every week without you touching any config.

---

## Phase 4: Active Discovery — AI Hunts For You

Shift from passive listening to active seeking. AI doesn't just filter what arrives — it goes out and finds what you need before you know you need it.

- Proactive web searches based on your interest profile
- Scheduled deep dives: "What's new in AI agents this week?"
- Source discovery: "Find blogs and researchers I should follow about X"
- Academic paper monitoring (arXiv, Semantic Scholar)
- Trend detection: spot emerging topics across all your sources
- High-significance alerts: push notification when something truly important happens

Goal: Information comes to you, not the other way around.

---

## Phase 5: Zero Touch — Complete Autonomy

The system runs itself. You do nothing. You only see the output: the highest-value information, perfectly curated, delivered when you need it.

- Scheduled fetching via Task Scheduler / cron
- Claude API for background scoring (no human-in-the-loop needed)
- Smart delivery: daily digest, real-time alerts, or weekly summary — AI picks the right cadence
- Push notifications (email, Telegram, mobile push) for high-priority content
- Auto-export to your knowledge base (Obsidian, Notion, Readwise)
- Self-monitoring: AI detects when sources go stale and suggests replacements

Goal: You open your dashboard or inbox and everything important is already there.

---

## Phase 6: Attention Network — Curated Streams for Everyone

Your curated intelligence becomes shareable. Other people can subscribe to your attention stream, and you can subscribe to theirs.

- Publish your curated feed as a public or private stream
- Subscribe to other people's AttentionOS streams
- Collaborative filtering: "People with similar interests also found this valuable"
- Team mode: shared interest profiles for organizations
- API for third-party integrations (Slack bots, Discord feeds, RSS re-export)

Goal: AttentionOS becomes a platform — not just personal curation, but a network of curated intelligence.
