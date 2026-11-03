# Workspace removal and Outlook connection-test review

Reviewed November 3, 2026 for OfferPath 2.11.0, including an independent read-only code review.

## Findings addressed

- Outlook's connection probe used the Graph profile endpoint, which requires
  User.Read although the app requests Mail.Read for collection. The probe now
  requests Inbox messages with `$select=id` and `$top=1`, accepts an empty Inbox,
  and retains real authentication, permission, network and response errors.
  It never fetches message bodies or changes read state.
- The legacy Graph smoke test explicitly required the obsolete profile request.
  Updated it to require the minimal mailbox probe and reject profile access.

## Workspace-removal checks

- Only the owner can remove added admin workspaces. The original owner and the
  workspace currently selected by the requester are protected. The request must
  confirm the target's username.
- Session authorization is rechecked inside the write transaction, including
  requests whose bodies were held until after owner logout.
- Removal revokes admin, owner-as-viewer and bidder sessions; disables the workspace;
  clears its login hashes; and prevents later re-enable/reset requests.
- Identity tombstones preserve audit attribution and prevent ID recycling. Reusing
  a username creates a separate empty workspace with a new workspace identity.
- Stored workspace data remains offline and is included in existing backup/restore
  inventories. This feature removes access and active-list membership, not files.
- Worker shutdown and access updates are serialized and performed off the event
  loop. No new network calls, directory walks or file deletion are added to removal.
- Existing installations gain the nullable removed_at column without altering
  existing sessions, passwords or workspace files.
- Browser checks with synthetic accounts verified cancellation, confirmation,
  list refresh, owner protection, phone layout and absence of page errors.

## Scope and limitations

No real workspace was removed and no live mailbox or stored credential was accessed
for validation. Microsoft responses were synthetic. Already dispatched mail cannot
be recalled. Removed workspace data has no restore or erase button in this release;
recovery uses retained files/installation backups.

Independent review found no remaining critical or important defects in the new
functions. Passing tests support the checked scenarios; they do not establish the
absence of every possible defect.

## Final validation

- Full backend run: 583 passed, 76 subtests passed; one existing Starlette/httpx
  deprecation warning. The final focused removal run passed all 10 tests, including
  the additional suspended-workspace regression.
- Full frontend run: 317 passed across 39 files.
- Production build and release-history consistency checks pass for 2.11.0. Vite
  reports its advisory large-chunk warning; no new build failure is present.
- Browser removal checks pass at 1500×950 and 390×844 with synthetic API responses.
