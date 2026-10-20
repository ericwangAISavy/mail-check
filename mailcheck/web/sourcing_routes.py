"""Native sheet endpoints. Resolve ownership before any read, export or mutation."""

from typing import Annotated, Literal
import sqlite3
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .. import db, native_sourcing as sheets, sourcing_csv, payments

Text = Annotated[str, Field(max_length=50_000)]
Key = Annotated[str, Field(min_length=1, max_length=64)]


class Book(BaseModel):
    bidder_id: int
    title: str = Field(default="Applications", min_length=1, max_length=100)


class Tab(BaseModel):
    account_id: int
    title: str = Field(default="", max_length=100)


class Style(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bold: bool | None = None
    italic: bool | None = None
    align: Literal["left", "center", "right"] | None = None
    wrap: bool | None = None


class Change(BaseModel):
    row_id: Key
    column_id: Key
    expected_version: int = Field(ge=0)
    value: Text | None = None
    style: Style | None = None

    @model_validator(mode="after")
    def content(self):
        if self.value is None and self.style is None:
            raise ValueError("Provide a cell value or formatting change.")
        return self


class Operation(BaseModel):
    operation: uuid.UUID
    work_date: str = Field(default="all", max_length=10)


class Save(Operation):
    compact_rows: bool = False
    changes: list[Change] = Field(min_length=1, max_length=10_000)


class Versioned(Operation):
    revision: str = Field(min_length=1, max_length=32)


class Append(Versioned):
    rows: list[list[Text]] = Field(min_length=1, max_length=10_000)


class Structure(Versioned):
    action: Literal[
        "insert_rows",
        "delete_rows",
        "add_column",
        "delete_column",
        "rename_column",
        "resize_column",
        "move_date",
    ]
    at_row_id: Key | None = None
    ids: list[Key] = Field(default_factory=list, max_length=1000)
    count: int = Field(default=20, ge=1, le=1000)
    column_id: Key | None = None
    title: str = Field(default="", max_length=100)
    width: int = Field(default=220, ge=70, le=1200)


class Import(Versioned):
    text: str = Field(min_length=1, max_length=2_000_000)
    mode: Literal["append", "replace"] = "append"
    has_header: bool = True


class DeleteTab(BaseModel):
    revision: str = Field(min_length=1, max_length=32)


class Archive(BaseModel):
    archived: bool


def install(app, frontend_page, secure_cookies):
    router = APIRouter()

    def principal(req):
        return {"role": req.state.role, "bidder_id": req.state.bidder_id}

    def admin(req):
        if req.state.role != "admin":
            raise HTTPException(403, "Admin access required.")

    def owned(conn, tab_id, req):
        try:
            return sheets.owned(conn, tab_id, principal(req))
        except PermissionError:
            raise HTTPException(404, "Sheet not found.")

    def mutation(tab_id, req, function):
        with db.session() as conn:
            tab = owned(conn, tab_id, req)
            try:
                return function(conn, tab)
            except FileExistsError as exc:
                raise HTTPException(409, str(exc))
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    @router.get("/sourcing")
    def page():
        return frontend_page()

    @router.get("/api/sourcing")
    def index(req: Request):
        with db.session() as conn:
            is_admin = req.state.role == "admin"
            # Older bidders predate automatic workbook creation. Reconcile only
            # missing workbooks so the picker always represents active bidders.
            conn.execute(
                "INSERT OR IGNORE INTO native_books(bidder_id,title) "
                "SELECT p.id,'Applications' FROM bidders p WHERE p.removed_at IS NULL "
                "AND (? OR p.id=?) AND NOT EXISTS ("
                "SELECT 1 FROM native_books b WHERE b.bidder_id=p.id)",
                (is_admin, req.state.bidder_id),
            )
            books = [
                dict(r)
                for r in conn.execute(
                    "SELECT b.*,p.name FROM native_books b JOIN bidders p ON p.id=b.bidder_id WHERE p.removed_at IS NULL AND (? OR b.bidder_id=?) ORDER BY p.name",
                    (is_admin, req.state.bidder_id),
                )
            ]
            for book in books:
                book.pop("legacy_book_id", None)
                book["tabs"] = [
                    {**dict(r), "header_row": 1}
                    for r in conn.execute(
                        "SELECT t.id,t.account_id,t.account_label,COALESCE(a.label,t.title) AS title,t.updated_at AS refreshed_at,t.archived FROM native_tabs t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.book_id=? AND (? OR t.archived=0) ORDER BY t.id",
                        (book["id"], is_admin),
                    )
                ]
            result = {"books": books}
            if is_admin:
                result["bidders"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,name,login_enabled FROM bidders WHERE removed_at IS NULL ORDER BY name"
                    )
                ]
                result["accounts"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT id,email,label FROM accounts WHERE enabled=1"
                    )
                ]
                day = payments.today().isoformat()
                result["assignments"] = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT bidder_id,account_id FROM bidder_assignments WHERE start_date<=? AND (end_date IS NULL OR end_date>=?)",
                        (day, day),
                    )
                ]
            return result

    @router.post("/api/sourcing/books")
    def create_book(body: Book, req: Request):
        admin(req)
        with db.session() as conn:
            try:
                return {"id": sheets.create_book(conn, body.bidder_id, body.title)}
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    @router.post("/api/sourcing/books/{book_id}/tabs")
    def create_tab(book_id: int, body: Tab, req: Request):
        admin(req)
        with db.session() as conn:
            book = conn.execute(
                "SELECT * FROM native_books WHERE id=?", (book_id,)
            ).fetchone()
            if not book:
                raise HTTPException(404, "Workbook not found.")
            day = payments.today().isoformat()
            if not conn.execute(
                "SELECT 1 FROM bidder_assignments s JOIN accounts a ON a.id=s.account_id WHERE s.bidder_id=? AND s.account_id=? AND a.enabled=1 AND s.start_date<=? AND (s.end_date IS NULL OR s.end_date>=?)",
                (book["bidder_id"], body.account_id, day, day),
            ).fetchone():
                raise HTTPException(
                    400, "Assign this profile to the bidder on Bidder payments first."
                )
            try:
                return {
                    "id": sheets.create_tab(conn, book_id, body.account_id, body.title)
                }
            except sqlite3.IntegrityError:
                raise HTTPException(
                    409, "This profile already has a sheet. Restore it if archived."
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    @router.post("/api/sourcing/tabs/{tab_id}/archive")
    def archive(tab_id: int, body: Archive, req: Request):
        admin(req)
        with db.session() as conn:
            owned(conn, tab_id, req)
            conn.execute(
                "UPDATE native_tabs SET archived=?,revision=revision+1 WHERE id=?",
                (body.archived, tab_id),
            )
        return {"ok": True}

    @router.post("/api/sourcing/tabs/{tab_id}/delete")
    def delete_tab(tab_id: int, body: DeleteTab, req: Request):
        admin(req)
        return mutation(tab_id, req, lambda conn, tab: sheets.delete_tab(conn, tab, body.revision))

    @router.get("/api/sourcing/tabs/{tab_id}")
    def snapshot(tab_id: int, req: Request):
        with db.session() as conn:
            return sheets.snapshot(conn, owned(conn, tab_id, req))

    @router.post("/api/sourcing/tabs/{tab_id}/save")
    def save(tab_id: int, body: Save, req: Request):
        return mutation(
            tab_id,
            req,
            lambda conn, tab: sheets.save(
                conn,
                tab,
                str(body.operation),
                [c.model_dump(exclude_none=True) for c in body.changes],
                work_date=body.work_date,
                compact_rows=body.compact_rows,
            ),
        )

    @router.post("/api/sourcing/tabs/{tab_id}/structure")
    def structure(tab_id: int, body: Structure, req: Request):
        return mutation(
            tab_id,
            req,
            lambda conn, tab: sheets.structure(
                conn,
                tab,
                str(body.operation),
                body.revision,
                body.model_dump(
                    exclude={"operation", "revision"}
                    | ({"work_date"} if body.work_date == "all" else set()),
                    exclude_none=True,
                ),
            ),
        )

    @router.post("/api/sourcing/tabs/{tab_id}/verify")
    def verify(tab_id: int, body: Versioned, req: Request):
        from .. import sourcing_verification
        return mutation(tab_id, req, lambda conn, tab: sourcing_verification.verify(
            conn, tab, str(body.operation), body.revision, body.work_date))

    @router.post("/api/sourcing/tabs/{tab_id}/append")
    def append(tab_id: int, body: Append, req: Request):
        return mutation(
            tab_id,
            req,
            lambda conn, tab: sheets.append(
                conn,
                tab,
                str(body.operation),
                body.revision,
                body.rows,
                work_date=body.work_date,
            ),
        )

    @router.post("/api/sourcing/tabs/{tab_id}/import")
    def import_csv(tab_id: int, body: Import, req: Request):
        return mutation(
            tab_id,
            req,
            lambda conn, tab: sourcing_csv.import_rows(
                conn,
                tab,
                str(body.operation),
                body.revision,
                text=body.text,
                mode=body.mode,
                has_header=body.has_header,
                work_date=body.work_date,
            ),
        )

    @router.get("/api/sourcing/tabs/{tab_id}/export")
    def export_csv(tab_id: int, req: Request, work_date: str = "all"):
        with db.session() as conn:
            tab = owned(conn, tab_id, req)
            try:
                content = sourcing_csv.export_rows(conn, tab, work_date=work_date)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            suffix = "" if work_date == "all" else "-" + work_date
            return Response(
                "\ufeff" + content,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="jobs-{tab_id}{suffix}.csv"'
                },
            )

    @router.get("/api/sourcing/search")
    def search(req: Request, q: str = "", account: int | None = None):
        with db.session() as conn:
            tabs = conn.execute(
                "SELECT t.*,b.bidder_id,p.name FROM native_tabs t JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id WHERE p.removed_at IS NULL AND t.archived=0 AND (? OR b.bidder_id=?) AND (? IS NULL OR t.account_id=?)",
                (req.state.role == "admin", req.state.bidder_id, account, account),
            ).fetchall()
            results = []
            for tab in tabs:
                data = sheets.snapshot(conn, dict(tab))
                fields = {
                    c["kind"]: i for i, c in enumerate(data["columns"]) if c["kind"]
                }
                for i, row in enumerate(data["rows"][1:], 1):
                    values = [
                        row[fields[k]]["value"] if k in fields else ""
                        for k in ("company", "role", "link")
                    ]
                    haystack = " ".join(
                        [
                            *(str(c["value"]) for c in row),
                            tab["name"],
                            data["title"],
                            tab["account_label"],
                        ]
                    ).casefold()
                    if (
                        q.strip()
                        and any(str(c["value"]) for c in row)
                        and all(word in haystack for word in q.casefold().split())
                    ):
                        results.append(
                            {
                                "tab_id": tab["id"],
                                "bidder": tab["name"],
                                "profile": data["title"],
                                "account_id": tab["account_id"],
                                "row": i,
                                "row_id": data["row_ids"][i],
                                "work_date": data["row_dates"][i],
                                "company": values[0],
                                "role": values[1],
                                "link": values[2],
                                "refreshed_at": tab["updated_at"],
                            }
                        )
            return {"results": results[:500], "cached": False, "incomplete": False}

    app.include_router(router)
