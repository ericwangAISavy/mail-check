# Interview Pipeline Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans or independent backend/frontend tasks with explicit contracts. Track verification below.

**Goal:** Persistent, evidence-backed opportunities with a concise four-filter worklist and one next-action engine.
**Architecture:** Additive SQLite tables; retained legacy APIs/view; isolated `pipeline` modules and admin-only router. Existing calendar/mail collectors stay read-only. Stable opportunity IDs, revision checks, idempotent writes and audited source links protect decisions from sync.
**Tech stack:** Python/SQLite/FastAPI; React/TanStack Query; existing dialog/button styles.
**Spec:** `docs/superpowers/specs/2026-10-31-interview-pipeline-design.md`; user approved implementation and the compact Opportunity/Profile/Stage-status/Next-action UI.

## Global constraints

No production data changes during development. No automatic sends, stage/outcome guesses, cross-account merges, or overwrite of legacy records. Preserve admin-only access and workspace isolation. GET requests are read-only. One minor release after verification; no commit/push until requested.

## Review focus

- Same-company roles/reapplications must remain separate; shared recruiter/ATS domains cannot confirm links.
- Calendar deletion/rescheduling must preserve evidence and attendance history without implying a hiring outcome.
- Unconfirmed ended meetings and external Outlook replies must not create false follow-up/delivery claims.
- Concurrent edits and retried writes must not duplicate opportunities/actions or lose changes.
- Disabled accounts, bidder sessions and foreign-account source IDs must not expose private data.

## Contracts

Routes use `/api/pipeline` without altering `/api/interview-processes` legacy contracts.
All mutation bodies include `operation` UUID; edits also include integer `revision`.

- GET `/api/pipeline?view=active|attention|upcoming|closed|archived&q=&account_id=` -> `{opportunities,accounts,review_count,activated,legacy_available:true}`.
- POST `/api/pipeline` -> create `{operation,account_id,company,role?,job_url?,application_ref?,timezone?}`.
- GET `/api/pipeline/{id}` -> `{opportunity,events,messages,tasks,history}`.
- POST `/api/pipeline/{id}` -> `{operation,revision,changes:{company?,role?,job_url?,application_ref?,status?,stage?,pinned?,archived?,timezone?,response_due?}}`.
- GET `/api/pipeline/review` -> `{items:[{key,kind,account_id,account_label,title,occurred_at,company?,role?,reason,legacy_key?,legacy_pinned?,legacy_hidden?}],total}`. Optional `q`, `account_id`, `limit`, `offset`.
- POST `/api/pipeline/review` -> `{operation,action:'accept'|'dismiss'|'link',key,company?,role?,target_id?,revision?}`. Accept creates an opportunity; link requires target revision; returns `{opportunity?}`.
- POST `/api/pipeline/{id}/evidence` -> `{operation,revision,action:'link'|'unlink',kind:'event'|'message',source_id:int}`.
- POST `/api/pipeline/{id}/attendance` -> `{operation,revision,event_id,attendance:'Unconfirmed'|'Attended'|'Did not attend',start_at}` (attendance tied to reviewed occurrence).
- POST `/api/pipeline/{id}/tasks` -> `{operation,revision,title,due_at?,kind?,responsibility?}`.
- POST `/api/pipeline/{id}/tasks/{task_id}` -> `{operation,revision,state:'open'|'done'|'dismissed'|'snoozed',snoozed_until?}`; synthetic recommendation IDs support persistent dismiss/snooze.
- POST `/api/pipeline/{id}/contact` -> `{operation,revision,at,expects_reply:bool,note}` explicitly manually logged external contact.
- POST `/api/pipeline/{id}/notes` -> `{operation,revision,text}`.
- POST `/api/pipeline/{id}/merge` -> `{operation,revision,source_id,source_revision}`; retained target with audited redirect, blocked conflicting outcomes unless explicitly resolved.
- POST `/api/pipeline/{id}/split` -> `{operation,revision,company,role?,event_ids:[],message_ids:[],task_ids:[]}` -> new opportunity. Sources stay same account.
- POST `/api/pipeline/activate` -> explicit migration activation; new actions replace legacy follow-up discovery only after confirmation. Preserve legacy snooze/dismiss mappings; ambiguous ones remain review evidence.

Opportunity output: `id,revision,account_id,account_label,account_email,company,role,job_url,application_ref,status,stage,pinned,archived,timezone,response_due,next_interview,next_action,actions,last_contact_at,updated_at`.
Action output: `id,title,kind,responsibility,due_at,state,reason,suggested,target_message_pk?`.
Event output: `id,title,start_at,end_at,stage,provider_state,temporal,attendance,attendance_needs_review,meeting_url,location`.
Message output: `id,title,occurred_at,from_addr,category,summary`; full body stays in existing reader.
Statuses: Active, On hold, Offer received, Accepted, Rejected, Withdrawn, Offer declined, Role closed.
Stage: Not confirmed + existing interview stage catalog. Unknown company/role display explicit placeholders.

## Tasks

### 1. Persistent model and evidence decisions
- [x] Write failing isolated SQLite tests for identity, revisions, retries, account/source ownership, archived/terminal state, attendance, merge/split and audit.
- [x] Create `mailcheck/interview_pipeline.py`, additive `SCHEMA`, transactional CRUD/link operations and serialization. Root integrates schema in `db.py`.
- [x] Create `mailcheck/pipeline_tracking.py` for review/migration suggestions and shared next actions, with no per-opportunity provider calls.
- [x] Run the focused tests; preserve legacy tables and methods.

### 2. Admin APIs and migration
- [x] Create `mailcheck/web/pipeline_routes.py`; strict bodies, account ownership, revision conflicts 409, missing records 404, bidder denial 403.
- [x] Install router in `web/app.py`, integrate `SCHEMA` with one user_version bump.
- [x] Add API tests for workspaces/bidder denial, side-effect-free previews, failure/retry and detail/history.
- [x] Use one engine for new list/detail/actions and activated follow-ups; retain legacy behavior before explicit activation.

### 3. Compact UI
- [x] Create `frontend/src/pages/interview-pipeline.tsx` + focused detail component/CSS/types. Change App route to new page while keeping the legacy timeline accessible by deliberate link.
- [x] Four filters (Needs attention, Upcoming, All active, Closed), search, optional profile, Add opportunity and Review evidence. Archive is secondary.
- [x] Detail exposes next interview/actions first; notes/history/link corrections behind progressive disclosure. Use labelled status colors and no age/milestone legends.
- [x] Implement accessible error/loading/empty states, conflict-safe drafts, attendance, tasks, evidence review and legacy preview.
- [x] Add frontend tests for filtering, creation/detail, evidence acceptance, failed edits, unknown values and outcome/attendance separation.

### 4. Verification and release
- [x] Reviewer checks against approved spec; resolve material gaps before completion.
- [x] Run full backend and frontend suites. Build frontend after any backend test serving generated assets has completed.
- [x] Add minor release and documentation, rebuild bundled assets, run release check and diff check.
- [x] Record actual limits and validation; leave changes uncommitted until user asks.

## Completion evidence

See `docs/superpowers/verification/2026-10-31-interview-pipeline.md`.
The implementation remains uncommitted, following the session workflow.
