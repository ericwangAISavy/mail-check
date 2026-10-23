# Reply assistant and follow-ups

Implementation authorized. The final user correction removes required interview and date-window selection.

## Reply workflow

The existing reply composer offers Availability, Follow up, Thank you, Reschedule, Confirm, Question, Decline and Custom. Clicking a case explicitly generates a preview. The user reviews it, optionally regenerates or changes wording, then chooses Use draft. Insertion can be undone while the editor still contains the inserted text. Generation never sends, marks a message done, changes calendar events or runs automatically. Existing Send and Send & Done remain the only delivery actions. Delivery uncertainty locks still apply.

Context is the selected message, same-account thread, relevant sent replies and linked calendar events. Email content is untrusted prompt data. Never assume a scheduled past interview actually occurred. Rescheduling can use neutral wording when a reliable appointment is not identifiable. Reuse the classification LLM connection and loaded model, with a shared job lock. No new model provider or credentials.

## Availability

Use saved defaults automatically: next five business days including remaining usable time today, Chicago timezone, Monday–Thursday 9–5, Friday 9–4, 30-minute meeting minimum, 15-minute buffers. Meeting length supports 30, 45, 60 and custom minutes. No per-reply date-window or interview picker.

Read live Outlook calendars, including expanded recurring occurrences and all-day entries. Cancelled and explicitly Free entries do not block time; other entries do. Combine every enabled Outlook account’s live calendar with saved events from all accounts. The user confirmed that all accounts share one personal schedule. Calendar selection is automatic, including when replying from IMAP. An incomplete provider scan must fail availability generation. Rescheduling can instead generate a neutral request without offering times, with a warning.

Calculate every remaining qualifying range deterministically after subtracting merged buffered busy intervals. Include buffer overlaps at query boundaries and handle DST. Insert literal verified ranges in generated prose. Wording instructions do not change calculated ranges; the UI and preview explain this limitation. Calendar data, defaults and meeting duration control ranges. Show calendar sources and refresh time. Sender name, signature, tone, calendar links and duration are saved per account. Preferences are removed with the account. Generated previews are stored with original message/account identity checks and can be recovered explicitly.

## Follow-ups

Follow-up actions live at the end of each Interview processes timeline. Clicking opens the relevant account-scoped saved email and reply composer without generating or sending. Prefer a human contact in the linked conversation, including original invitations that predate the first event. If no saved reply target exists, explain the limitation.

After a successfully delivered reply following the latest process activity, highlight the endpoint and label as Follow-up sent. Pending, unknown, failed or partially delivered sends never count as complete. Match delivery ledger entries by account, message PK and original message ID. New inbound activity or a later meeting resets the indication. Refresh process queries after sending or reconciling delivery status. Provide a Back to interview processes link in the email view.

The separate Follow-ups navigation entry is removed; its former URL redirects to Interview processes. Existing saved follow-up state remains stored. Generation and delivery remain explicit actions.

## Verification

Cover deterministic availability, Friday and DST, elapsed time, free/cancelled/duplicate events, missing end times, live query boundaries and linked calendars. Verify no sends or queue mutations, account-scoped context, saved-preview identity guards, account deletion cleanup, model errors and shared-job contention. Run existing backend/frontend regression suites and production build.
