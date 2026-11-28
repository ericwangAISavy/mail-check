from concurrent.futures import ThreadPoolExecutor
from tests.test_workspace_gateway import system


def test_control_write_does_not_block_existing_session_reads(system):
    _,store,_=system
    with ThreadPoolExecutor(max_workers=1) as executor,store.connect() as writer:
        writer.execute('BEGIN EXCLUSIVE')
        writer.execute('UPDATE users SET enabled=0 WHERE owner=1')
        future=executor.submit(store.identity,store.owner_token)
        try:
            assert future.result(timeout=.3)['is_owner'] is True
            writer.commit()
            assert store.identity(store.owner_token) is None
        finally:writer.rollback()
