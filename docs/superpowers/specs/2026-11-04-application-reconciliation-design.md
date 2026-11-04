# Application receipt reconciliation

Approved by user's go-ahead after the counting audit: preserve emails and recorded
payments; distinguish raw confirmation messages from verified applications; expose
uncertain extras instead of blindly deduplicating by company/title.

Raw receipts stay unique per (account_id,message_id). A verified application needs
a checked job row with a receipt claim and a nonempty job URL. A receipt claimed
by several rows, or several checked claims of the same account/job URL, requires
review; never arbitrarily credit one bidder or silently delete another row.
Automatic verification must not broadcast one receipt to multiple candidate rows.
Existing checks remain untouched unless the existing explicit rebuild is invoked.
Safe title-prefix aliases Sr./Senior and Jr./Junior improve strict matching; do not
add broad fuzzy matches or change the user's existing company normalization.

Read-only weekly reconciliation exposes raw receipts, verified applications,
possible extra confirmations, unmatched receipts and conflicts, with masked account
labels in the UI. Possible extras are suspicions, not removed from raw counts.
Missing metadata, title mismatches, manual checks and duplicate mailbox connections
are review reasons. Report filters preserve tenant/bidder scopes.

User explicitly selected receipt-based future payment estimates, with reconciled
application counts shown separately. Retain saved payments and label the basis. Changing the
basis automatically could underpay legitimate unmatched applications; no recorded
payment or historical email is rewritten.

Approaches considered: blanket company/title deduplication merges legitimate jobs;
using raw messages as applications preserves the existing overcount. Add conservative
one-to-one verification and explicit reconciliation while retaining raw evidence.

Validation: synthetic duplicate mail, repeated fetch, shared account conflict,
exact job URL duplicates, title aliases, missing receipt metadata, timezone boundaries,
reclassification, manual checks, read-only reports, privacy/filtering, and full suites.

Review rulings: uniqueness of checked job URLs considers historical rows in the same
account, while presented counts stay weekly. A legitimate reapplication to the same
URL may require review; no receipt is deleted or payment reduced. Weekly refresh
includes archived tabs, so all explicit proposals reserve the receipt together even
when active-tab candidate queries omit archived tabs. Ambiguous proposals are skipped;
existing checked state remains until the user's existing explicit rebuild action.
