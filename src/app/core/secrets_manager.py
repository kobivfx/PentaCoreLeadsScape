"""Secure secrets management using Windows Credential Manager (keyring)
with fallback to Fernet encryption tied to the local machine."""
from __future__ import annotations

import base64
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE_NAME = "LeadsScraper2"

# ---------------------------------------------------------------------------
# Try keyring first, fall back to local Fernet encryption
# ---------------------------------------------------------------------------
_USE_KEYRING = False
try:
    import keyring
    # Smoke test – if no backend is configured this raises
    keyring.get_credential(SERVICE_NAME, "___probe___")
    _USE_KEYRING = True
except Exception:
    pass

_fernet = None

def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    try:
        from cryptography.fernet import Fernet
        key_path = Path(__file__).resolve().parents[3] / "data" / ".secret_key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            key_path.write_bytes(key)
            # Try to hide the file on Windows
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(key_path), 0x02)
            except Exception:
                pass
        _fernet = Fernet(key)
        return _fernet
    except ImportError:
        return None


class SecretsManager:
    """Read/write secrets, persisting references in the secrets table."""

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._ensure_table()

    # ------------------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _ensure_table(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS secrets (
                    key TEXT PRIMARY KEY,
                    encrypted_value TEXT DEFAULT '',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)

    # ------------------------------------------------------------------
    def set_secret(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        encrypted = ""

        if _USE_KEYRING:
            try:
                keyring.set_password(SERVICE_NAME, key, value)
                encrypted = "__keyring__"
            except Exception as exc:
                log.warning("keyring.set_password failed: %s – falling back", exc)

        if encrypted != "__keyring__":
            f = _get_fernet()
            if f:
                encrypted = f.encrypt(value.encode()).decode()
            else:
                log.error("No encryption backend available; storing obfuscated.")
                encrypted = base64.b64encode(value.encode()).decode()

        with self._conn() as con:
            con.execute(
                """INSERT INTO secrets (key, encrypted_value, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET encrypted_value=excluded.encrypted_value,
                                                  updated_at=excluded.updated_at""",
                (key, encrypted, now, now),
            )

    def get_secret(self, key: str) -> str | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT encrypted_value FROM secrets WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        enc = row[0]

        if enc == "__keyring__":
            if _USE_KEYRING:
                try:
                    return keyring.get_password(SERVICE_NAME, key)
                except Exception:
                    pass
            return None

        f = _get_fernet()
        if f and enc:
            try:
                return f.decrypt(enc.encode()).decode()
            except Exception:
                pass

        # Fallback: try base64
        try:
            return base64.b64decode(enc.encode()).decode()
        except Exception:
            return None

    def delete_secret(self, key: str) -> None:
        if _USE_KEYRING:
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except Exception:
                pass
        with self._conn() as con:
            con.execute("DELETE FROM secrets WHERE key=?", (key,))

    def list_keys(self) -> list[str]:
        with self._conn() as con:
            rows = con.execute("SELECT key FROM secrets ORDER BY key").fetchall()
        return [r[0] for r in rows]

    def has_secret(self, key: str) -> bool:
        """Check if a secret exists."""
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM secrets WHERE key=?", (key,)
            ).fetchone()
        return row is not None

    # ─────────────────────────────────────────────────────────────
    # Apify token management (multi-token support)
    # ─────────────────────────────────────────────────────────────

    def get_apify_tokens(self) -> list[str]:
        """Get list of Apify API tokens."""
        tokens_json = self.get_secret("apify_tokens")
        if tokens_json:
            try:
                return json.loads(tokens_json)
            except (json.JSONDecodeError, TypeError):
                pass
        # Fallback: check for legacy single token
        legacy_token = self.get_secret("apify_token")
        if legacy_token:
            return [legacy_token]
        return []

    def add_apify_token(self, token: str) -> None:
        """Add an Apify token to the list. Avoids duplicates."""
        if not token or not token.strip():
            return
        token = token.strip()
        tokens = self.get_apify_tokens()
        if token not in tokens:
            tokens.append(token)
            self.set_secret("apify_tokens", json.dumps(tokens))

    def remove_apify_token(self, token: str) -> None:
        """Remove an Apify token from the list."""
        tokens = self.get_apify_tokens()
        tokens = [t for t in tokens if t != token]
        if tokens:
            self.set_secret("apify_tokens", json.dumps(tokens))
        else:
            # Remove entirely if no tokens left
            self.delete_secret("apify_tokens")
            # Also clear legacy token
            if self.get_secret("apify_token"):
                self.delete_secret("apify_token")

    def set_apify_tokens(self, tokens: list[str]) -> None:
        """Set the entire list of Apify tokens."""
        if tokens:
            self.set_secret("apify_tokens", json.dumps(tokens))
        else:
            self.delete_secret("apify_tokens")

    def has_secret(self, key: str) -> bool:
        return self.get_secret(key) is not None
