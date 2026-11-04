from mailcheck import db


def test_receipt_origin_and_copy_evidence_are_additive(tmp_path):
    with db.session(tmp_path / 'count.db') as conn:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(application_receipts)')}
        assert {'sender','duplicate_of','counting_evidence'} <= columns


def test_legacy_upgrade_backfills_origin_without_changing_mail_or_payments(tmp_path):
    from datetime import datetime
    from mailcheck.models import Classification, NormalizedMessage
    path=tmp_path/'legacy.db'
    conn=db.connect(path)
    account=db.add_account(conn,label='legacy',email='owner@example.test')
    message=NormalizedMessage(account_id=account,account_label='legacy',message_id='original',uid='1',folder='INBOX',
        from_addr='jobs-noreply@linkedin.com',from_name='',subject='Application received',
        date_utc=datetime(2026,11,4,18),body='We received your application.')
    pk=db.upsert_message(conn,message)
    db.save_classification(conn,pk,Classification(category='application_ack',company='Acme',role='Engineer'),'model','2')
    for column in ('sender','duplicate_of','counting_evidence'):
        conn.execute(f'ALTER TABLE application_receipts DROP COLUMN {column}')
    conn.execute('PRAGMA user_version=38');conn.commit();conn.close()
    with db.session(path) as upgraded:
        receipt=upgraded.execute('SELECT * FROM application_receipts').fetchone()
        assert receipt['sender']=='jobs-noreply@linkedin.com'
        assert receipt['category']=='application_ack'
        assert receipt['duplicate_of'] is None
        assert upgraded.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==1
        assert upgraded.execute('SELECT COUNT(*) FROM classifications').fetchone()[0]==1
