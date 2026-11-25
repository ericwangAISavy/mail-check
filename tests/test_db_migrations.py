"""Regression coverage for concurrent request-time schema upgrades."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3

from mailcheck import db
import pytest


@pytest.mark.parametrize('previous_version',[50,51])
def test_shared_workers_upgrade_supported_previous_versions(tmp_path,previous_version):
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'mail.db'
    with closing(db.connect(path)) as conn:
        db.add_account(conn,label='preserved',email='existing@example.test')
        conn.execute('DROP TABLE sourcing_match_evidence')
        conn.execute('DROP TABLE sourcing_posting_cache')
        conn.execute(f'PRAGMA user_version={previous_version}')
        conn.commit()
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    with bind_workspace(context),closing(db.connect()) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==db.SCHEMA_VERSION
        assert db.get_account(conn,'preserved').email=='existing@example.test'
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='sourcing_match_evidence'").fetchone()
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='sourcing_posting_cache'").fetchone()


def test_concurrent_shared_version_51_upgrade_preserves_accounts(tmp_path):
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'shared.db'
    with closing(db.connect(path)) as conn:
        db.add_account(conn,label='preserved',email='existing@example.test')
        conn.execute('DROP TABLE sourcing_match_evidence')
        conn.execute('DROP TABLE sourcing_posting_cache')
        conn.execute('PRAGMA user_version=51')
        conn.commit()
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    ready=Barrier(6)
    def open_shared(_):
        ready.wait(timeout=10)
        with bind_workspace(context),closing(db.connect()) as conn:
            assert conn.execute('PRAGMA user_version').fetchone()[0]==db.SCHEMA_VERSION
            assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0]==1
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(open_shared,range(6)))


@pytest.mark.parametrize('unsupported',[49,db.SCHEMA_VERSION+1])
def test_shared_workers_still_refuse_unsupported_schema_without_modifying_it(tmp_path,unsupported):
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'unsupported.db'
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('CREATE TABLE sentinel(value TEXT)')
        conn.execute("INSERT INTO sentinel VALUES('preserve')")
        conn.execute(f'PRAGMA user_version={unsupported}')
        conn.commit()
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    with bind_workspace(context),pytest.raises(RuntimeError,match='database schema'):
        db.connect()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==unsupported
        assert conn.execute('SELECT value FROM sentinel').fetchone()[0]=='preserve'


def test_non_shared_open_never_downgrades_a_future_database(tmp_path):
    path=tmp_path/'future.db'
    with closing(db.connect(path)) as conn:
        db.add_account(conn,label='future',email='future@example.test')
        conn.execute(f'PRAGMA user_version={db.SCHEMA_VERSION+1}');conn.commit()
    with pytest.raises(RuntimeError,match='schema'):
        db.connect(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==db.SCHEMA_VERSION+1
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0]==1


def test_new_shared_workspace_can_initialize_its_first_database(tmp_path):
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'new.db'
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    with bind_workspace(context),closing(db.connect()) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==db.SCHEMA_VERSION


def test_unsupported_database_appearing_during_creation_is_not_migrated(tmp_path,monkeypatch):
    from mailcheck import maintenance
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'appeared.db'
    connect=maintenance.connect_database
    def appeared(*args,**kwargs):
        with closing(sqlite3.connect(path)) as other:
            other.execute('CREATE TABLE sentinel(value TEXT)')
            other.execute("INSERT INTO sentinel VALUES('preserve')")
            other.execute('PRAGMA user_version=49');other.commit()
        return connect(*args,**kwargs)
    monkeypatch.setattr(maintenance,'connect_database',appeared)
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    with bind_workspace(context),pytest.raises(RuntimeError,match='schema'):
        db.connect()
    with closing(sqlite3.connect(path)) as other:
        assert other.execute('PRAGMA user_version').fetchone()[0]==49
        assert other.execute('SELECT value FROM sentinel').fetchone()[0]=='preserve'


@pytest.mark.parametrize('changed_version',[49,db.SCHEMA_VERSION+1])
def test_schema_rechecked_after_shared_preflight(tmp_path,monkeypatch,changed_version):
    from mailcheck import maintenance
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    path=tmp_path/'racing.db'
    db.connect(path).close()
    connect=maintenance.connect_database
    def changed(*args,**kwargs):
        with closing(sqlite3.connect(path)) as other:
            other.execute(f'PRAGMA user_version={changed_version}');other.commit()
        return connect(*args,**kwargs)
    monkeypatch.setattr(maintenance,'connect_database',changed)
    context=WorkspaceContext('legacy',None,tmp_path/'config.toml',path,tmp_path/'control')
    with bind_workspace(context),pytest.raises(RuntimeError,match='schema'):
        db.connect()
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==changed_version


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


def test_accounting_expression_indexes_upgrade_a_previous_release(tmp_path):
    path = tmp_path/'previous-release.db'
    with closing(db.connect(path)) as conn:
        conn.execute('DROP INDEX idx_check_activity_confirmed_day')
        conn.execute('DROP INDEX idx_native_rows_date')
        conn.execute('DROP INDEX idx_check_activity_message')
        conn.execute('PRAGMA user_version=38')
        conn.commit()
    with closing(db.connect(path)) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        plans = [row['detail'] for row in conn.execute("EXPLAIN QUERY PLAN SELECT row_id FROM sourcing_check_activity WHERE julianday(confirmed_at)>=julianday(?) AND julianday(confirmed_at)<julianday(?)",('2026-11-02','2026-11-09'))]
        assert any('idx_check_activity_confirmed_day' in plan for plan in plans)
        assert any(row['name']=='idx_native_rows_date' for row in conn.execute('PRAGMA index_list(native_rows)'))
        assert any(row['name']=='idx_check_activity_message' for row in conn.execute('PRAGMA index_list(sourcing_check_activity)'))
