# Historical classification and estimated confirmations

Reconciliation and platform-copy deductions have been removed. Classification
uses the original behavior from before release2.13.3. Weekly estimates and the
daily badge count emails currently classified as Application received, once per
account/message ID. Checked job links remain a separate number.

After updating and restarting, open **Bidder management**:

- **Reclassify this week** reruns every stored email received in the displayed
  Chicago accounting week, including emails already classified.
- **Reclassify all stored emails** reruns every retained classified message in
  this workspace, across all weeks.

Both actions bypass the classification cache, rerun the original sender rules and
current model, save results and a run log, update confirmation receipt estimates,
and rebuild automatic job checks in scope. Progress appears in the normal check
status. Keep the model server running. Existing recorded payments, payment edits
and manual checks stay unchanged. Repeating a run updates the same receipt records
rather than adding them again. Normal mail checks still reuse stored labels;
upgrading alone does not relabel history.

Only stored email content can be reclassified. Receipt records can survive email
retention, but those records do not contain the original body. Fetch missing older
emails again from the provider using an explicit lookback and no-cache check before
relogging them. The history action never deletes or guesses classifications for
these unavailable emails. Very large histories take time and use the configured
model; failed/unclassified items remain visible for retry.
