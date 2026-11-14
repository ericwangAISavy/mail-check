from mailcheck import db


def test_existing_v49_database_gets_business_triggers_and_coalesced_hints(tmp_path):
    path=tmp_path/'prior.db'
    old=db.connect(path)
    old.execute('DROP TRIGGER IF EXISTS realtime_native_cells_insert')
    old.execute('DROP INDEX IF EXISTS realtime_outbox_topic')
    old.execute("INSERT INTO realtime_outbox(topic) VALUES('sourcing')")
    old.execute("INSERT INTO realtime_outbox(topic) VALUES('sourcing')")
    old.execute('PRAGMA user_version=49')
    old.commit();old.close()
    upgraded=db.connect(path)
    try:
        assert upgraded.execute('PRAGMA user_version').fetchone()[0]>=50
        assert upgraded.execute("SELECT COUNT(*) FROM realtime_outbox WHERE topic='sourcing'").fetchone()[0]==1
        assert upgraded.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='realtime_native_cells_insert'").fetchone()
    finally:upgraded.close()
