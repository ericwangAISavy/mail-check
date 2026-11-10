# Clearing an initial Queue backlog

Admins can open **Queue**, choose **Mark all as done**, and confirm the action.
This completes the entire current workspace Queue, including messages outside
current date/mailbox/category/search filters and beyond the 500 displayed rows.
The confirmation states that scope explicitly. Bidder Inbox does not offer this
action, and bidders cannot call either bulk endpoint.

Only unhandled messages whose latest classification belongs in Queue are changed.
Other categories and previously completed messages remain untouched. Emails and
classifications stay saved; mail is available in All mail/Completed under the
appropriate filters. No email is deleted, sent, or marked read at the provider.
Messages added after completion are not included.

The success notification's **Undo** restores that exact batch. The toolbar's
existing **Undo** (or Ctrl/Cmd+Z) also recognizes a bulk completion as one action
when it is the most recent completion. A later single-message Done/Restore action
supersedes that message's batch membership, so batch Undo does not overwrite it.
Deleting/pruning a message removes its membership, preventing Undo from affecting
an unrelated message that later reuses its database ID. Repeated batch Undo is safe.

Completion and membership writes are atomic. Schema version 46 adds a small
workspace-local membership table and operation index; existing emails, completed
states and classification history are preserved during upgrade. Membership rows
are bounded by retained messages, removed on manual changes/batch undo, and cascade
away on message deletion. No provider network calls or per-row browser requests
are needed to clear the backlog. Existing deployments need the normal app restart
to apply the code and schema migration.

Completion timestamps are reserved after acquiring the write transaction and
advance monotonically when the system clock repeats or moves backward, preserving
single-message/batch Undo ordering on coarse clocks.

Verification for 2.25.0: 844 backend tests and 98 subtests passed, including large
queues, latest classification, rollback, upgrade preservation, retention ID reuse,
manual overrides, repeated Undo, clock ordering and bidder restrictions. All 457
frontend tests passed, production build passed, and Chromium verified confirm,
cancel, bulk clear, empty Queue and scoped batch Undo under production security
headers with synthetic mailbox data. Existing dependency/chunk-size warnings remain.

## Retry and session safety (2.25.1)

Each new confirmation gets a UUID. Retrying that confirmation after a connection
error reuses its UUID; concurrent or later duplicate requests return the original
result without clearing new arrivals. This also applies to an initially empty
Queue and remains true after the original batch is undone. Cancelling or opening
a new confirmation creates a new action. Writes are never retried automatically.

Schema 47 adds a small operation-result record, independent of message retention,
so the same confirmation cannot be reapplied after its members are restored or
pruned. Surviving schema-46 batches are backfilled during upgrade. Older clients
without an operation ID retain their original endpoint compatibility; refresh the
browser after deploying to receive the retry-safe confirmation UI.

Notifications are scoped to the session identity revision. Workspace switches,
account changes, logout and re-login discard prior notifications; retained old
buttons and delayed callbacks cannot run an action in a newer session.

Verification: 848 backend tests and 98 subtests, 461 frontend tests, production build
and Chromium replay/workspace-switch checks passed. The browser test simulated an
accepted clear whose response was lost, checked reuse of the confirmation UUID,
confirmed a newly arrived message remained queued, and verified the old Undo was
removed after a workspace change. Existing dependency/chunk-size warnings remain.
