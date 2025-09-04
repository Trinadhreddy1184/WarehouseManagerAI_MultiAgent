import scripts.init_db as init_db
from sqlalchemy import create_engine, text


def test_load_sql_from_s3_via_cp(monkeypatch):
    expected_sql = "SELECT 1;"

    def fake_run(cmd, *args, **kwargs):
        assert cmd == ["aws", "s3", "cp", "s3://bucket/key.sql", "-"]
        class Res:
            stdout = expected_sql
        return Res()

    monkeypatch.setenv("S3_BUCKET", "bucket")
    monkeypatch.setenv("S3_KEY", "key.sql")
    monkeypatch.setattr(init_db.subprocess, "run", fake_run)

    sql = init_db._load_sql()
    assert sql == expected_sql


def test_execute_sql_falls_back_to_sqlalchemy(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    db_url = f"sqlite:///{db_file}"
    sql = "CREATE TABLE foo (id INTEGER);"

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("psql not found")

    monkeypatch.setattr(init_db.subprocess, "run", fake_run)

    init_db._execute_sql(sql, db_url)

    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='foo'")
            )
            assert result.first() is not None
    finally:
        engine.dispose()
