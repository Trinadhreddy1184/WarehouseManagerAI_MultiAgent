import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database.db_manager import DBManager


def test_connects_using_db_password(monkeypatch):
    """DBManager should honour DB_PASSWORD environment variable."""

    # Ensure compatibility variable is absent and DATABASE_URL not set
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_PASSWORD", "secret")

    mgr = DBManager()
    try:
        assert mgr.engine.url.password == "secret"
    finally:
        mgr.close()

