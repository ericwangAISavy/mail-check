"""Inbox marks describe saved checked-link proof, independently of Done."""
from datetime import datetime, timezone

from mailcheck import db, sourcing_activity
from mailcheck.models import Classification, NormalizedMessage
from tests import test_native_sourcing as sheets_fixture, test_frontend_api as mail_fixture


class TestApplicationMatchMarks:
    def setup_method(self):
        # unittest fixture cleanup is registered with this isolated host.
        self.host=sheets_fixture.NativeSheetTests()
        self.host.setUp()

    def teardown_method(self):
        self.host.doCleanups()

    def test_list_and_reader_use_checked_link_proof_not_email_done(self):
        host=self.host
        first=mail_fixture.FrontendApiTests.add_message(host,'matched',category='application_ack')
        second=mail_fixture.FrontendApiTests.add_message(host,'done-only',category='application_ack',done=True)
        base=host.snapshot()
        saved=host.native.append(host.conn,host.tab(),'job',base['revision'],[['Acme','Engineer','https://jobs.test/a']])
        rid=saved['row_ids'][1];column=saved['columns'][3]['id']
        host.conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?) ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value',(rid,column,'true'))
        message=host.conn.execute('SELECT message_id FROM messages WHERE id=?',(first,)).fetchone()[0]
        sourcing_activity.confirm(host.conn,rid,datetime.now(timezone.utc),message);host.conn.commit()
        def items():
            response=host.client.get('/api/triage?view=all&days=30')
            assert response.status_code==200,response.text
            return {m['pk']:m for group in response.json()['groups'] for m in group['items']}
        assert items()[first]['application_matched'] is True
        assert items()[second]['application_matched'] is False
        assert host.client.get(f'/api/messages/{first}').json()['message']['application_matched'] is True
        # A same message ID from a different mailbox cannot borrow the proof.
        other=db.add_account(host.conn,label='other-proof',email='other@example.test')
        other_pk=db.upsert_message(host.conn,NormalizedMessage(account_id=other,account_label='other-proof',message_id=message,uid='other',folder='INBOX',from_addr='hr@example.test',from_name='HR',subject='Application received',date_utc=datetime.now(timezone.utc),body='Thank you for applying.'))
        db.save_classification(host.conn,other_pk,Classification('application_ack',summary='Application received.'),'test','1');host.conn.commit()
        assert items()[other_pk]['application_matched'] is False
        # Reclassification or deleting the job removes the mark immediately.
        host.conn.execute("UPDATE classifications SET category='interview_invite' WHERE message_pk=?",(first,));host.conn.commit()
        assert items()[first]['application_matched'] is False
        host.conn.execute("UPDATE classifications SET category='application_ack' WHERE message_pk=?",(first,))
        host.conn.execute('DELETE FROM native_rows WHERE id=?',(rid,));host.conn.commit()
        assert items()[first]['application_matched'] is False
