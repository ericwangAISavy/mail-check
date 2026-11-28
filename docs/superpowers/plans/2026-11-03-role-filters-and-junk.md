# Role filters and Junk/Spam collection

User authorized implementation of both backlog items.

- [x] Add migrated account-keyed role keyword storage and admin-only management APIs.
- [x] Apply case-insensitive role substring filtering to incoming job rows, preserving history and account isolation.
- [x] Provide account selection and independent drafts/saves alongside existing company filters.
- [x] Include role-removal counts in filtering progress/results.
- [x] Scan Outlook Inbox and Junk Email with pagination, existing ID compatibility, and Message-ID deduplication.
- [x] Discover IMAP Junk/Spam folders, select read-only, preserve precise arrival-time filtering, and deduplicate across folders.
- [x] Report folder collection status; reset inbox-only checkpoints once so newly covered folders are backfilled.
- [x] Run complete backend and frontend suites, release checks, and production build.

No live mailbox credentials, databases, or production settings are modified by development tests.
