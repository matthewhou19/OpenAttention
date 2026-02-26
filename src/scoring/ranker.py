"""Composite ranker for AttentionOS (Issue #7).

Formula:
    composite = (relevance × max_topic_weight / 10) + (significance × 0.3) + recency_bonus
    recency_bonus = 2 × exp(-age_hours / 48)

Read articles get rank × 0.3.
Multi-topic articles use the highest matching topic weight.
If no topic matches, max_topic_weight defaults to 1.0 (floor).
"""

import math
from datetime import datetime, timezone

from src.db.models import Article, Score


def compute_rank(article: Article, score: Score, interests: dict) -> float:
    """Compute composite rank for an article given its score and user interests."""
    max_weight = max_topic_weight(score.topics_list, interests)

    relevance_component = score.relevance * max_weight / 10
    significance_component = score.significance * 0.3
    recency_bonus = _recency_bonus(article)

    rank = relevance_component + significance_component + recency_bonus

    if article.is_read:
        rank *= 0.3

    return rank


def max_topic_weight(score_topics: list[str], interests: dict) -> float:
    """Find the highest matching topic weight from interests. Floor = 1.0."""
    if not score_topics:
        return 1.0

    interest_topics = interests.get("topics", [])
    if not interest_topics:
        return 1.0

    max_weight = 0.0
    score_topics_lower = [t.lower() for t in score_topics]

    for topic in interest_topics:
        name_lower = topic.get("name", "").lower()
        keywords_lower = [k.lower() for k in topic.get("keywords", [])]
        weight = topic.get("weight", 1.0)

        for st in score_topics_lower:
            if st == name_lower or name_lower in st or st in name_lower:
                max_weight = max(max_weight, weight)
                break
            if any(kw in st or st in kw for kw in keywords_lower):
                max_weight = max(max_weight, weight)
                break

    return max_weight if max_weight > 0 else 1.0


def _recency_bonus(article: Article) -> float:
    """Calculate recency bonus: 2 × exp(-age_hours / 48)."""
    now = datetime.now(timezone.utc)
    published = article.published_at or article.fetched_at
    if published is None:
        return 2.0  # No date info — treat as fresh

    # Ensure timezone-aware comparison
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    age_hours = max((now - published).total_seconds() / 3600, 0)
    return 2 * math.exp(-age_hours / 48)
