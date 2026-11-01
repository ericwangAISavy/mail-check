"""Native sheets preserve owner scope, stable identities and atomic edits."""

import importlib
import json
import unittest
from tests import test_frontend_api as fixtures


class NativeSheetTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
        self.assertIsNotNone(
            importlib.util.find_spec("mailcheck.native_sourcing"),
            "Native sheet storage is not implemented",
        )
        self.native = importlib.import_module("mailcheck.native_sourcing")
        for name in ("Alex", "Blair"):
            self.conn.execute(
                "INSERT INTO bidders(name,created_at) VALUES(?,'2026-10-15')", (name,)
            )
        self.conn.commit()
        self.book = self.native.create_book(self.conn, 1, "Applications")
        self.tab_id = self.native.create_tab(
            self.conn, self.book, self.account_id, "Engineering"
        )
        self.principal = {"role": "admin", "bidder_id": None}

    def test_index_backfills_existing_bidders_without_replacing_workbooks(self):
        before = self.snapshot()
        result = self.client.get("/api/sourcing")
        self.assertEqual(result.status_code, 200, result.text)
        books = result.json()["books"]
        self.assertEqual([b["name"] for b in books], ["Alex", "Blair"])
        alex = next(b for b in books if b["bidder_id"] == 1)
        self.assertEqual(alex["id"], self.book)
        self.assertEqual(alex["tabs"][0]["id"], self.tab_id)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.client.get("/api/sourcing").json()["books"], books)
        self.conn.execute("UPDATE bidders SET name='Renamed' WHERE id=2")
        self.conn.commit()
        self.assertIn("Renamed", [b["name"] for b in self.client.get("/api/sourcing").json()["books"]])
        self.client.post("/api/payments/bidders/2/remove", json={})
        self.assertEqual([b["name"] for b in self.client.get("/api/sourcing").json()["books"]], ["Alex"])

    def test_job_dates_count_nonempty_links_across_active_account_tabs(self):
        base = self.snapshot()
        self.native.append(self.conn, self.tab(), "day-one", base["revision"],
                           [["Acme", "Engineer", "https://jobs.test/1"]], work_date="2026-10-20")
        current = self.snapshot()
        self.native.append(self.conn, self.tab(), "no-link", current["revision"],
                           [["Beta", "Engineer", "  "]], work_date="2026-10-21")
        books = self.client.get("/api/sourcing").json()["books"]
        self.assertEqual(next(b for b in books if b["bidder_id"] == 1)["job_dates"], ["2026-10-20"])
        self.assertEqual(next(b for b in books if b["bidder_id"] == 2)["job_dates"], [])
        self.conn.execute("UPDATE native_tabs SET archived=1 WHERE id=?", (self.tab_id,))
        self.conn.commit()
        books = self.client.get("/api/sourcing").json()["books"]
        self.assertEqual(next(b for b in books if b["bidder_id"] == 1)["job_dates"], [])

    def tab(self):
        return self.native.owned(self.conn, self.tab_id, self.principal)

    def snapshot(self):
        return self.native.snapshot(self.conn, self.tab())

    def change(self, value="Acme", col=0, row=1, base=None):
        base = base or self.snapshot()
        return {
            "row_id": base["row_ids"][row],
            "column_id": base["columns"][col]["id"],
            "expected_version": base["rows"][row][col]["version"],
            "value": value,
        }

    def test_tabs_use_account_names_and_have_a_compact_check_column(self):
        base = self.snapshot()
        label = self.conn.execute("SELECT label FROM accounts WHERE id=?", (self.account_id,)).fetchone()[0]
        self.assertEqual(base["title"], label)
        self.assertEqual([c["kind"] for c in base["columns"][:4]], ["company", "role", "link", "check"])
        self.assertEqual(base["columns"][3]["title"], "Check")
        self.assertLessEqual(base["columns"][3]["width"], 80)

    def test_blank_pasted_rows_are_not_stored_between_jobs(self):
        base = self.snapshot()
        result = self.native.append(self.conn, self.tab(), "blank-append", base["revision"],
            [["Acme", "Engineer", "https://jobs.test/1"], ["", "  ", ""],
             ["Beta", "Engineer", "https://jobs.test/2"], ["", "", ""]], work_date="2026-10-20")
        jobs = [r for r in result["rows"][1:] if any(str(c["value"]).strip() for c in r)]
        self.assertEqual([r[0]["value"] for r in jobs], ["Acme", "Beta"])
        self.assertEqual(len(result["row_ids"]), 4)  # header, two jobs, one input row
        self.assertEqual(result["row_dates"][1:3], ["2026-10-20", "2026-10-20"])

    def test_existing_sheet_upgrade_keeps_cells_and_adds_check_after_job_link(self):
        self.native.save(self.conn, self.tab(), "original", [self.change("Acme")])
        old = self.snapshot()
        self.conn.execute("DELETE FROM native_columns WHERE tab_id=? AND kind='check'", (self.tab_id,))
        self.conn.execute("UPDATE native_tabs SET title='Custom name' WHERE id=?", (self.tab_id,))
        self.conn.execute("ALTER TABLE application_receipts DROP COLUMN company")
        self.conn.execute("PRAGMA user_version=21")
        self.conn.commit()
        from mailcheck import db
        with db.session(self.path) as conn:
            tab = self.native.owned(conn, self.tab_id, self.principal)
            migrated = self.native.snapshot(conn, tab)
            self.assertEqual(migrated["row_ids"], old["row_ids"])
            self.assertEqual(migrated["rows"][1][0]["value"], "Acme")
            self.assertEqual([col["id"] for col in migrated["columns"][:3]], [col["id"] for col in old["columns"][:3]])
            self.assertEqual(migrated["columns"][3]["kind"], "check")
            self.assertEqual(migrated["title"], "personal")
            self.assertIn("company", [row["name"] for row in conn.execute("PRAGMA table_info(application_receipts)")])

    def test_deleting_an_imported_tab_does_not_reimport_it_on_upgrade(self):
        self.conn.execute("INSERT INTO sourcing_books(id,bidder_id,spreadsheet_id,title) VALUES(22,2,'legacy-delete','Legacy')")
        self.conn.execute("INSERT INTO sourcing_tabs(id,book_id,sheet_id,account_id,account_label,title) VALUES(22,22,1,?,'personal','Old tab')", (self.account_id,))
        self.native.migrate(self.conn)
        self.conn.commit()
        tab_id = self.conn.execute("SELECT id FROM native_tabs WHERE legacy_tab_id=22").fetchone()[0]
        tab = self.native.owned(self.conn, tab_id, self.principal)
        self.native.delete_tab(self.conn, tab, str(tab["revision"]))
        self.native.migrate(self.conn)
        self.assertIsNone(self.conn.execute("SELECT id FROM native_tabs WHERE legacy_tab_id=22").fetchone())
        self.assertIsNone(self.conn.execute("SELECT id FROM sourcing_tabs WHERE id=22").fetchone())

    def test_native_sheet_saves_literal_values_and_retries_without_duplication(self):
        self.assertEqual(self.snapshot()["rows"][0][0]["display"], "Company")
        changes = [self.change("=literal")]
        result = self.native.save(self.conn, self.tab(), "operation-1", changes)
        self.assertEqual(result["rows"][1][0]["value"], "=literal")
        self.assertFalse(result["rows"][1][0]["formula"])
        again = self.native.save(self.conn, self.tab(), "operation-1", changes)
        self.assertEqual(
            again["rows"][1][0]["version"], result["rows"][1][0]["version"]
        )

    def test_independent_edits_merge_but_same_cell_conflicts_atomically(self):
        base = self.snapshot()
        self.native.save(
            self.conn, self.tab(), "first", [self.change("Acme", base=base)]
        )
        self.native.save(
            self.conn, self.tab(), "second", [self.change("Engineer", col=1, base=base)]
        )
        with self.assertRaises(FileExistsError):
            self.native.save(
                self.conn,
                self.tab(),
                "third",
                [
                    self.change("Overwrite", base=base),
                    self.change("lost", col=2, base=base),
                ],
            )
        current = self.snapshot()
        self.assertEqual(current["rows"][1][0]["value"], "Acme")
        self.assertEqual(current["rows"][1][1]["value"], "Engineer")
        self.assertEqual(current["rows"][1][2]["value"], "")

    def test_owner_is_checked_before_read_or_write(self):
        with self.assertRaises(PermissionError):
            self.native.owned(
                self.conn, self.tab_id, {"role": "bidder", "bidder_id": 2}
            )

    def test_cached_google_data_migrates_once_without_network(self):
        legacy = {
            "rows": [
                [{"display": "Company"}, {"display": "Role"}, {"display": "Job link"}],
                [
                    {"value": "Acme", "display": "Acme"},
                    {"value": "=role()", "display": "Engineer", "formula": True},
                    {
                        "value": "Apply",
                        "display": "Apply",
                        "link": "https://jobs.test/actual",
                    },
                ],
            ]
        }
        self.conn.execute(
            "INSERT INTO sourcing_books(id,bidder_id,spreadsheet_id,title) VALUES(22,2,'legacy','Old sheet')"
        )
        self.conn.execute(
            "INSERT INTO sourcing_tabs(id,book_id,sheet_id,account_id,account_label,title,snapshot) VALUES(22,22,12,?,?,?,?)",
            (self.account_id, "personal", "Old profile", json.dumps(legacy)),
        )
        self.conn.commit()
        self.native.migrate(self.conn)
        self.native.migrate(self.conn)
        tabs = self.conn.execute(
            "SELECT * FROM native_tabs WHERE legacy_tab_id=22"
        ).fetchall()
        self.assertEqual(len(tabs), 1)
        result = self.native.snapshot(self.conn, dict(tabs[0]))
        self.assertEqual(result["rows"][1][1]["value"], "Engineer")
        self.assertFalse(result["rows"][1][1]["formula"])
        self.assertEqual(result["rows"][1][2]["value"], "https://jobs.test/actual")
        self.assertTrue(result["migration_notice"])
        self.assertEqual(
            self.conn.execute(
                "SELECT snapshot FROM sourcing_tabs WHERE id=22"
            ).fetchone()[0],
            json.dumps(legacy),
        )

    def test_stable_cell_id_survives_row_insert_and_deleted_row_conflicts(self):
        base = self.snapshot()
        change = self.change("Original job", base=base)
        shifted = self.native.structure(
            self.conn,
            self.tab(),
            "insert",
            base["revision"],
            {"action": "insert_rows", "at_row_id": base["row_ids"][1], "count": 2},
        )
        current = self.native.save(
            self.conn, self.tab(), "write-after-insert", [change]
        )
        self.assertEqual(current["rows"][3][0]["value"], "Original job")
        self.native.structure(
            self.conn,
            self.tab(),
            "delete",
            current["revision"],
            {"action": "delete_rows", "ids": [change["row_id"]]},
        )
        with self.assertRaises(FileExistsError):
            self.native.save(self.conn, self.tab(), "deleted-row", [change])

    def test_append_is_atomic_and_idempotent(self):
        base = self.snapshot()
        first = self.native.append(
            self.conn,
            self.tab(),
            "append",
            base["revision"],
            [["Acme", "Engineer", "https://jobs.test/1"]],
        )
        second = self.native.append(
            self.conn,
            self.tab(),
            "append",
            base["revision"],
            [["Acme", "Engineer", "https://jobs.test/1"]],
        )
        self.assertEqual(first["row_ids"], second["row_ids"])
        self.assertEqual(second["rows"][1][0]["value"], "Acme")

    def test_required_columns_cannot_be_deleted_but_custom_columns_can(self):
        base = self.snapshot()
        with self.assertRaises(ValueError):
            self.native.structure(
                self.conn,
                self.tab(),
                "bad",
                base["revision"],
                {"action": "delete_column", "column_id": base["columns"][0]["id"]},
            )
        added = self.native.structure(
            self.conn,
            self.tab(),
            "add",
            base["revision"],
            {"action": "add_column", "title": "Notes"},
        )
        self.assertEqual(added["columns"][-1]["title"], "Notes")
        self.native.structure(
            self.conn,
            self.tab(),
            "remove",
            added["revision"],
            {"action": "delete_column", "column_id": added["columns"][-1]["id"]},
        )
        self.assertEqual(len(self.snapshot()["columns"]), 4)

    def test_csv_replacement_is_checked_and_export_is_literal(self):
        from mailcheck import sourcing_csv

        body = {
            "text": 'Company,Role,Job link\r\nAcme,"Engineer, Platform",https://jobs.test/1\r\n',
            "mode": "replace",
            "has_header": True,
        }
        base = self.snapshot()
        imported = sourcing_csv.import_rows(
            self.conn, self.tab(), "csv", base["revision"], **body
        )
        self.assertEqual(imported["rows"][1][1]["value"], "Engineer, Platform")
        with self.assertRaises(FileExistsError):
            sourcing_csv.import_rows(
                self.conn, self.tab(), "stale-csv", base["revision"], **body
            )
        content = sourcing_csv.export_rows(self.conn, self.tab())
        self.assertIn('"Engineer, Platform"', content)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            sourcing_csv.import_rows(
                self.conn,
                self.tab(),
                "bad-csv",
                before["revision"],
                text='Company,Role,Job link\n"unterminated',
                mode="replace",
                has_header=True,
            )
        self.assertEqual(self.snapshot()["row_ids"], before["row_ids"])

    def test_snapshot_uses_one_read_transaction_during_concurrent_updates(self):
        from mailcheck import db

        before = self.native.save(
            self.conn, self.tab(), "initial", [self.change("Acme")]
        )
        writer = db.connect(self.path)
        self.addCleanup(writer.close)
        switched = False

        def concurrent_write(sql):
            nonlocal switched
            if switched or not sql.startswith(
                "SELECT id,title,kind,width FROM native_columns"
            ):
                return
            switched = True
            writer.execute(
                "UPDATE native_cells SET value='Newer job',version=version+1 WHERE row_id=?",
                (before["row_ids"][1],),
            )
            writer.execute(
                "UPDATE native_tabs SET revision=revision+1 WHERE id=?", (self.tab_id,)
            )
            writer.commit()

        self.conn.set_trace_callback(concurrent_write)
        try:
            result = self.snapshot()
        finally:
            self.conn.set_trace_callback(None)
        self.assertTrue(switched)
        self.assertEqual(result["revision"], before["revision"])
        self.assertEqual(result["rows"][1][0]["value"], "Acme")

    def test_csv_alias_headers_preserve_field_identity_when_out_of_order(self):
        from mailcheck import sourcing_csv

        result = sourcing_csv.import_rows(
            self.conn,
            self.tab(),
            "aliases",
            self.snapshot()["revision"],
            text="Role,Company,Job URL\nEngineer,Acme,https://jobs.test/1",
            mode="append",
            has_header=True,
        )
        self.assertEqual(result["rows"][1][0]["value"], "Acme")
        self.assertEqual(result["rows"][1][1]["value"], "Engineer")
        self.assertEqual(result["rows"][1][2]["value"], "https://jobs.test/1")

    def test_csv_import_can_use_the_full_advertised_cell_budget(self):
        from mailcheck import sourcing_csv

        text = "Company,Role,Job link\n" + "\n".join(
            f"Company {i},Engineer,https://jobs.test/{i}" for i in range(2000)
        )
        result = sourcing_csv.import_rows(
            self.conn,
            self.tab(),
            "many-rows",
            self.snapshot()["revision"],
            text=text,
            mode="replace",
            has_header=True,
        )
        self.assertEqual(len(result["rows"]), 2002)  # includes one trailing input row
        self.assertEqual(result["rows"][2000][0]["value"], "Company 1999")

    def test_dated_save_claims_blank_rows_and_prevents_cross_day_edits(self):
        base = self.snapshot()
        result = self.native.save(
            self.conn,
            self.tab(),
            "today-save",
            [self.change(base=base)],
            work_date="2026-10-15",
        )
        self.assertEqual(result["row_dates"][1], "2026-10-15")
        with self.assertRaises(FileExistsError):
            self.native.save(
                self.conn,
                self.tab(),
                "wrong-day",
                [self.change("Wrong", col=1, base=base)],
                work_date="2026-10-16",
            )
        self.assertEqual(self.snapshot()["rows"][1][1]["value"], "")
        with self.assertRaises(ValueError):
            self.native.save(
                self.conn,
                self.tab(),
                "invalid-date",
                [self.change("Bad")],
                work_date="2026-02-30",
            )

    def test_existing_jobs_stay_undated_and_date_moves_are_checked_and_idempotent(self):
        base = self.native.save(self.conn, self.tab(), "old-job", [self.change()])
        self.assertIsNone(base["row_dates"][1])
        command = {
            "action": "move_date",
            "ids": [base["row_ids"][1]],
            "work_date": "2026-10-15",
        }
        moved = self.native.structure(
            self.conn, self.tab(), "move-date", base["revision"], command
        )
        again = self.native.structure(
            self.conn, self.tab(), "move-date", base["revision"], command
        )
        self.assertEqual(again["revision"], moved["revision"])
        self.assertEqual(again["row_dates"][1], "2026-10-15")
        with self.assertRaises(FileExistsError):
            self.native.structure(
                self.conn,
                self.tab(),
                "stale-date",
                base["revision"],
                {**command, "work_date": "2026-10-16"},
            )
        self.assertEqual(self.snapshot()["rows"][1][0]["value"], "Acme")

    def test_daily_replace_and_export_leave_other_days_and_undated_jobs_intact(self):
        from mailcheck import sourcing_csv

        self.native.save(self.conn, self.tab(), "legacy", [self.change("Undated")])
        for day, name in [("2026-10-15", "Thursday"), ("2026-10-16", "Friday")]:
            base = self.snapshot()
            self.native.append(
                self.conn, self.tab(), day, base["revision"], [[name]], work_date=day
            )
        base = self.snapshot()
        replaced = sourcing_csv.import_rows(
            self.conn,
            self.tab(),
            "daily-replace",
            base["revision"],
            text="Company,Role\nReplacement,Engineer",
            mode="replace",
            work_date="2026-10-15",
        )
        values = [r[0]["value"] for r in replaced["rows"][1:]]
        self.assertIn("Undated", values)
        self.assertIn("Friday", values)
        self.assertNotIn("Thursday", values)
        csv = sourcing_csv.export_rows(self.conn, self.tab(), work_date="2026-10-15")
        self.assertIn("Replacement", csv)
        self.assertNotIn("Friday", csv)
        self.assertNotIn("Undated", csv)

    def test_upgrade_adds_dates_without_reassigning_existing_native_jobs(self):
        from mailcheck import db

        self.native.save(
            self.conn, self.tab(), "before-dates", [self.change("Existing job")]
        )
        self.conn.execute("ALTER TABLE native_rows DROP COLUMN work_date")
        self.conn.execute("PRAGMA user_version=15")
        self.conn.commit()
        upgraded = db.connect()
        try:
            result = self.native.snapshot(upgraded, self.tab())
            self.assertEqual(result["rows"][1][0]["value"], "Existing job")
            self.assertIsNone(result["row_dates"][1])
        finally:
            upgraded.close()

    def test_pre_date_operation_can_be_retried_after_upgrade(self):
        changes = [self.change("Saved before upgrade")]
        saved = self.native.save(self.conn, self.tab(), "legacy-save-id", changes)
        old_payload = {"action": "save", "changes": changes}
        self.conn.execute(
            "UPDATE native_operations SET fingerprint=? WHERE id=?",
            (self.native.fingerprint(old_payload), "legacy-save-id"),
        )
        self.conn.commit()
        retried = self.native.save(self.conn, self.tab(), "legacy-save-id", changes)
        self.assertEqual(retried["revision"], saved["revision"])

    def test_gateway_bidder_reads_only_own_saved_sourcing_without_writes(self):
        from fastapi.testclient import TestClient as WorkerClient
        from mailcheck.web.app import create_app
        other_book=self.native.create_book(self.conn,2,'Other workbook')
        other_tab=self.native.create_tab(self.conn,other_book,self.account_id,'Other tab')
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('No workbook','2026-10-28')")
        self.conn.commit()
        other=self.native.owned(self.conn,other_tab,self.principal)
        base=self.native.snapshot(self.conn,other)
        self.native.append(self.conn,other,'other-job',base['revision'],[['Private Company','Engineer','https://private.test/job']],work_date='2026-10-20')
        self.conn.commit()
        before=self.conn.total_changes
        headers={'x-offerpath-worker':'worker-secret','x-offerpath-viewer':'bidder','x-offerpath-bidder':'1'}
        with WorkerClient(create_app(worker_secret='worker-secret')) as client:
            result=client.get('/api/sourcing',headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual([b['bidder_id'] for b in result.json()['books']],[1])
            self.assertNotIn('accounts',result.json())
            self.assertEqual(client.get(f'/api/sourcing/tabs/{self.tab_id}',headers=headers).status_code,200)
            self.assertEqual(client.get(f'/api/sourcing/tabs/{other_tab}',headers=headers).status_code,404)
            search=client.get('/api/sourcing/search?q=Private',headers=headers)
            self.assertEqual(search.status_code,200)
            self.assertEqual(search.json()['results'],[])
            for action in ('save','append','verify','structure','import','archive','delete'):
                self.assertEqual(client.post(f'/api/sourcing/tabs/{self.tab_id}/{action}',headers=headers,json={}).status_code,403)
            self.assertEqual(client.get('/api/sourcing/filters',headers=headers).status_code,403)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM native_books').fetchone()[0],2)
        self.assertEqual(self.conn.total_changes,before)

    def test_standard_column_names_are_fixed_without_changing_saved_job_data(self):
        from mailcheck.sourcing_structure import structure
        before=self.snapshot()
        for column in before['columns']:
            if column['kind'] not in ('company','role','link','check'):continue
            with self.assertRaises(ValueError):
                structure(self.conn,self.tab(),'rename-'+column['id'],before['revision'],{'action':'rename_column','column_id':column['id'],'title':'Changed'})
        self.assertEqual(self.snapshot(),before)
