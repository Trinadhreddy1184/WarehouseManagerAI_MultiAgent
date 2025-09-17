import pytest

import scripts.init_db as init_db
from src.database import db_manager


@pytest.fixture(autouse=True)
def reset_db_manager():
    db_manager._GLOBAL_DB = None
    yield
    db_manager._GLOBAL_DB = None


def test_main_exits_when_table_missing(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    with pytest.raises(SystemExit):
        init_db.main()

