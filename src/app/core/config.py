"""Application configuration helpers – reads from settings table in SQLite."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Default project root
if getattr(sys, "frozen", False):
    # Running as PyInstaller bundle – .exe lives next to data/
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "leads.db"

DEFAULTS = {
    "language": "en",
    "score_quota": 50,
    "top_n_for_scoring": 50,
    "dry_run": False,
    "mock_run": False,
    "active_provider": "gemini",
    "db_path": str(DB_PATH),
}


def get_setting(con, key: str, default=None):
    row = con.execute(
        "SELECT value_json FROM settings WHERE key=?", (key,)
    ).fetchone()
    if row:
        return json.loads(row[0])
    return default if default is not None else DEFAULTS.get(key)


def set_setting(con, key: str, value):
    con.execute(
        """INSERT INTO settings (key, value_json)
           VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json""",
        (key, json.dumps(value)),
    )
    con.commit()


def get_all_settings(con) -> dict:
    rows = con.execute("SELECT key, value_json FROM settings").fetchall()
    result = dict(DEFAULTS)
    for k, v in rows:
        try:
            result[k] = json.loads(v)
        except Exception:
            result[k] = v
    return result
