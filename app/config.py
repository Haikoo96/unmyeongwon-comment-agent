from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
PROFILES_DIR = DATA_DIR / "profiles"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"

load_dotenv(ROOT / ".env")

with open(ROOT / "config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

CHANNELS = {c["id"]: c["name"] for c in CONFIG["channels"]}
TEST_VIDEOS = set(CONFIG.get("test_videos") or [])
PROFILES = CONFIG["profiles"]
COMMENT = CONFIG["comment"]
DAILY_MAX = CONFIG["limits"]["daily_max_comments"]
LLM = CONFIG["llm"]

for d in (DATA_DIR, PROFILES_DIR, SCREENSHOTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
