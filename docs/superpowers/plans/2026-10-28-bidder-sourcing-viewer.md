# Read-only bidder sourcing

Scope: bidders retain whole-team Dashboard and Bidder management access, and gain view/copy access to their own saved sourcing workbook only. Date/history/account-tab navigation and search are reads. No edits, paste, autosave, application checks, refresh, settings, imports, or structural changes.

1. Add gateway/worker tests proving the exact read allowlist, own-workbook ownership, cross-bidder denial, and zero workbook backfill on viewer reads.
2. Pass authenticated viewer bidder identity into sourcing principals only, skip index reconciliation for viewers, and use query-only SQLite connections for sourcing reads.
3. Render a separate sourcing viewer using existing date controls, a selectable paginated table, and HTTP-compatible copy support. Keep admin editor behavior intact.
4. Add frontend tests for saved-day navigation, copying, and absence of mutation controls; verify relevant suites and compiled build. Add one minor release and update bidder access docs.
