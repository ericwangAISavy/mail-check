# Reply assistant implementation plan

> **For agentic workers:** Use superpowers:executing-plans; independent UI work may run in parallel against the contracts below. Track verification per task.

**Goal:** Ship manual-only context-aware email drafting, automatic calendar availability, and a follow-up workspace.
**Architecture:** Read-only Python assistant services expose account-scoped preferences/context, deterministic availability, explicit Ollama generation, and follow-up state. React integrates a review/insert/undo workflow in the existing composer and a separate follow-up page. Send code remains separate.
**Tech Stack:** Existing FastAPI, SQLite, Ollama LLMClient, React Query, existing UI controls.
**Spec:** docs/superpowers/specs/2026-10-22-reply-assistant-design.md, superseded where the user explicitly removed interview/date-window selection.

## Global constraints
- Never automatically generate or send. No interview or date-window selection is required.
- Availability uses the next five business days, Monday–Thursday 9–17, Friday 9–16, America/Chicago, default 30-minute duration, 15-minute buffers; selectable duration.
- Same configured Ollama connection/model resolution as classification. No provider mail mutation from generation.
- Source calendars default to the current Outlook account; other calendar accounts only through explicit saved linking.
- Preserve drafts, delivery uncertainty locks, existing reply behavior and account isolation.

## Review focus
- Partial calendar collection must not produce claimed free time.
- Late generation must not overwrite newer edits or another message.
- Account sharing must not merge unrelated people's calendars or conversations.
- Pending scheduled events must not be asserted as completed interviews.
- A follow-up email or recruiter response must suppress repeat suggestions.

## Contracts
- GET /api/agent/messages/{pk}: account {id,label,email,provider}, preferences, cases [{id,label}], calendars [{id,label,email}], model_ready boolean.
- GET/POST /api/agent/preferences/{account_id}: sender_name, signature, tone (professional|warm|concise), timezone, duration_minutes, buffer_minutes, lookahead_business_days, start_hour, end_hour, friday_end_hour, calendar_account_ids, followup_business_days.
- POST /api/agent/messages/{pk}/generate: {case: availability|follow_up|thank_you|confirm|reschedule|question|decline|custom, instructions?:string, duration_minutes?:number, tone?:professional|warm|concise, refinement?:original|shorter|formal, current_draft?:string}; response {body,case,model,warnings:string[],availability:null|{ranges:[{date,start,end,label}],timezone,checked_at,calendar_labels:string[]},context_summary}.
- GET /api/agent/followups?account_id=: {items:[{id,account_id,account_label,company,role,last_interview_at,last_contact_at,elapsed_business_days,status:awaiting_response|suggested|draft_ready|snoozed|dismissed,reason,target_message_pk:number|null,snoozed_until:string|null}],accounts:[{id,label,email}],threshold_business_days:number}.
- POST /api/agent/followups/{id}: {action:snooze|dismiss|restore,days?:number}; returns {ok:true}.
- Browser navigation from follow-ups: /?view=all&days=90&message={pk}&reply=1. Opens the selected message and composer, never auto-generates.

## Task 1 — Calendar and assistant backend
Files: new mailcheck/assistant.py, mailcheck/availability.py, mailcheck/followups.py; modify calendar_events.py, sources/outlook.py, db.py, web/app.py.
- [x] Write and run failing tests for busy/free/cancelled intervals, Friday/duration/DST, incomplete calendars, account scope, generation with mocked LLM and no sending.
- [x] Implement preferences/schema and scoped context; calendar refresh covers the exact automatic window and retains showAs/isAllDay.
- [x] Implement interval subtraction and deterministic availability list, then explicit LLM drafting with grounded context and separate endpoint.
- [x] Implement follow-up discovery and snooze/dismiss state without background generation.
- [x] Run focused backend tests.

## Task 2 — Composer and follow-up UI
Files: new frontend/src/components/reply-assistant.tsx, pages/followups.tsx and tests/styles; modify reply-composer.tsx, triage.tsx, App.tsx.
- [x] Write/run failing UI tests for explicit generation, preview/insert/undo, no implicit send, error/stale result handling, follow-up navigation and controls.
- [x] Implement case chips below textarea, duration/default preferences, optional instructions, preview and grounded availability display.
- [x] Add follow-up navigation, filters, snooze/dismiss, and explicit open-reply action.
- [x] Run focused frontend tests.

## Task 3 — Integrate and verify
- [x] Review API contracts and account/permission behavior, preserve delivery protection and manual-only send.
- [x] Full backend/frontend suites; production build; desktop/mobile browser checks with mocked LLM/providers.
- [x] Update docs and perform final review. Do not commit or push until requested by user.
