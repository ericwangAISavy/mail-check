# Interview pipeline: reliable opportunity tracking

Status: implementation approved by the user after design and concise UI review.
Date: October 31, 2026 (America/Chicago).

## Purpose and success

Help an admin answer, for every interview opportunity: which profile and job is
this, what is confirmed, what happens next, who needs to act, and by when?
A user should identify those facts within ten seconds without interpreting a
color legend, counting dots, or guessing what an elapsed meeting means.

This proposal builds on existing stored calendar events, Inbox mail and latest
classifications, sourcing jobs, local replies, notes, account identities and
workspace permissions. It does not claim access to production mailbox contents.

## Findings from current code

- Processes are derived from organization/domain + account, not persistent
  application opportunities. Multiple roles, attempts or clients of a recruiter
  can mix; changed source metadata can move a process and its apparent identity.
- A manual company name matches any word/number in its name against broad text.
  Generic names can pull unrelated mail into a process.
- Native calendar collection intentionally accepts all bookings, not exclusively
  interviews. Generic meetings must not automatically become hiring opportunities.
- An ended event is displayed as Completed without proof of attendance or success.
- The UI needsFollowUp rule flags a process once all milestones are past; backend
  process follow-up decoration and the separate follow-ups module use different
  evidence/eligibility rules. These can disagree about whether action is due.
- Earlier mail is hidden before the first calendar event. A declined/closed role
  has no durable opportunity outcome, and live event visibility can change history.
- Outlook collection reads Inbox. Local mail_replies tracks sends through
  OfferPath, not arbitrary Outlook Sent Items. Missing local delivery is not proof
  the user never replied elsewhere.
- Existing stage names, stable source records, local manual-field protection,
  idempotent reply operations, account scoping and bulk calendar reads are useful
  foundations to preserve.

## Approaches considered

1. Improve the existing organization timeline: smallest migration, but still mixes
   applications and relies on unstable domain/name grouping.
2. Persistent opportunities with evidence-assisted linking: explicit identity,
   explainable automation, corrections that survive sync. Recommended.
3. Fully automatic stage/outcome inference: less user input, but unreliable when
   mail is ambiguous, calendars contain unrelated meetings, or replies are external.

Approach 2 is the proposed default, not a recorded user approval. The previous
plan's company + role key is refined below: repeated applications need distinct
identities even when profile, company and role are identical.

## 1. Stable opportunities

Each opportunity has its own opaque, immutable ID within its workspace and a
primary profile/account. Company, role, job/requisition/application identifiers,
job URL and recruiter contacts are editable attributes.
Company + role is not a unique key. A later reapplication can be a new opportunity.
Distinct roles at one company remain separate by default. Unknown company/role
stays visibly unknown until resolved; never fabricate either from a meeting title.

For the first release, account remains the existing profile boundary. No new
candidate identity system, cross-workspace linking, or automatic cross-account
merging is proposed. The responsible admin is the existing workspace admin;
new internal assignee/team administration is outside the first release. Display
existing profile identity without changing sourcing assignments or bidder payments.

Create manually, from a sourcing job, or by accepting a proposed opportunity from
linked interview evidence. An availability request can start tracking before a
meeting is booked. Imported calendar meetings without hiring evidence remain
unassigned evidence rather than creating active interview opportunities.

Persist source links and manual decisions. A sync must not silently move a
confirmed event/message to a different opportunity or rewrite a confirmed company.

## 2. Facts, suggestions and confirmation

Calendar is authoritative for provider booking times, locations, links and
cancellations; it is not authoritative for attendance or hiring outcome. Existing
local corrections retain their precedence and a visible explanation.

Matching order:
1. Explicit user assignment or previously confirmed source relationship.
2. Exact account-scoped application/requisition identity or confirmed job link,
   only when it identifies one compatible application attempt; reused requisitions
   or links across attempts require review.
3. A thread/reply relationship anchored to confirmed evidence, provided there is
   no contradictory application/role evidence; otherwise propose a link.
