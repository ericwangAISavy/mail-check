# Bidder web access

An admin opens **Accounts → Manage bidders and account assignments → Bidder web access**, enters a password of at least 12 characters, and clicks **Enable bidder access**. Share the password and their **bidder username** privately with that bidder.

On the sign-in screen, choose **Bidder**, type **bidder username** in **Username**, and enter the password. Use the bidder name alone, without an admin suffix. Bidder accounts are opt-in; existing bidders are not automatically granted access.

Bidders can open **Dashboard** to see graphs for accounts assigned to them on the message’s Chicago receipt date. The dashboard has no message list, message reader, or account-status panel for bidders. Account filters list only their assigned accounts; changing URL parameters cannot select another bidder’s data.

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
