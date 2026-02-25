"""Interest profile management: read, write, and detect structural changes."""

import json
from datetime import datetime, timezone

import yaml

from src.config import INTERESTS_PATH
from src.db.models import UserPreference
from src.db.session import get_session


def load_interests() -> dict:
    """Load user interests from YAML file."""
    if not INTERESTS_PATH.exists():
        return {"description": "", "topics": [], "exclude": []}
    with open(INTERESTS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"description": "", "topics": [], "exclude": []}


def save_interests(profile: dict) -> None:
    """Write interests.yaml and set needs_rescore flag if topics were added or removed.

    Weight-only or keyword-only changes do NOT trigger re-scoring — the rank
    formula handles those live.
    """
    # Load old profile to compare topic names
    old_profile = load_interests()
    old_names = {t["name"] for t in old_profile.get("topics", [])}
    new_names = {t["name"] for t in profile.get("topics", [])}

    # Write the new profile
    with open(INTERESTS_PATH, "w", encoding="utf-8") as f:
        yaml.dump(profile, f, allow_unicode=True, sort_keys=False)

    # Structural change = topic added or removed
    if old_names != new_names:
        _set_rescore_flag(True)


def _set_rescore_flag(value: bool) -> None:
    """Set or clear the needs_rescore flag in UserPreference."""
    session = get_session()
    try:
        pref = session.query(UserPreference).filter(UserPreference.key == "needs_rescore").first()
        flag_value = json.dumps("true" if value else "false")
        if pref is None:
            pref = UserPreference(key="needs_rescore", value=flag_value)
            session.add(pref)
        else:
            pref.value = flag_value
            pref.updated_at = datetime.now(timezone.utc)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
