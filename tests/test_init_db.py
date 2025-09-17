import pytest

import scripts.init_db as init_db
from src.database import db_manager


@pytest.fixture(autouse=True)
def reset_db_manager():
    db_manager._GLOBAL_DB = None
    yield
    db_manager._GLOBAL_DB = None


def test_main_exits_when_table_missing(tmp_path, monkeypatch):
    duckdb_file = tmp_path / "test.duckdb"
    monkeypatch.setenv("DUCKDB_FALLBACK_PATH", str(duckdb_file))
    monkeypatch.delenv("DUCKDB_SQL_DUMP", raising=False)
    monkeypatch.delenv("SQL_FILE", raising=False)
    with pytest.raises(SystemExit):
        init_db.main()

