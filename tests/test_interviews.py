"""Interview discovery/reconciliation uses real local SQLite and provider messages."""
from __future__ import annotations
from tests.web_client import sign_in_bidder
import base64
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email import message_from_string
from pathlib import Path
from unittest.mock import patch

from mailcheck import config, db, interviews, normalize, pipeline
from mailcheck.models import Classification, NormalizedMessage, RawMessage
from mailcheck.sources.imap import _to_raw as imap_raw
from mailcheck.sources.outlook import _to_raw as graph_raw
from mailcheck.interview_metadata import imap_calendars
from tests.web_client import TestClient
from mailcheck.web import app as web


class Model:
    def __init__(self, **overrides):
        self.data = dict(is_interview_event=True,event_type="scheduled",company="Acme",role="Engineer",stage="Technical Interview",start_time="2026-10-18T10:30:00-05:00",end_time="2026-10-18T11:30:00-05:00",timezone="America/Chicago",confidence=.95)
        self.data.update(overrides)
    def complete(self, *args, **kwargs): return json.dumps(self.data)
    def close(self): pass


def ics(uid="invite-1", sequence=0, start="20261018T153000Z", end="20261018T163000Z", status="CONFIRMED", method="REQUEST", extra=""):
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nMETHOD:{method}\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nSEQUENCE:{sequence}\r\nDTSTAMP:20261015T120000Z\r\nDTSTART:{start}\r\nDTEND:{end}\r\nSUMMARY:Acme Technical Interview\r\nDESCRIPTION:Join https://zoom.us/j/12345\r\nLOCATION:Remote\r\nORGANIZER;CN=Recruiter:mailto:recruiter@acme.test\r\nATTENDEE:mailto:candidate@example.test\r\nSTATUS:{status}\r\n{extra}END:VEVENT\r\nEND:VCALENDAR\r\n"


class InterviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"mail.db"
        self.conn=db.connect(self.path);self.addCleanup(self.conn.close)
        self.a=db.add_account(self.conn,label="work",email="work@example.test")
        self.b=db.add_account(self.conn,label="personal",email="personal@example.test")
        self.n=0
    def message(self, **kwargs):
        self.n+=1
        defaults=dict(account_id=self.a,account_label="work",message_id=f"<m{self.n}@acme.test>",uid=str(self.n),folder="INBOX",from_addr="recruiter@acme.test",from_name="Recruiter",subject="Technical Interview Confirmation",date_utc=datetime(2026,10,15,12),body="Your Acme technical interview is confirmed. Join https://zoom.us/j/12345",thread_id="thread-1")
        defaults.update(kwargs)
        msg=NormalizedMessage(**defaults);pk=db.upsert_message(self.conn,msg)
        db.save_classification(self.conn,pk,Classification(category="interview_invite",company="Acme",role="Engineer"),"test","1")
        return pk,msg
    def process(self, pk, model=None, **kwargs):
        return interviews.process_message(self.conn,pk,{"category":"interview_invite","company":"Acme","role":"Engineer"},client=model,**kwargs)
    def events(self): return [dict(r) for r in self.conn.execute("SELECT * FROM interview_events ORDER BY id")]
    def test_normal_invitation_and_source_trace(self):
        pk,_=self.message();changes=self.process(pk,Model())
        self.assertEqual(len(changes),1);event=self.events()[0]
        self.assertEqual(event["start_at"],"2026-10-18T15:30:00+00:00")
        self.assertEqual(event["needs_review"],0)
        self.assertEqual(interviews.event_sources(self.conn,event["id"])[0]["message_pk"],pk)
    def test_ics_precedes_model_and_parses_metadata(self):
        pk,_=self.message(calendar_data=[ics()])
        model=Model(start_time="2026-10-01T01:00:00Z")
        with patch.object(model,"complete",side_effect=AssertionError("ICS must not call model")):
            self.process(pk,model)
        event=self.events()[0]
        self.assertEqual(event["calendar_uid"],"invite-1")
        self.assertEqual(event["start_at"],"2026-10-18T15:30:00+00:00")
        self.assertEqual(event["organizer_email"],"recruiter@acme.test")
        self.assertEqual(json.loads(event["participants"]),["candidate@example.test"])
    def test_zoom_teams_meet_and_generic_https_links(self):
        for url,platform in (("https://zoom.us/j/123","Zoom"),("https://teams.microsoft.com/l/meetup-join/ABC","Microsoft Teams"),("https://meet.google.com/abc-defg-hij","Google Meet"),("https://example.webex.com/meet/a","Webex"),("https://chime.aws/123","Amazon Chime")):
            with self.subTest(platform=platform):
                pk,_=self.message(thread_id=url,body=f"Interview confirmed {url}")
                self.process(pk,Model(start_time=f"2026-11-{self.n+1:02}T10:00:00Z"))
                self.assertEqual(self.events()[-1]["meeting_platform"],platform)
                self.assertEqual(self.events()[-1]["meeting_url"],url)
        self.assertIsNone(interviews.safe_url("javascript:alert(1)"))
        self.assertIsNone(interviews.safe_url("https://user:pass@host.test"))
    def test_automatic_lifecycle_same_event(self):
        pk,_=self.message();self.process(pk,Model())
        original=self.events()[0]["id"]
        pk,_=self.message(subject="Your interview has been rescheduled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="rescheduled",start_time="2026-10-20T14:00:00-05:00",end_time="2026-10-20T15:00:00-05:00"))
        pk,_=self.message(subject="Interview cancelled",date_utc=datetime(2026,10,17,12))
        self.process(pk,Model(event_type="cancelled",start_time=None,end_time=None))
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.events()[0]["id"],original)
        self.assertEqual(self.events()[0]["status"],"Cancelled")
        self.assertEqual(self.events()[0]["start_at"],"2026-10-20T19:00:00+00:00")
    def test_duplicate_confirmation_and_incremental_scan(self):
        pk,_=self.message();self.process(pk,Model());self.assertEqual(self.process(pk,Model()),[])
        pk,_=self.message(message_id="<confirmation@acme.test>",thread_id=None)
        self.process(pk,Model());self.assertEqual(len(self.events()),1)
    def test_uid_cross_account_dedup_and_filter(self):
        pk,_=self.message(calendar_data=[ics()]);self.process(pk)
        pk,_=self.message(account_id=self.b,account_label="personal",calendar_data=[ics()]);self.process(pk)
        self.assertEqual(len(self.events()),1)
        self.assertEqual(len(interviews.list_events(self.conn,account="personal")),1)
        self.assertEqual(len(interviews.event_sources(self.conn,1)),2)
        db.set_account_enabled(self.conn,"work",False)
        self.assertEqual(len(interviews.list_events(self.conn)),1)
        db.set_account_enabled(self.conn,"personal",False)
        self.assertEqual(len(interviews.list_events(self.conn)),0)
    def test_distinct_ics_uids_never_collapse(self):
        for uid in ("one","two"):
            pk,_=self.message(calendar_data=[ics(uid)]);self.process(pk)
        self.assertEqual(len(self.events()),2)
    def test_sequence_stale_update_does_not_revert_reschedule_or_cancel(self):
        for sequence,start,end,status in ((0,"20261018T153000Z","20261018T163000Z","CONFIRMED"),(2,"20261020T190000Z","20261020T200000Z","CONFIRMED"),(1,"20261019T190000Z","20261019T200000Z","CONFIRMED"),(3,"20261020T190000Z","20261020T200000Z","CANCELLED")):
            pk,_=self.message(calendar_data=[ics(sequence=sequence,start=start,end=end,status=status)])
            self.process(pk)
        event=self.events()[0]
        self.assertEqual(len(self.events()),1)
        self.assertEqual(event["start_at"],"2026-10-20T19:00:00+00:00")
        self.assertEqual(event["status"],"Cancelled")
        self.assertEqual(event["sequence"],3)
    def test_ambiguous_schedule_and_dst_need_review(self):
        pk,_=self.message();self.process(pk,Model(start_time="2026-11-01T01:30:00",end_time=None,ambiguous=True))
        event=self.events()[0]
        self.assertEqual(event["needs_review"],1);self.assertIsNone(event["start_at"])
        self.assertEqual(interviews.display_event(event)["display_status"],"Needs review")
    def test_manual_correction_preserved(self):
        pk,_=self.message(calendar_data=[ics()]);self.process(pk)
        interviews.correct_event(self.conn,1,{"company":"Correct Company","start_at":"2026-10-22T10:00:00","timezone":"America/Chicago","end_at":"2026-10-22T11:00:00","status":"Scheduled","needs_review":False})
        pk,_=self.message(calendar_data=[ics(sequence=2,start="20261020T190000Z",end="20261020T200000Z")]);self.process(pk)
        event=self.events()[0]
        self.assertEqual(event["company"],"Correct Company")
        self.assertEqual(event["start_at"],"2026-10-22T15:00:00+00:00")
        self.assertEqual(event["status"],"Scheduled")
        self.assertFalse(event["needs_review"])
    def test_past_completed_display_keeps_detected_status(self):
        pk,_=self.message();self.process(pk,Model(start_time="2020-01-01T10:00:00Z",end_time="2020-01-01T11:00:00Z"))
        event=self.events()[0]
        self.assertEqual(event["status"],"Scheduled")
        self.assertEqual(interviews.display_event(event)["display_status"],"Completed")
    def test_unrelated_message_and_unrelated_ics(self):
        pk,_=self.message(subject="Your invoice",body="Invoice attached",calendar_data=[])
        self.assertEqual(interviews.process_message(self.conn,pk,{"category":"other","company":None}),[])
        self.assertEqual(len(self.events()),0)
    def test_model_error_keeps_local_review_record_and_retry(self):
        pk,_=self.message()
        with patch.object(Model,"complete",side_effect=RuntimeError("offline")):
            self.process(pk,Model())
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.events()[0]["needs_review"],1)
        self.assertEqual(self.conn.execute("SELECT retryable FROM interview_scans").fetchone()[0],1)
    def test_extraction_failure_never_breaks_persistence(self):
        pk,_=self.message()
        with patch.object(interviews,"detect",side_effect=RuntimeError("bad model")):
            self.assertEqual(self.process(pk),[])
        self.assertIsNotNone(db.get_message(self.conn,pk))
        self.assertEqual(db.get_cached(self.conn,pk,"1").category,"interview_invite")
    def test_retention_preserves_interview_and_source_metadata(self):
        pk,_=self.message();self.process(pk,Model())
        db.prune_messages(self.conn,before_iso="2026-10-16")
        self.assertEqual(len(self.events()),1)
        source=interviews.event_sources(self.conn,1)[0]
        self.assertIsNone(source["message_pk"]);self.assertEqual(source["source_subject"],"Technical Interview Confirmation")
    def test_imap_and_graph_capture_ics_and_thread_data(self):
        payload=ics()
        mime=message_from_string('MIME-Version: 1.0\nContent-Type: text/calendar; charset="utf-8"\n\n'+payload)
        class Mail:
            obj=mime
        self.assertIn("UID:invite-1",imap_calendars(Mail())[0])
        raw=graph_raw({"id":"g1","subject":"Interview","conversationId":"conversation-1","internetMessageHeaders":[{"name":"In-Reply-To","value":"<original@acme.test>"}],"body":{"content":"Interview https://teams.microsoft.com/"},"attachments":[{"name":"invite.ics","contentType":"text/calendar","contentBytes":base64.b64encode(payload.encode()).decode()}]})
        normalized=normalize.normalize(raw,account_id=self.a,account_label="work")
        pk=db.upsert_message(self.conn,normalized)
        row=dict(db.get_message(self.conn,pk))
        self.assertEqual(row["thread_id"],"conversation-1")
        self.assertEqual(json.loads(row["references_json"]),["<original@acme.test>"])
        self.assertEqual(len(json.loads(row["calendar_data"])),1)
    def test_full_meeting_link_not_truncated_with_classifier_body(self):
        url="https://teams.microsoft.com/l/meetup-join/"+"a"*180
        raw=RawMessage("id","u","INBOX","hr@acme.test","HR","Interview",None,"Interview "+url)
        msg=normalize.normalize(raw,account_id=self.a,account_label="work",max_body_chars=60)
        self.assertIn(url,msg.interview_text)
        self.assertNotIn(url,msg.body)
    def test_pipeline_does_not_infer_events_from_unclassified_text(self):
        pk,msg=self.message()
        cfg=config.Config();cfg.llm.base_url=""
        with patch.object(pipeline,"fetch_account",return_value=[msg]),patch.object(pipeline,"classify",return_value=([Classification(category="unclassified",retryable=True)],[])),patch.object(pipeline,"LLMClient") as llm:
            llm.from_config.return_value.__enter__.return_value.model="test"
            result=pipeline.check_once(self.conn,cfg,since_days=90,use_cache=False,account_label="work")
        self.assertEqual(result.fetched,1)
        self.assertIsNotNone(db.get_message(self.conn,pk))
        self.assertEqual(len(self.events()),0)
    def test_pipeline_lifecycle_and_reprocess_no_second_fetch(self):
        cfg=config.Config();cfg.llm.base_url=""
        _,first=self.message(calendar_data=[ics()])
        updated=replace(first,message_id="<update@acme.test>",calendar_data=[ics(sequence=1,start="20261020T190000Z",end="20261020T200000Z")])
        cancelled=replace(first,message_id="<cancel@acme.test>",calendar_data=[ics(sequence=2,status="CANCELLED",start="20261020T190000Z",end="20261020T200000Z")])
        for message in (first,updated,cancelled):
            with patch.object(pipeline,"fetch_account",return_value=[message]) as fetch,patch.object(pipeline,"classify",return_value=([Classification(category="interview_invite",company="Acme",role="Engineer")],[])),patch.object(pipeline,"LLMClient") as llm:
                llm.from_config.return_value.__enter__.return_value.model="test"
                pipeline.check_once(self.conn,cfg,since_days=90,use_cache=False)
                self.assertEqual(fetch.call_count,2) # both enabled accounts, one fetch each
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.events()[0]["status"],"Cancelled")
        self.assertEqual(self.events()[0]["start_at"],"2026-10-20T19:00:00+00:00")
    def test_edit_validation(self):
        pk,_=self.message();self.process(pk,Model())
        for fields in ({"status":"invalid"},{"meeting_url":"javascript:alert(1)"},{"start_at":"not a date"},{"timezone":"CST"},{"unknown":True}):
            with self.subTest(fields=fields),self.assertRaises(ValueError): interviews.correct_event(self.conn,1,fields)


