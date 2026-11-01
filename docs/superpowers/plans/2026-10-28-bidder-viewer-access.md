# Bidder viewer access

Agreed scope: role-first sign-in; bidder selects `name + admin username`, authenticates with an admin-set password, and sees their admin's whole team on Dashboard and Bidder management. No editing, checking, refreshing, Settings, sourcing, workspace switching, or other admins' data. Admin features remain unchanged.

Implementation choice: reuse the existing gateway and isolated workers. Add separate bidder credential/session tables in the control database, without migrating business records or reviving old writable bidder permissions. Public directory exposes enabled bidder display names and opaque credential IDs only. Credentials are opt-in; passwords are hashed, attempts throttled, sessions revocable. Workspace suspension, admin password reset, bidder disable/reset/removal revoke access.

1. Add failing gateway tests for directory/login, workspace isolation, read-only allowlist, credential administration, reset/disable/removal, and suspended admin.
2. Add bidder-access store with workspace-qualified credential identity and hashed sessions. Integrate gateway authentication, logout, dispatch revalidation, and credential management backed by worker bidder lookup.
3. Pass a private viewer header only across the worker-authenticated boundary. Enforce read-only APIs in workers too. Skip payment matching and receipt synchronization on viewer reads.
4. Restore role selector, bidder directory/password login, and admin credential forms. Clear caches on bidder/workspace identity changes. Limit navigation to Dashboard and Bidder management; hide refresh/write/account controls.
5. Test role flow and read-only pages. Run relevant and full suites, build compiled assets, increment minor release once, and check release consistency.
