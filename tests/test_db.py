from coverage_service import db


def test_schema_has_tables(tmp_path):
    conn = db.connect(str(tmp_path / "c.db"))
    db.init_schema(conn)
    names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"units", "evidence"} <= names
    assert conn.execute("pragma journal_mode").fetchone()[0].lower() == "wal"