class InterviewApiTests(unittest.TestCase):
    message = InterviewTests.message
    process = InterviewTests.process
    events = InterviewTests.events
    def setUp(self):
        InterviewTests.setUp(self)
        for name,value in (("db_path",self.path),("config_path",Path(self.tmp.name)/"config.toml")):
            p=patch.object(config,name,return_value=value);p.start();self.addCleanup(p.stop)
        p=patch.object(web._scheduler_started,"is_set",return_value=True);p.start();self.addCleanup(p.stop)
        self.client=TestClient(web.create_app());self.addCleanup(self.client.close)
    def test_interview_routes_details_edit_and_guest_authorization(self):
        pk,_=self.message(calendar_data=[ics()]);self.process(pk);self.conn.commit()
        self.assertEqual(self.client.get("/interviews").status_code,200)
        response=self.client.get("/api/interviews").json()
        self.assertEqual(len(response["events"]),1);self.assertEqual(len(response["accounts"]),2)
        self.assertEqual(response["events"][0]["account_labels"],["work"])
        self.assertEqual(self.client.get("/api/interviews/1").json()["sources"][0]["message_pk"],pk)
        self.assertEqual(self.client.post("/api/interviews/1",json={"company":"Edited"}).status_code,200)
        self.assertEqual(self.client.get("/api/interviews?company=Edited").json()["events"][0]["company"],"Edited")
        self.assertEqual(self.client.get("/api/interviews/999").status_code,404)
        sign_in_bidder(self.client)
        for path in ("/interviews","/api/interviews","/api/interviews/1","/api/interviews/scan"):
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post("/api/interviews/1",json={"company":"No"}).status_code,403)

    def test_calendar_check_collects_events_without_configured_model(self):
        cfg=config.Config();cfg.llm.base_url="";config.save(cfg)
        result={"changes":[],"errors":[],"accounts":2}
        with patch.object(interviews,"collect_calendar_events",return_value=result) as collect:
            self.assertEqual(self.client.post("/api/check",json={"mode":"calendar"}).status_code,200)
            self.assertTrue(web._job_lock.acquire(timeout=2));web._job_lock.release()
            self.assertEqual(collect.call_count,1)
            self.assertEqual(self.client.post("/api/interviews/sync").status_code,200)
            self.assertTrue(web._job_lock.acquire(timeout=2));web._job_lock.release()
            self.assertEqual(collect.call_count,2)
        self.assertNotIn("classified",web._job["message"])


    def test_outlook_reconnect_preserves_account_and_calendar_records(self):
        from types import SimpleNamespace
        import time
        cfg=config.Config();cfg.outlook.client_id="test";config.save(cfg)
        with db.session() as conn:
            account_id=db.add_account(conn,label="outlook",email="me@example.test",provider="outlook")
        pending=SimpleNamespace(id="reconnect-test",label="outlook",user_code="TEST",verification_uri="https://microsoft.com/devicelogin")
        with patch.object(web.outlook_auth,"begin_device_flow",return_value=pending),patch.object(web.outlook_auth,"complete_device_flow",return_value="me@example.test"):
            response=self.client.post("/api/outlook/start",json={"label":"outlook","reconnect":True})
            self.assertEqual(response.status_code,200)
            for _ in range(100):
                if web._outlook['state']!='waiting':break
                time.sleep(.01)
            self.assertEqual(web._outlook['state'],'connected')
        self.assertEqual(db.get_account(self.conn,"outlook").id,account_id)
        self.assertEqual(len(db.list_accounts(self.conn)),3)