4. Company aliases, sender domains, recruiter contacts and title text are
   suggestions requiring review when identity is uncertain.

Use existing classifications as supporting evidence, not as unquestioned facts.
Recruiting agencies, shared ATS/scheduling domains, personal email providers and
short/generic company names cannot establish an opportunity on their own. No
any-word manual-name matching for new confirmed links. Explain each suggestion
with its source and reason; no fabricated probability percentages.

An admin can accept, reject or move a link. Rejected suggestions must stay
rejected for the same evidence unless materially new evidence arrives. Unmatched
items remain separate and reviewable; do not aggregate every unknown into one
fictional company process. An event may be relevant to multiple opportunities
only through explicit confirmation; deduplicate its display within each one.

## 3. Separate opportunity, stage and booking status

Opportunity status: Active, On hold, Offer received, Accepted, Rejected, Withdrawn,
Offer declined, or Role closed. Accepted/Rejected/Withdrawn/Offer declined/Role
closed are terminal; Offer received still needs a candidate decision. Reopening
is explicit and preserves the prior status history. Archive is a reversible
visibility preference independent of outcome, not deletion or rejection.

Interview stages reuse the existing catalog (recruiter/phone screen, technical,
coding, system design, behavioral, hiring manager, onsite, final, other). Add a
clear Not confirmed state. Repeated, skipped and parallel stages are permitted.
Current stage is confirmed, not guessed from the last email or passage of time.
Show next booked interview/stage separately so future bookings do not imply a
round was passed. No arbitrary numeric pipeline completion percentage.

Keep provider booking state and attendance separate:
- Provider booking state: Scheduled, Cancelled, or Removed from provider, with
  reschedules preserved as revisions/history rather than losing the prior time.
- Temporal display: Upcoming, In progress, or Ended, computed from actual times.
- Attendance: Unconfirmed, Attended, or Did not attend, explicitly recorded against
  the occurrence and time interval reviewed by the user.

Ended must not mean attended, passed or completed successfully. A provider update
cannot overwrite attendance. If an already-reviewed occurrence moves into a new
slot, retain the old attendance record and request review before carrying it to
that slot. Calendar cancellation changes booking state, not opportunity outcome.
Assessment tasks have their own completion/due date rather than pretending to be
calendar interviews.

Offers/rejections found in clearly linked mail can propose an opportunity update;
an admin confirms consequential outcomes. Acceptance requires an explicit admin
decision; linked evidence supports that decision but does not apply it automatically.

## 4. One next-action engine

Replace the conflicting UI/process/follow-up eligibility rules with one shared
backend computation consumed by pipeline, follow-ups and badges. Store explicit
tasks and deadlines; derive recommendations without silently persisting decisions.

Supported actions: respond/provide availability, attend/prepare for a meeting,
complete an assessment, record attendance/result, review an employer update, and
follow up. Each has a reason, evidence link, responsible party (you/employer/
unknown), optional due date and state. Responsibility is stated only when the
evidence supports it. Keep multiple actions; highlight the most urgent one with
its reason rather than concealing secondary deadlines. Default ordering puts
explicit overdue/today deadlines and today's meetings first (ordered by deadline),
then other dated tasks, required responses/attendance confirmation, suggested
follow-ups and unmatched-evidence review. Display the other outstanding actions.

An ended interview first suggests recording attendance/result. A confirmed
employer response deadline can trigger a follow-up after it passes. With no agreed
deadline, a configurable suggestion (proposed default: three business days after
confirmed attendance or relevant contact) says Suggested follow-up, not Overdue.
The follow-up clock has explicit rules:
- Automated application acknowledgements, job alerts and generic notifications do
  not restart an employer-response clock. Calendar updates adjust scheduling facts
  and tasks, not the hiring outcome or a promised response deadline.
