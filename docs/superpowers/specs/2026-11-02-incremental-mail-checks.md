# Mail check range selection

Keep the existing fixed lookback mode as the default. Add a saved “Since last successful check” mode used by manual, automatic, and CLI checks. An explicit CLI/API lookback override still performs a fixed-window check, advancing the incremental checkpoint only if it covers the whole outstanding range.

Store the successful check start time independently for each account, bound to its mailbox configuration. Resume with a two-minute overlap, falling back to the configured lookback for new accounts or invalid checkpoints. Advance only after all collected mail for that account is durably processed; mailbox failures and deferred classifications preserve the previous checkpoint. Nonretryable manual-review classifications remain visible locally without stalling progress. Failed first attempts keep their original starting window. Empty successful checks advance too. Save checkpoints in SQLite so backups and restarts preserve them. Show each account’s last successful mail-check timestamp.

Outlook queries received timestamps directly. IMAP first searches by date, reads only UID/INTERNALDATE metadata, then downloads matching messages; never use sender Date headers as arrival timestamps. Keep read and unread messages and read-only access. Protect retention within each actual fetch window, including recently fetched mail whose sender dates are stale. Native calendar collection retains its independent rescan because existing events can change.

Do not change the pending role-filter behavior without the user’s inclusion/exclusion answer.