class AdditionalReconciliationTests(unittest.TestCase):
    setUp = InterviewTests.setUp
    message = InterviewTests.message
    process = InterviewTests.process
    events = InterviewTests.events
    def test_text_cancellation_matches_existing_calendar(self):
        pk,_=self.message(calendar_data=[ics()]);self.process(pk)
        pk,_=self.message(subject="Interview cancelled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="cancelled",start_time=None,end_time=None))
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.events()[0]["status"],"Cancelled")
        self.assertEqual(self.events()[0]["needs_review"],0)
    def test_ics_timezone_and_floating_time(self):
        raw=ics().replace("DTSTART:20261018T153000Z","DTSTART;TZID=America/Chicago:20261018T103000").replace("DTEND:20261018T163000Z","DTEND;TZID=America/Chicago:20261018T113000")
        pk,_=self.message(calendar_data=[raw]);self.process(pk)
        self.assertEqual(self.events()[0]["start_at"],"2026-10-18T15:30:00+00:00")
        self.assertEqual(self.events()[0]["timezone"],"America/Chicago")
        floating=ics(uid="floating").replace("20261018T153000Z","20261018T103000").replace("20261018T163000Z","20261018T113000")
        pk,_=self.message(calendar_data=[floating]);self.process(pk)
        self.assertTrue(self.events()[1]["needs_review"])
        self.assertIsNone(self.events()[1]["start_at"])
    def test_unrelated_calendar_is_not_an_interview(self):
        raw=ics().replace("Acme Technical Interview","Dentist appointment")
        pk,_=self.message(subject="Calendar invitation",body="Your cleaning is booked. Interview tips are in the footer.",calendar_data=[raw])
        interviews.process_message(self.conn,pk,{"category":"other","company":None})
        self.assertEqual(self.events(),[])
    def test_reschedule_without_end_clears_obsolete_end(self):
        pk,_=self.message();self.process(pk,Model())
        pk,_=self.message(subject="Interview rescheduled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="rescheduled",start_time="2026-10-20T14:00:00-05:00",end_time=None))
        self.assertIsNone(self.events()[0]["end_at"])

class InterviewBackfillTests(unittest.TestCase):
    setUp = InterviewApiTests.setUp
    message = InterviewTests.message
    process = InterviewTests.process
    events = InterviewTests.events
    def test_saved_mail_scan_is_retired_without_reading_messages(self):
        self.message(calendar_data=[ics()]);self.conn.commit()
        with patch.object(interviews,"process_message",side_effect=AssertionError("No mail scanning")):
            self.assertEqual(self.client.post("/api/interviews/scan").status_code,410)
        self.assertEqual(self.events(),[])

    def test_v7_upgrade_keeps_existing_mail_and_handled_state(self):
        pk,_=self.message();db.set_handled(self.conn,pk,True)
        for table in ('interview_sources','interview_scans','interview_events'):self.conn.execute(f'DROP TABLE {table}')
        for column in ('calendar_data','thread_id','references_json','interview_text'):self.conn.execute(f'ALTER TABLE messages DROP COLUMN {column}')
        self.conn.execute('PRAGMA user_version=7');self.conn.commit()
        upgraded=db.connect(self.path)
        try:
            self.assertEqual(upgraded.execute('PRAGMA user_version').fetchone()[0],db.SCHEMA_VERSION)
            self.assertIsNotNone(db.get_message(upgraded,pk)['handled_at'])
            self.assertEqual(db.get_cached(upgraded,pk,'1').category,'interview_invite')
            self.assertEqual(upgraded.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],0)
        finally:upgraded.close()


