# Owner management layout

The owner needs one active task and one selected workspace rather than every
admin action and every backup archive rendered together.

- Default to Workspaces: searchable, compact directory; one selected detail panel.
  Preserve browser presence separately from server health and all owner restrictions.
- Open Add admin as its own form. Keep creation drafts in memory while changing
  tasks, and clear password-reset state when changing the selected administrator.
- Backups and Activity are separate task tabs. Fetch their data when first opened;
  pause backup polling when its task is hidden. Preserve backup settings drafts.
- Show backup status and latest-download action in a concise overview. Put archive
  history in an explicit modal with provider-independent type filter and eight
  rows per page, sorted newest first. Keep retention, location and restore help
  collapsed until needed. Preserve existing ticket validation and confirmations.
- Tests cover task isolation, search/selection, account permissions, owner protection,
  password reset target, creation, lazy fetch, archive pagination and secure downloads.
- Run relevant frontend tests, TypeScript, release checks and production build. Add
  one patch release for this UI/workflow improvement; retain generated assets.

Validated: 638 frontend tests passed, TypeScript and production build passed, release consistency and source whitespace checks passed. Mock-data desktop and 390px mobile screenshots were reviewed with no horizontal overflow. Independent review findings were resolved, including keyboard focus restoration after closing archive history. Release 3.33.3.
