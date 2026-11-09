# Bidder web access

An admin opens **Accounts → Manage bidders and account assignments → Bidder web access**, enters a password of at least 12 characters, and clicks **Enable bidder access**. Share the password and their **bidder username** privately with that bidder.

On the sign-in screen, choose **Bidder**, type **bidder username** in **Username**, and enter the password. Use the bidder name alone, without an admin suffix. Bidder accounts are opt-in; existing bidders are not automatically granted access.

Bidders can open **Dashboard** to see graphs for accounts assigned to them on the message’s Chicago receipt date. The dashboard has no message list, message reader, or account-status panel for bidders. Account filters list only their assigned accounts; changing URL parameters cannot select another bidder’s data.

Bidders also have **Inbox**, which reuses the Triage list and reader but is fixed
to the existing **Info request** category. Lists, search, counts, message bodies
and Done requests are restricted to currently active account assignments (Chicago
calendar dates); future/ended assignments and disabled accounts do not grant access.
This restriction is enforced at the gateway and worker, not just in the page filters.
Inbox refreshes every ten seconds. It adds no category and changes no classifier.

Bidders may read messages and use the existing **Done / Restore** action. The
status is the app's existing shared, local message status, not a new per-bidder
acknowledgment; it never alters the provider mailbox. Undo from the Done toast
restores only that specific authorized message. Global Undo, reply/composer/history,
reclassification, Open in Outlook/Gmail, mailbox settings and other message categories
remain unavailable. Assignment changes and reclassification are checked again for
every message read and status update. Admin Triage keeps its existing behavior.

On **Accounts → Bidder visibility**, admins save two checkbox options for each bidder:

- **Payment visible** shows payment amounts for all bidder rows the viewer is allowed to see. When **Other bidders’ work visible** is also enabled, this includes coworkers’ before/after-deduction amounts and recorded payment status. Coworker wallets, rates, internal notes and account details remain private. It defaults to enabled. Disabling it removes money, rates, deductions, and recorded-payment details from their payment API response and page.
- **Other bidders’ work visible** shares the team’s checked counts and work-activity graphs. It defaults to disabled, showing only the signed-in bidder. It shares payment amounts only when **Payment visible** is also enabled. It never shares coworkers’ accounts, received replies, or wallets. Dashboard graphs remain restricted to the signed-in bidder regardless of this option.

Options apply to the active workspace and all viewed weeks. Changes require **Save visibility**; conflicting edits require reloading the saved options. Bidders cannot read or change these admin settings. Visible bidder payment and activity pages refresh every 30 seconds and on focus. When team visibility changes, the activity graph switches scope without displaying cached coworker data. API permissions apply to every request.

Bidders can also view and copy their own saved Job sourcing workbook, navigating account tabs, dates, and saved history. Sourcing search is limited to their own workbook. They cannot edit, paste, import, check applications, refresh/rebuild stored matches, send messages, manage accounts, access Settings, or switch workspaces. Access restrictions apply at both the public gateway and private worker boundary.

Admins can reset a bidder's password or disable access from the same account card. Reset, disable, or removal revokes the bidder's sessions. Admin password changes/resets and workspace suspension also invalidate the associated bidder sessions. Bidder names are updated when renamed through the Accounts page.

The sign-in page never fetches or displays account directories. Users type their identifier; account-directory endpoints require authentication. Failed sign-ins return the same generic error for unknown usernames and incorrect passwords. Duplicate bidder identifiers fail closed rather than selecting an arbitrary account.

Credentials and sessions use separate additive tables in `offerpath-control/control.db`; existing mailbox, application, payment, and assignment tables are preserved. Old standalone writable bidder credentials are not automatically imported into the public multi-admin gateway.

Bidder usernames must be unique across all registered workspaces, including
suspended workspaces and bidders whose web access has not been enabled. Creation,
rename and web-access setup check for duplicates; whitespace, case and Unicode
normalization are ignored when comparing names. Existing duplicate login names
are not silently reassigned: sign-in fails safely until an admin gives each
conflicting bidder a distinct name. Existing passwords and workspace identities
remain unchanged. Admin usernames use a separate role/namespace.

Visible payment rows show the calculated before/after-deduction amounts separately
from **Recorded paid: $…** or **Not recorded as paid**. Saved manual amounts
that differ from the current calculation are also shown without marking them paid. A recorded payment can differ
from the current calculation; the recorded status does not imply the app transferred
funds. Coworker payment notes are not shown.

## Faster active Inbox checks

With automatic mail checks enabled and the model configured, an open, visible
bidder Inbox requests fresh stored results every 3 seconds. It also signals active
Inbox demand to the server. The workspace shares one recent-mail check about every
30 seconds across active bidders, using only currently assigned enabled accounts.
Requests coalesce across tabs/bidders; closing or hiding the Inbox stops demand
shortly afterward. Failed checks back off. Normal mail, calendar and sourcing work
retain the shared job lock; a busy provider/model or running job can delay delivery.

Live scans use a recent 10-minute overlap and preserve normal collection
checkpoints and retention windows. They do not alter classification or email
visibility. The existing Info request-only Inbox and account permissions remain.
Automatic-check off remains off. **Refresh Inbox** reloads the view; it cannot
bypass that setting or grant mailbox-management access.