- Start a default employer-waiting clock after confirmed attendance, or a confirmed
  human outbound contact explicitly marked as expecting a response. A thank-you,
  draft, failed send or arbitrary manual note does not automatically reset it.
- A newer confirmed human inbound response ends the prior unanswered-contact
  recommendation. If it requests action, prioritize the response/task; if its intent
  is unclear, create Review employer update rather than guessing who must act.
- An explicitly confirmed employer response date overrides the default interval.
  A new confirmed interview suppresses a generic inactivity follow-up for that
  round, while preserving independent explicit tasks and deadlines.
- Suggestions may use existing classification/thread evidence, but consequential
  or ambiguous intent remains reviewable. Do not require hand-labeling every email.

Initial business-day support means weekdays in the chosen opportunity/workspace
IANA timezone; do not claim holiday awareness. Date-only deadlines are due during that local day
and become overdue after its end; timed deadlines use their exact instant.
Users can set exact dates, snooze,
complete or dismiss actions with reasons. Employer updates, reschedules and new
confirmed rounds recompute recommendations without deleting explicit tasks.

Terminal opportunities suppress automatic follow-up suggestions. On hold pauses
inactivity-based recommendations; explicit deadlines and existing booked meetings
remain visible until separately changed. A missing future meeting is not itself
proof a reply is due, especially when calendar sync failed or coverage is stale.

Drafting is optional; review recipients and message before sending. No auto-send.
Never choose a no-reply/shared ATS address merely because it is newest. If no
confirmed reply target exists, show Choose contact. Delivery-backed local sends
are labelled Sent through OfferPath. Replies made directly in Outlook are unknown
unless the user records them; a manually recorded external contact is labelled as
such and is not a provider delivery receipt.

## 5. History and everyday usefulness

The summary exposes identity, confirmed status/stage, next interview, next action,
responsibility, last meaningful contact and sync freshness. Detailed history is
secondary: dated meetings, relevant inbound mail, OfferPath sends, manually logged
external contact, notes, tasks, status changes and corrections with evidence.
Retain relevant application mail before the first interview.

Avoid using process age as a proxy for success, failure or urgency. Color should
support a labelled status/action, not require several competing legends. Review
unassigned evidence separately from active opportunities. The main tracking
questions are Needs my action, Upcoming, Waiting, Offers and Closed; a full history
or date filter must explain its scope and never imply unmatched activity is gone.

This section specifies information priorities, not an approved screen layout.
A visual proposal is a separate next step after agreement on these rules.

A calendar event removed from Outlook may disappear from the live calendar but
remains referenced in opportunity history with provider deletion noted; it does
not delete the opportunity. Source visibility, disabled accounts and local removals
must be distinguished from deletion of historical evidence. Permission revocation
always takes precedence over retaining a visible link to private content.

## 6. Reliability, performance and migration

- Persist opportunity revisions, links, actions and an append-only change history.
  Use transactions, idempotent operations and conflict detection for concurrent
  admins. Audit user decisions separately from provider revisions.
- Preserve per-workspace isolation and existing owner/admin/bidder permissions.
  Pipeline stays admin-only in this proposal. Do not expose new bidder access.
- Reuse existing collectors and the stored message/event records; no extra provider
  call per opportunity, no repeated full-body scans for ordinary page views, and
  no rebuild of all opportunity history on each poll. Batch reads; paginate history.
- Show per-account last successful calendar/mail sync and current errors. Missing
  or partial collection is not an empty successful snapshot. Never close an
  opportunity because a request failed or an item fell outside a sync window.
- Keep UTC instants and IANA display/reminder zones; test DST and midnight edges.
- Add schema without overwriting messages, classifications, events, corrections,
  sourcing/payments data, credentials, existing pins or hidden-process choices.
- Start migration as a dry-run preview of proposed opportunities and links. Legacy
  auto-groupings are suggestions, not newly confirmed facts. Preserve old views
  until reconciliation is verified. Do not hard-delete or silently merge records.
