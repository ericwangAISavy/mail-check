"""Regression coverage for concurrent request-time schema upgrades."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from mailcheck import db


def test_migration_holds_write_transaction(tmp_path, monkeypatch):
    migrate = db._migrate

    def checked_migrate(conn):
        assert conn.in_transaction
        migrate(conn)
        assert conn.in_transaction

    monkeypatch.setattr(db, "_migrate", checked_migrate)
    db.connect(tmp_path / "mail.db").close()


def test_concurrent_upgrade_preserves_data(tmp_path):
    path = tmp_path / "mail.db"
    with db.session(path) as conn:
        db.add_account(conn, label="existing", email="test@example.com")
        conn.execute("ALTER TABLE messages DROP COLUMN web_notified")
        conn.execute("PRAGMA user_version = 0")

    ready = Barrier(8)

    def open_database(_):
        ready.wait(timeout=10)
        with db.session(path) as conn:
            assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
            assert db.get_account(conn, "existing").email == "test@example.com"
            assert "web_notified" in {
                row["name"] for row in conn.execute("PRAGMA table_info(messages)")
            }

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(open_database, range(8)))
