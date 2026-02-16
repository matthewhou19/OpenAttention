from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "rss.db"
DB_URL = f"sqlite:///{DB_PATH}"
INTERESTS_PATH = PROJECT_ROOT / "interests.yaml"

# Ensure data directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
