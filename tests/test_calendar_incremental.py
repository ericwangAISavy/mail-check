"""Automatic calendar collection: changes only, with periodic full reads."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from mailcheck import calendar_sync, config, interviews, pipeline
from mailcheck.sources.outlook import GRAPH
from tests import test_calendar_collection as native

DELTA = f"{GRAPH}/me/calendarView/delta"


event = native.event


class IncrementalCalendarTests(unittest.TestCase):
    def setUp(self):
        native.NativeCalendarTests.setUp(self)
        self.events = {}        # what Microsoft currently holds
        self.changed = []       # ids the next change list reports
        self.expired = False
        self.paths = []

    source = native.NativeCalendarTests.source

    def graph(self, request):
        path = request.url.path.removeprefix("/v1.0")
        self.paths.append(path)
        if path == "/me/calendars":
            return httpx.Response(200, json={"value": [{"id": "calendar-1", "name": "Calendar"}]})
        if path == "/me/calendars/calendar-1/calendarView":
            return httpx.Response(200, json={"value": list(self.events.values())})
        if path == "/me/calendarView/delta":
            if "token" in str(request.url) and self.expired:
                self.expired = False
                return httpx.Response(410, json={"error": {"code": "syncStateNotFound"}})
            items = [{"id": identity} for identity in self.changed] if "token" in str(request.url) else []
            self.changed = []
            return httpx.Response(200, json={"value": items, "@odata.deltaLink": DELTA + "?$deltatoken=token"})
        if path == "/me/calendar":
            return httpx.Response(200, json={"id": "calendar-1", "name": "Calendar"})
        identity = path.removeprefix("/me/events/")
        if identity in self.events:
            return httpx.Response(200, json=self.events[identity])
        return httpx.Response(404, json={"error": {"code": "ErrorItemNotFound"}})

    def run_sync(self, *, incremental=True):
        self.paths = []
        cfg = config.Config(); cfg.llm.base_url = "http://model.test"
        with patch.object(pipeline, "build_source", return_value=self.source(handler=self.graph)), \
             patch("mailcheck.calendar_analysis.LLMClient.from_config", side_effect=AssertionError("no inference")):
            return interviews.collect_calendar_events(self.conn, cfg, account_label="work",
                                                      defer_analysis=True, incremental=incremental)

    def present(self, identity):
        row = self.conn.execute("""SELECT c.present FROM interview_sources s JOIN interview_calendar_state c ON c.source_id=s.id
            WHERE s.external_message_id=?""", ("graph-event:" + identity,)).fetchone()
        return None if row is None else row[0]

    def task_state(self, identity):
        return self.conn.execute("SELECT state FROM calendar_analysis_tasks WHERE external_id=?",
                                 ("graph-event:" + identity,)).fetchone()[0]

    def test_first_run_reads_everything_then_only_changes_without_writing_events(self):
        self.events = {name: event(name) for name in ("one", "two")}
        first = self.run_sync()
        self.assertFalse(first["errors"]); self.assertEqual(len(first["changes"]), 2)
        self.assertIn("/me/calendars/calendar-1/calendarView", self.paths)

        statements = []
        self.conn.set_trace_callback(statements.append)
        second = self.run_sync()
        self.conn.set_trace_callback(None)
        self.assertFalse(second["errors"]); self.assertFalse(second["changes"])
        self.assertEqual(self.paths, ["/me/calendarView/delta"])          # one small request
        writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
        self.assertTrue(all("pipeline_sync_state" in s for s in writes), writes)

    def test_changed_new_and_deleted_events_are_applied_from_the_change_list(self):
        self.events = {name: event(name) for name in ("one", "two")}
        self.run_sync()
        moved = event("one")
        moved["start"] = {"dateTime": "2026-10-19T15:30:00.0000000", "timeZone": "UTC"}
        moved["end"] = {"dateTime": "2026-10-19T16:30:00.0000000", "timeZone": "UTC"}
        moved["lastModifiedDateTime"] = "2026-10-16T12:00:00Z"
        self.events["one"] = moved
        self.events["three"] = event("three")
        del self.events["two"]
        self.changed = ["one", "two", "three"]
        result = self.run_sync()
        self.assertFalse(result["errors"])
        self.assertNotIn("/me/calendars/calendar-1/calendarView", self.paths)
        self.assertEqual(len(result["changes"]), 2)
        self.assertEqual((self.present("one"), self.present("two"), self.present("three")), (1, 0, 1))
        self.assertEqual(self.task_state("two"), "cancelled")
        starts = {row[0] for row in self.conn.execute("SELECT start_at FROM interview_events")}
        self.assertIn("2026-10-19T15:30:00+00:00", starts)

    def test_periodic_full_read_keeps_unchanged_events_and_retires_missing_ones(self):
        self.events = {name: event(name) for name in ("one", "two")}
        self.run_sync()
        del self.events["two"]                      # deleted without appearing in a change list
        with patch.object(calendar_sync, "FULL_READ_SECONDS", 0):
            result = self.run_sync()
        self.assertFalse(result["errors"]); self.assertFalse(result["changes"])
        self.assertIn("/me/calendars/calendar-1/calendarView", self.paths)
        self.assertEqual((self.present("one"), self.present("two")), (1, 0))
        self.assertNotEqual(self.task_state("one"), "cancelled")
        self.assertEqual(self.task_state("two"), "cancelled")

    def test_an_expired_token_falls_back_to_a_full_read(self):
        self.events = {"one": event("one")}
        self.run_sync()
        self.expired = True
        result = self.run_sync()
        self.assertFalse(result["errors"])
        self.assertIn("/me/calendars/calendar-1/calendarView", self.paths)
        self.assertEqual(self.present("one"), 1)

    def test_a_failed_save_keeps_the_old_token_so_the_change_comes_back(self):
        self.events = {"one": event("one")}
        self.run_sync()
        self.events["two"] = event("two"); self.changed = ["two"]
        with patch.object(interviews, "_save_calendar_booking", side_effect=ValueError("bad")), \
             patch.object(calendar_sync.SyncState, "save", autospec=True, side_effect=calendar_sync.SyncState.save) as saved:
            self.assertTrue(self.run_sync()["errors"])
        self.assertNotIn("graph-event:two", saved.call_args.args[0].events)
        self.changed = ["two"]
        self.assertFalse(self.run_sync()["errors"])
        self.assertEqual(self.present("two"), 1)

    def test_manual_checks_still_read_and_process_everything(self):
        self.events = {"one": event("one")}
        self.run_sync()
        with patch.object(interviews, "_save_calendar_booking", wraps=interviews._save_calendar_booking) as save:
            self.run_sync(incremental=False)
        self.assertEqual(save.call_count, 1)
        self.assertNotIn("/me/calendarView/delta", self.paths)

    def test_rows_missing_from_the_database_are_rebuilt_despite_saved_progress(self):
        self.events = {"one": event("one")}
        self.run_sync()
        self.conn.execute("DELETE FROM interview_calendar_state"); self.conn.commit()
        with patch.object(calendar_sync, "FULL_READ_SECONDS", 0):
            self.run_sync()
        self.assertEqual(self.present("one"), 1)


def test_polling_slows_only_while_calendar_notifications_are_active(tmp_path):
    from mailcheck.shared import runtime
    rows = [dict(account_id=1, kind="calendar", expires=9e12), dict(account_id=2, kind="mail", expires=9e12),
            dict(account_id=3, kind="calendar", expires=1)]
    with patch.object(runtime, "ExistingRegistry", lambda path: SimpleNamespace(list_workspace=lambda wid: rows)):
        assert [runtime._calendar_notifications_live(tmp_path, "w", n) for n in (1, 2, 3)] == [True, False, False]
    with patch.object(runtime, "ExistingRegistry", side_effect=OSError("missing")):
        assert runtime._calendar_notifications_live(tmp_path, "w", 1) is False
