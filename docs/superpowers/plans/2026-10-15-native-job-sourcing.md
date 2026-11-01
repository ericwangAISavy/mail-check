# Native Job Sourcing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax.

**Goal:** Replace Google synchronization with mail-check-owned spreadsheet workbooks.
**Architecture:** Add native SQLite tables with stable row/column IDs, sparse versioned cells and atomic idempotent operations. Preserve legacy tables and migrate cached rows once. Reuse the grid, bidder authentication and page shell, with native structure/import controls and search.
**Tech Stack:** SQLite, FastAPI/Pydantic, React 19, react-data-grid, existing test frameworks.
**Spec:** `docs/superpowers/specs/2026-10-15-native-job-sourcing-design.md`

## Global Constraints

- Admin reads/writes all; bidders only their own sheets; authorize before reads, exports or writes.
- No Google calls, credentials or setup in the active sourcing workflow. Preserve legacy files/tables/secrets.
- Stable row/column IDs, atomic version checks, operation UUIDs; no positional writes after sorting.
- Keep existing email/calendar/payment behavior. Native data is separate from email retention.
- Support rectangular TSV, CSV preview/append/confirmed replace, 10,000 cells per write/import, up to 101 columns and 100,000 rows.

## Review Focus

1. External/admin sorting or row deletion while another bidder edits: stable IDs and version conflicts prevent overwriting another job.
2. Retry after an acknowledged append/import: operation IDs prevent duplicate jobs across process restarts.
3. Legacy formula/hyperlink/missing cache: preserve available display data and actual job URL; show conversion warnings.
4. Dirty sheets, browser history and background refresh: preserve pending values and clear unsafe positional undo.
5. CSV replace, sheet export and structure mutations: enforce owner scope and transaction-wide validation.

## Task 1: Native storage, migration and checked cell writes

**Files:** new `mailcheck/native_sourcing.py`; modify `mailcheck/db.py`; new `tests/test_native_sourcing.py`.
**Interfaces:** `migrate(conn)`, `owned(conn,tab_id,principal)`, `snapshot(conn,tab)`, `save(conn,tab,operation,changes)`; stable `row_id`, `column_id`, `expected_version` on each change. Snapshot includes column definitions, row IDs, cell versions, tab/structure revisions and migration notices.
- [x] Write/run failing tests for native creation, cached migration, literal formulas/hyperlinks, idempotency and independent vs same-cell edits.
- [x] Add native schema and automatic idempotent migration; keep legacy data. Implement atomic ownership-aware saves and durable operation records.
- [x] Run native, auth, payment and migration checks. Expected: pass.

## Task 2: Native API, structure, import/export and search

**Files:** replace `mailcheck/web/sourcing_routes.py`; new `mailcheck/sourcing_csv.py`; update sourcing API tests.
**Interfaces:** existing `/api/sourcing` and tab/save/append/search paths become native. Add `/structure`, `/import`, `/export`; admin creates workbook/profile tabs, owner edits cells/rows/custom columns. Search returns stable `row_id` and profile/account context.
- [x] Write/run failing real SQLite/API tests for cross-bidder denial, stale structural edits, append retry, row/column operations and atomic CSV validation/replacement.
- [x] Implement native-only routes, current assignment checks, filtered search, literal/escaped CSV export, row structure and cell formatting. Remove active OAuth callbacks/Google routes.
- [x] Run backend regression suite. Expected: all pass without Google access.

## Task 3: Spreadsheet workspace

**Files:** `frontend/src/lib/sourcing.ts`, `components/sourcing-grid.tsx`, `components/sourcing-settings.tsx`, `pages/sourcing.tsx/.css`; new focused sheet editor/import/control components as useful.
**Interfaces:** local display indices map to stable IDs before requests; cell versions accompany changes; formatting is separate from value; structure operations require tab revision.
- [x] Write/run failing frontend tests for native setup, stable-ID save payloads, sort/filter/find, CSV parsing/import preview and conflict/draft recovery.
- [x] Replace Google setup with workbook/profile management and existing password controls. Add toolbar for row/column actions, formatting, sort/filter/find and CSV import/export. Preserve keyboard/clipboard and guarded autosave/undo.
- [x] Integrate stable search row links and interview profile context. Run frontend tests and build. Expected: pass.

## Task 4: Verification and documentation

**Files:** `docs/JOB_SOURCING.md`, README and verification notes; bundled frontend.
- [x] Document native migration notices, CSV behavior, permissions, limits and SQLite backup/restore.
- [x] Run full Python, standalone smoke, frontend and production build checks.
- [x] Browser-test admin/two bidders: paste/edit/save, formatting, sort/filter/find, structure, import/export, conflict/navigation, search and desktop/mobile fit.
- [x] Obtain one fresh whole-feature review; reproduce/fix Important findings; rerun affected/full checks.
- [x] Commit verified work locally; do not merge or push without a request for this change.

## Execution result

Completed inline. See [verification and review disposition](../verification/2026-10-15-native-job-sourcing.md) for final test counts, browser evidence and implementation decisions.