- Existing pins/hidden choices need an explicit mapping to opportunities; ambiguous
  mappings remain in the preview. Offer backup and a documented rollback before
  switching the primary view. Backup restore uses its existing same-version rule.

## Delivery order

1. Stable opportunity identity, persisted links, audit/revisions, permissions and
   migration preview. Establish matching corrections before adding automation.
2. Confirmed statuses, attendance, tasks and one shared next-action engine.
3. Focused tracking experience and evidence detail, replacing confusing age and
   unconditional follow-up signals. Then offer visual options for approval.
4. Verified migration, performance benchmarks and staged activation. Broader
   automation can be evaluated later against reviewed linking decisions.

## Acceptance scenarios

- Two roles at the same company, and a later attempt at the same role, stay separate.
- A recruiter working for several clients cannot mix those clients' pipelines.
- A shared ATS domain, generic company name or ordinary calendar meeting cannot
  silently create/link an active interview opportunity.
- Cancelled/rescheduled meetings retain identity/history; cancellation is not
  rejection, and an ended meeting does not count as attended or passed.
- Scheduling mail can start tracking before a booking; earlier relevant mail stays.
- A rejection for one role cannot close another role's opportunity.
- Multiple rounds on the same day and parallel stages remain distinguishable.
- Direct Outlook replies are not falsely marked missing or delivery-confirmed.
- No immediate follow-up solely because a meeting ended; terminal cases stop
  automatic follow-up; legitimate outstanding tasks are not silently completed.
- Failed/partial sync shows stale evidence without removing the opportunity or
  making an unsupported next-action claim.
- Corrections, rejected suggestions, pins and archived state survive repeated syncs.
- Two simultaneous admin edits produce a recoverable conflict, not lost updates.
- No cross-profile/workspace evidence leak; history details recheck authorization.
- Large histories use batched reads and bounded detail pages with measured latency.

## Decisions proposed, not yet approved

Persistent opportunities; separate roles/attempts by default; existing account as
profile boundary; confirmed consequential outcomes; admin-only access; weekday-only
three-business-day default suggestion; no Sent Items integration or automatic sends
in the first release. These defaults are open for correction before implementation.

## Independent review and resolved reliability decisions

A fresh builder review identified three material ambiguities. This revision
resolves them as proposed product decisions rather than asking the implementer to
invent behavior:
1. Booking state, temporal position and attendance are independent; sync cannot
   erase attendance or make a cancellation disappear behind an Attended label.
2. Meaningful contact has the explicit follow-up-clock rules above. Automated mail,
   unanswered inbound requests and externally logged replies are not interchangeable.
3. Interview evidence not yet accepted into an opportunity generates a Review
   interview evidence item, not an automatic employer follow-up or send target.
   Pipeline and follow-ups consume that same action engine after activation.
   Preserve existing snoozes/dismissals and removed evidence in migration; do not
   silently reactivate them or show duplicate legacy/new reminders. Offer acceptance
   of the opportunity and its links before enabling its business follow-up clock.

Merge/split is manual and audited. Merge previews selected links, tasks and status
conflicts; an admin chooses the retained opportunity and resolves conflicts.
Retain the old ID as a redirect/history record. Split creates a new opportunity ID
and moves only selected links/actions after review. Never merge because company
and role happen to match, and never duplicate an outbound send during either action.


Builder recheck: the independent reviewer found no remaining material ambiguity
blocking an implementation plan after product approval. This is a design review,
not runtime validation or a claim that the planned behavior already exists.


## Approved concise UI addendum

Default page: Opportunity / Profile / Stage-status / Next-action worklist, with
Needs attention, Upcoming, All active and Closed filters. Search and profile
filter are secondary. Details progressively disclose notes, source history and
corrections. Advanced dates, merge/split and linking controls do not occupy the
main list. A created opportunity switches to All active so an empty action list
cannot make the new record appear to vanish. Existing legacy timeline is retained
at `/interview-processes/legacy` while the new pipeline uses the existing main route.
