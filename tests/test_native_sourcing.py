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
        self.assertEqual(len(self.snapshot()["columns"]), 3)

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
        self.assertEqual(len(result["rows"]), 2001)
        self.assertEqual(result["rows"][2000][0]["value"], "Company 1999")
