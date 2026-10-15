# Bidder payments

Open **Bidder payments** in the sidebar. Admins manage bidders, account assignments,
and payment records. Guests use the existing shared guest login to view all bidders’
daily and weekly totals and recorded payment amounts. Guest writes are rejected by
the server. This feature does not add individual bidder credentials.

## Setup and use

1. As admin, expand **Manage bidders and account assignments**, and add each bidder.
2. Assign one or more connected accounts to the bidder. Set the first assigned day
   to the date they actually started, including earlier dates when appropriate.
   Each assignment has **Edit** and **Remove** controls. Edit the account, first
   day, or optional last day; clear the last day to restore an ongoing rule.
   Removal requires confirmation and changes attribution, without deleting emails.
   Changes affecting a paid week are blocked; changes outside it remain editable.
3. Use the week selector or arrows to view Monday–Sunday totals in America/Chicago.
   The bidder selector narrows the table and summary to one bidder.
4. After a week ends, select **Record payment**, enter the amount in USD and an
   optional reference, then select **Record as paid**. Amounts are entered manually;
   there is no rate-per-application calculation or money transfer.

## Counting rules

- Only the latest `application_ack` classification (displayed as **Application
  received**) contributes to a count. Reclassification can change an unpaid total.
- Each confirmation is identified by account and message ID. Rechecking or retrying
  classification does not count it again. Marking a message Done does not change it.
- A confirmation belongs to the Chicago calendar day of its received timestamp.
  Missing timestamps use the original collection timestamp. Daylight-saving
  transitions use the timezone’s actual offsets.
- A confirmation goes to the bidder assigned to its account on that calendar day.
  One account cannot have overlapping assignments, including with the same bidder.
  End dates are inclusive. For transfers, the next bidder starts the following day.
- Unassigned confirmations are excluded from bidder totals. Admins see an unassigned
  count so they can add the missing dated assignments.
- Counts are confirmation emails, not a direct audit of submitted applications.
  They depend on what mail-check fetches and classifies. Two different confirmation
  emails for one submission remain two counts; this feature does not guess whether
  they describe the same submission.

## History and payment integrity

A separate ledger stores account/message identities, received timestamps, and
categories. No email content enters the accounting ledger. Entries survive normal
email retention cleanup and account removal. New accounts cannot reuse an accounting
account identity. Existing retained classifications populate the ledger automatically.
Emails already removed before this feature was installed cannot be recovered by it.

Payment records snapshot the reviewed count, entered amount, date, and reference.
The server rejects stale counts, repeat payments for the same bidder/week, and payment
recording before a week ends. Assignment changes that would affect that bidder’s paid
week are rejected. Later classification changes do not rewrite recorded payments;
the table flags any difference between the current count and paid count.

Payment records are immutable in this version. There is no payment gateway or bank
integration. The records describe payments the admin made elsewhere.

The database migration runs automatically on startup. Guest responses omit the full
account-management list, while assigned account labels remain visible in the table.
