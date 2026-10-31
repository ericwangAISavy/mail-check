# Interview pipeline

Open **Interview pipeline** to track individual application attempts. Separate
roles, or later attempts at the same role, have separate stable opportunity IDs.
The four main views are Needs attention, Upcoming, All active and Closed. Search
by company/role and filter by profile. Existing organization timelines remain
under **History and migration → Open legacy timeline**.

## Start tracking

Choose **Add opportunity**, select the profile and enter the company; role and job
URL are optional. The form displays the IANA timezone used for dates. Creation
switches to All active so the new opportunity remains visible even with no tasks.
Use **Review evidence** to accept a saved booking/email into a new opportunity or
link it to an existing one. These are suggestions, not verified hiring facts.
Ordinary calendar meetings are not silently promoted into hiring opportunities.
Calendar booking titles are not treated as confirmed company names.

An opportunity opens its next interview and next actions first. Expand the other
sections only when needed:
- **Edit opportunity:** confirmed stage/outcome, timezone, promised employer response
  date, pin, archive/restore. Stages can repeat or be skipped; elapsed time does not
  advance the stage or establish a hiring outcome.
- **Meetings and attendance:** provider scheduling status, actual times and explicit
  attendance. Ended means time elapsed, not attended or passed. A reschedule cannot
  erase recorded attendance; changed occurrences request review.
- **Tasks:** explicit actions/deadlines and completion, dismissal or snooze.
- **Notes and external contact:** record decisions and contact made outside OfferPath.
  An externally logged send is identified as a manual record, not delivery proof.
- **Sync status:** last successful calendar receipt and latest failure. Mail receipt
  remains Unknown until there is per-account evidence; Inbox collection does not
  prove what was sent directly through Outlook.
- **Evidence and chronological history:** retained sources and audited decisions.
  Full saved email opens through the existing message viewer.
- **Advanced corrections:** explicit link/unlink, same-profile merge and split.
  Resolve conflicting outcomes/deadlines before merging. Source and target revisions
  protect against concurrent edits. Split moves only selected evidence/tasks.

## Next-action rules

Unconfirmed ended bookings ask for attendance, not an immediate follow-up. Default
suggestions become eligible after three weekdays (or the existing configured
threshold) following confirmed attendance or explicitly recorded contact expecting
a reply. Automated acknowledgements and job alerts do not reset that clock. New
human inbound mail asks for review rather than guessing whether it needs a reply.

Confirmed response dates are independent of generic inactivity suggestions and
remain visible during a hold or when another meeting is booked. Date-only deadlines
are due during the chosen local day and become overdue after its end. On hold
pauses generic inactivity suggestions. Terminal opportunities stop automatic
follow-up suggestions; explicit tasks stay available for deliberate completion.
No pipeline action automatically sends mail or changes Outlook bookings.

## Migration and activation

The new tables are additive. Existing messages, events, sourcing rows, payments,
classifications and legacy visibility/reminder decisions are preserved. Review
legacy pins, hidden groups and reminder controls rather than guessing which role
or application attempt they belong to. Reconcile the corresponding opportunities
and explicitly dismiss each reconciled migration item. A legacy control is retained
in its old table; dismissing the review item acknowledges reconciliation only.

After creating a backup in **Admin management → Backup & restore**, use **Review
activation**. Activation is blocked until retained legacy reminder controls have
been reconciled, including those beyond the first evidence page. Activation makes
the existing follow-ups API use the same opportunity action engine and disables
legacy reminder discovery. The old timeline and its source data remain available.
Keep the backup and use the documented same-version offline restore procedure if
an installation rollback is necessary.

## Reliability and boundaries

Changes use revision checks and idempotency keys. A conflict keeps the form draft:
reload the latest version, review it, then save again. Retrying an unchanged failed
request reuses its key. Replays recheck account/source access. Disabled profiles
and bidder sessions cannot access pipeline details; workspaces remain isolated.

Calendar sync failures preserve the last successful receipt and historical links.
Deleted provider bookings can disappear from the live calendar while remaining in
opportunity history. Explicitly revoked source ownership is not exposed from cached
results. List reads batch evidence and never copy full email bodies into opportunity
snapshots. Detail history is capped at the latest 100 audit entries; underlying
history is retained. Provider revision history includes original linked booking and
attendance records, not a full audit of every intermediate remote edit.

This release uses conservative, account-scoped matching suggestions. Thread/domain
heuristics never auto-confirm links or outcomes. Live Windows, Outlook and hosting
latency still need verification on the deployment machine.
