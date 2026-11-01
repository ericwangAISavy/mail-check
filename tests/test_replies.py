"""Reply delivery is explicit, account-scoped and never retried after uncertainty."""
from unittest import TestCase
from unittest.mock import patch, MagicMock
import httpx
from tests import test_frontend_api as fixtures
from mailcheck import db, replies, outgoing
from mailcheck.models import NormalizedMessage, Classification
from tests.web_client import sign_in_bidder

class ReplyTests(TestCase):

    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
        self.conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?",(self.account_id,))
        self.pk = db.upsert_message(self.conn,NormalizedMessage(account_id=self.account_id,account_label='personal',
            message_id='<original@test>',uid='id/with+chars',folder='Inbox',from_addr='hr@example.test',
            from_name='HR',subject='Interview',body='Hello',date_utc=None))
        db.save_classification(self.conn,self.pk,Classification(category='info_request'),'test','1')
        self.conn.commit()
        self.client_id = patch.object(replies,'client_id',return_value='client'); self.client_id.start(); self.addCleanup(self.client_id.stop)
        self.token = patch.object(replies,'acquire_token',return_value='token'); self.token.start(); self.addCleanup(self.token.stop)
        self.calls=[]
        def handle(request):
            self.calls.append(request)
            if request.method=='GET': return httpx.Response(200,json={'id':'id/with+chars','internetMessageId':'<original@test>',
                'subject':'Interview','from':{'emailAddress':{'address':'hr@example.test'}},
                'replyTo':[{'emailAddress':{'address':'reply@example.test'}}],
                'toRecipients':[{'emailAddress':{'address':'me@example.test'}}]})
            return httpx.Response(202)
        self.transport = httpx.MockTransport(handle)
        real_client = httpx.Client
        active = patch.object(replies,'graph_client',side_effect=lambda token:real_client(transport=self.transport)); active.start(); self.addCleanup(active.stop)

    def payload(self):
        return {'operation':'b7313a76-5bb1-4d34-8c14-05f544047401','body':'Thank you. Monday works.','mode':'reply','mark_done':True}

    def test_reply_uses_original_account_and_graph_thread_and_is_idempotent(self):
        context=self.client.get(f'/api/messages/{self.pk}/reply').json()
        self.assertEqual(context['from'],'me@example.test')
        self.assertEqual(context['to'],['reply@example.test'])
        url=f'/api/messages/{self.pk}/reply'
        first=self.client.post(url,json=self.payload()); self.assertEqual(first.status_code,200,first.text)
        second=self.client.post(url,json=self.payload()); self.assertEqual(second.status_code,200,second.text)
        posts=[r for r in self.calls if r.method=='POST']
        self.assertEqual(len(posts),1)
        self.assertIn('id%2Fwith%2Bchars/reply',str(posts[0].url))
        self.assertIn(b'Thank you. Monday works.',posts[0].content)
        self.assertTrue(db.get_message(self.conn,self.pk)['handled_at'])
        reader=self.client.get(f'/api/messages/{self.pk}').json()
        self.assertEqual(reader['replies'][0]['body'],'Thank you. Monday works.')
        self.assertEqual(reader['replies'][0]['status'],'sent')
        changed=self.payload(); changed['body']='Different'
        self.assertEqual(self.client.post(url,json=changed).status_code,409)

    def test_transport_timeout_is_not_retried_and_does_not_mark_done(self):
        def fail(request):
            if request.method=='POST': raise httpx.ReadTimeout('timeout',request=request)
            return httpx.Response(200,json={'id':'id/with+chars','internetMessageId':'<original@test>','subject':'Interview','from':{'emailAddress':{'address':'hr@example.test'}}})
        self.transport=httpx.MockTransport(fail)
        url=f'/api/messages/{self.pk}/reply'
        response=self.client.post(url,json=self.payload()); self.assertEqual(response.status_code,409,response.text)
        self.assertIn('not confirmed',response.json()['error'])
        self.assertIsNone(db.get_message(self.conn,self.pk)['handled_at'])
        self.assertEqual(self.client.post(url,json=self.payload()).status_code,409)

    def test_read_only_user_and_unconfigured_imap_accounts_cannot_send(self):
        self.conn.execute("UPDATE accounts SET provider='imap'"); self.conn.commit()
        self.assertEqual(self.client.post(f'/api/messages/{self.pk}/reply',json=self.payload()).status_code,409)
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Bidder','2026-01-01')"); self.conn.commit()
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post(f'/api/messages/{self.pk}/reply',json=self.payload()).status_code,403)


    def test_imap_smtp_reply_uses_reply_to_and_real_thread_headers(self):
        self.conn.execute("UPDATE accounts SET provider='imap'")
        self.conn.execute("INSERT INTO mail_outgoing VALUES(?, 'smtp.test',587,'starttls','me@example.test')",(self.account_id,))
        self.conn.commit()
        box=MagicMock()
        item=MagicMock()
        self.conn.execute("UPDATE messages SET uid='123' WHERE id=?",(self.pk,));self.conn.commit()
        item.headers={'message-id':['<original@test>'],'reply-to':['Recruiter <reply@example.test>'],
            'to':['me@example.test'],'cc':['Other <other@example.test>'],'references':['<earlier@test>']}
        box.fetch.return_value=[item]
        smtp=MagicMock();smtp.__enter__.return_value=smtp;smtp.send_message.return_value={};smtp.close.side_effect=OSError("already closed")
        payload=self.payload();payload['mode']='reply_all'
        with patch.object(outgoing.secrets,'get_account_password',return_value='password'),patch.object(outgoing.IMAPSource,'_open',return_value=box),patch.object(outgoing,'open_smtp',return_value=smtp):
            response=self.client.post(f'/api/messages/{self.pk}/reply',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        mail=smtp.send_message.call_args.args[0]
        self.assertEqual(str(mail['To']),'reply@example.test')
        self.assertEqual(str(mail['Cc']),'other@example.test')
        self.assertEqual(str(mail['In-Reply-To']),'<original@test>')
        self.assertIn('<earlier@test>',str(mail['References']))
        self.assertEqual(smtp.send_message.call_args.kwargs['from_addr'],'me@example.test')
        box.fetch.assert_called_once_with('UID 123',headers_only=True,mark_seen=False,limit=1)

    def test_smtp_settings_require_tls_and_test_login_without_sending(self):
        self.conn.execute("UPDATE accounts SET provider='imap'");self.conn.commit()
        values={'host':'smtp.example.test','port':587,'security':'starttls','username':'me@example.test'}
        smtp=MagicMock()
        with patch.object(outgoing,'open_smtp',return_value=smtp):
            response=self.client.post('/api/accounts/personal/outgoing',json=values)
        self.assertEqual(response.status_code,200,response.text)
        smtp.send_message.assert_not_called()
        self.assertTrue(self.client.get('/api/accounts/personal/outgoing').json()['configured'])
        values['security']='none'
        self.assertEqual(self.client.post('/api/accounts/personal/outgoing',json=values).status_code,422)


    def test_smtp_upgrades_to_tls_before_authentication(self):
        server=MagicMock()
        with patch.object(outgoing.secrets,'get_account_password',return_value='secret'),patch.object(outgoing.smtplib,'SMTP',return_value=server):
            self.assertIs(outgoing.open_smtp('personal',{'host':'smtp.test','port':587,'security':'starttls','username':'me@example.test'}),server)
        self.assertEqual([call[0] for call in server.method_calls],['starttls','login'])


    def test_retention_cannot_attach_sent_history_to_a_reused_message_number(self):
        self.assertEqual(self.client.post(f'/api/messages/{self.pk}/reply',json=self.payload()).status_code,200)
        self.conn.execute("UPDATE messages SET message_id='<a-different-message@test>' WHERE id=?",(self.pk,));self.conn.commit()
        self.assertEqual(self.client.get(f'/api/messages/{self.pk}').json()['replies'],[])
        self.assertEqual(self.client.post(f'/api/messages/{self.pk}/reply',json=self.payload()).status_code,409)

    def test_imap_missing_message_id_does_not_reply_to_a_reused_uid(self):
        self.conn.execute("UPDATE accounts SET provider='imap'")
        self.conn.execute("UPDATE messages SET uid='123' WHERE id=?",(self.pk,));self.conn.commit()
        row=replies.account_message(self.conn,self.pk)
        box=MagicMock();item=MagicMock();item.headers={'reply-to':['wrong@example.test']};box.fetch.return_value=[item]
        with patch.object(outgoing.secrets,'get_account_password',return_value='password'),patch.object(outgoing.IMAPSource,'_open',return_value=box):
            with self.assertRaisesRegex(outgoing.OutgoingError,'identifier changed'):
                outgoing.metadata(row)
