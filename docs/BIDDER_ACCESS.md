# Bidder web access

An admin opens **Accounts → Manage bidders and account assignments → Bidder web access**, enters a password of at least 12 characters, and clicks **Enable bidder access**. Share the password privately with that bidder.

On the sign-in screen, choose **Bidder**, select **bidder name + admin username**, and enter the password. The original workspace uses the admin username `owner`. Bidder accounts are opt-in; existing bidders are not automatically granted access.

Bidders can view their admin's whole team on **Dashboard** and **Bidder management**, including team statistics, stored dashboard messages, and weekly payment totals. They cannot edit, check applications, refresh/rebuild stored matches, send messages, manage accounts, access Settings or Job sourcing, or switch workspaces. Date/account/bidder filters are available for browsing saved data. Access restrictions apply at both the public gateway and private worker boundary.

Admins can reset a bidder's password or disable access from the same account card. Reset, disable, or removal revokes the bidder's sessions. Admin password changes/resets and workspace suspension also invalidate the associated bidder sessions. Bidder names are updated when renamed through the Accounts page.

The public bidder selector exposes enabled bidder names and their admin usernames, as required to select an account. It does not expose email addresses, passwords, or payment data before login.

Credentials and sessions use separate additive tables in `offerpath-control/control.db`; existing mailbox, application, payment, and assignment tables are preserved. Old standalone writable bidder credentials are not automatically imported into the public multi-admin gateway.