class InterviewReviewRegressionTests(unittest.TestCase):
    setUp = InterviewTests.setUp
    message = InterviewTests.message
    process = InterviewTests.process
    events = InterviewTests.events

    def test_separate_bookings_in_one_thread_remain_separate(self):
        pk,_=self.message();self.process(pk,Model())
        pk,_=self.message(subject="Another technical interview confirmation")
        self.process(pk,Model(start_time="2026-10-22T10:30:00-05:00",end_time="2026-10-22T11:30:00-05:00"))
        self.assertEqual(len(self.events()),2)
        self.assertEqual(self.events()[0]["start_at"],"2026-10-18T15:30:00+00:00")

    def test_recurring_occurrences_with_same_uid_stay_distinct(self):
        for start,end in (("20261018T153000Z","20261018T163000Z"),("20261025T153000Z","20261025T163000Z")):
            pk,_=self.message(calendar_data=[ics(uid="series",start=start,end=end,extra=f"RECURRENCE-ID:{start}\r\n")])
            self.process(pk)
        self.assertEqual(len(self.events()),2)
        self.assertNotEqual(self.events()[0]["recurrence_id"],self.events()[1]["recurrence_id"])

    def test_known_calendar_uid_cancellation_does_not_need_interview_keywords(self):
        pk,_=self.message(calendar_data=[ics()]);self.process(pk)
        cancel=ics(sequence=1,status="CANCELLED").replace("Acme Technical Interview","Meeting")
        pk,_=self.message(subject="Cancelled: Meeting",body="This meeting is cancelled.",calendar_data=[cancel])
        interviews.process_message(self.conn,pk,{"category":"other","company":None})
        self.assertEqual(self.events()[0]["status"],"Cancelled")
        self.assertEqual(len(self.events()),1)

    def test_ics_duration_supplies_end_time(self):
        raw=ics().replace("DTEND:20261018T163000Z","DURATION:PT30M")
        pk,_=self.message(calendar_data=[raw]);self.process(pk)
        self.assertEqual(self.events()[0]["end_at"],"2026-10-18T16:00:00+00:00")

    def test_model_date_without_clock_time_does_not_become_midnight_booking(self):
        pk,_=self.message();self.process(pk,Model(start_time="2026-10-18",end_time=None))
        self.assertTrue(self.events()[0]["needs_review"])
        self.assertIsNone(self.events()[0]["start_at"])

    def test_clearing_start_keeps_event_visible_for_review(self):
        pk,_=self.message();self.process(pk,Model())
        value=interviews.correct_event(self.conn,1,{"start_at":None,"end_at":None})
        self.assertTrue(value["needs_review"])
        self.assertEqual(value["display_status"],"Needs review")

    def test_automatic_update_cannot_create_interval_before_protected_end(self):
        pk,_=self.message();self.process(pk,Model())
        interviews.correct_event(self.conn,1,{"end_at":"2026-10-18T18:00:00Z"})
        pk,_=self.message(subject="Interview rescheduled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="rescheduled",start_time="2026-10-20T14:00:00-05:00",end_time="2026-10-20T15:00:00-05:00"))
        event=self.events()[0]
        self.assertLess(interviews._utc(event["start_at"]),interviews._utc(event["end_at"]))
        self.assertEqual(event["end_at"],"2026-10-18T18:00:00+00:00")
        self.assertTrue(event["needs_review"])

    def test_ambiguous_reschedule_preserves_confirmed_time(self):
        pk,_=self.message();self.process(pk,Model())
        pk,_=self.message(subject="Interview rescheduled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="rescheduled",start_time="2026-10-20T14:00:00-05:00",end_time="2026-10-20T15:00:00-05:00",ambiguous=True))
        event=self.events()[0]
        self.assertEqual(event["start_at"],"2026-10-18T15:30:00+00:00")
        self.assertTrue(event["needs_review"])

    def test_cancellation_retains_last_confirmed_booking_time(self):
        pk,_=self.message();self.process(pk,Model(start_time="2026-10-20T14:00:00-05:00",end_time="2026-10-20T15:00:00-05:00"))
        pk,_=self.message(subject="Interview cancelled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="cancelled"))
        self.assertEqual(self.events()[0]["start_at"],"2026-10-20T19:00:00+00:00")
        self.assertEqual(self.events()[0]["status"],"Cancelled")

    def test_invalid_timestamp_types_cannot_corrupt_stored_record(self):
        pk,_=self.message();self.process(pk,Model())
        for value in (0,False,[],"",{}):
            with self.subTest(value=value),self.assertRaises(ValueError):
                interviews.correct_event(self.conn,1,{"start_at":value})
        self.assertEqual(len(interviews.list_events(self.conn)),1)

    def test_explicit_review_status_and_whitespace_company(self):
        pk,_=self.message();self.process(pk,Model())
        value=interviews.correct_event(self.conn,1,{"status":"Needs review"})
        self.assertTrue(value["needs_review"])
        with self.assertRaises(ValueError):
            interviews.correct_event(self.conn,1,{"company":"   ","needs_review":False})

    def test_cancellation_with_multiple_possible_bookings_requires_review(self):
        pk,_=self.message();self.process(pk,Model())
        pk,_=self.message();self.process(pk,Model(start_time="2026-10-22T10:30:00-05:00",end_time="2026-10-22T11:30:00-05:00"))
        pk,_=self.message(subject="Interview cancelled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="cancelled",start_time=None,end_time=None))
        self.assertEqual([r["status"] for r in self.events()[:2]],["Scheduled","Scheduled"])
        self.assertTrue(self.events()[2]["needs_review"])

    def test_reply_reference_identifies_one_booking_in_shared_thread(self):
        pk,first=self.message();self.process(pk,Model())
        pk,_=self.message();self.process(pk,Model(start_time="2026-10-22T10:30:00-05:00",end_time="2026-10-22T11:30:00-05:00"))
        pk,_=self.message(subject="Interview cancelled",references=[first.message_id],date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="cancelled",start_time=None,end_time=None))
        self.assertEqual(len(self.events()),2)
        self.assertEqual([r["status"] for r in self.events()],["Cancelled","Scheduled"])

    def test_explicit_time_identifies_one_booking_in_shared_thread(self):
        pk,_=self.message();self.process(pk,Model())
        pk,_=self.message();self.process(pk,Model(start_time="2026-10-22T10:30:00-05:00",end_time="2026-10-22T11:30:00-05:00"))
        pk,_=self.message(subject="Interview cancelled",date_utc=datetime(2026,10,16,12))
        self.process(pk,Model(event_type="cancelled",start_time="2026-10-22T10:30:00-05:00",end_time="2026-10-22T11:30:00-05:00"))
        self.assertEqual(len(self.events()),2)
        self.assertEqual([r["status"] for r in self.events()],["Scheduled","Cancelled"])
