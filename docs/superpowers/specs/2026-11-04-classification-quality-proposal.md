# Email classification quality proposal

Status: approved for implementation. The original review findings below are retained;
implementation and rollback details follow. Stored mailbox labels are unchanged.

## Intended outcome

Prioritize recall for interview-related messages so important scheduling mail is
not hidden, and precision for application-received confirmations so daily counts
are not inflated by advertising, invitations to apply, or unrelated messages.
Evaluate the two goals separately rather than optimizing overall accuracy.

## Findings

1. Sender-only noise filtering can suppress important mail before the model runs.
   `mailcheck/prefilter.py` labels configured default alert senders as job_alert
   regardless of content. Synthetic calls to the real function using
   `noreply@indeed.com` returned job_alert for both “Interview scheduling with Acme”
   and “We received your application to Acme”. These demonstrate a code-path risk,
   not a claim that real messages from those addresses were misclassified.
2. Category repair is too permissive. `mailcheck/taxonomy.py` accepts substrings in
   both directions. Verified examples: not_interview_invite becomes interview_invite;
   application becomes application_ack. An otherwise invalid model answer can be
   converted into a definite label without evidence.
3. Interview lifecycle distinctions are underspecified. Interview confirmations,
   reminders, rescheduling and cancellation are not explicitly described. Availability
   overlaps info_request, which is deliberately excluded from the daily action queue.
   This can hide scheduling conversations or confuse interview confirmation with an
   application receipt. The original email and category rules need explicit precedence.
4. Model input loses evidence. `mailcheck/normalize.py` strips quoted/forwarded text
   and normally keeps the first 1,200 characters. The classification prompt does not
   include available calendar metadata or selectively retained thread context. Critical
   details below boilerplate, in calendar data, or in short replies may be absent.
5. Syntactically valid results are accepted without an uncertainty policy.
   `ItemResult` supplies defaults for missing confidence/action/summary. Low-confidence
   noise can remain hidden; the model's self-reported confidence is not calibrated.
6. Cache refresh needs an explicit plan. Current cache lookup precedes rules, and
   PROMPT_VERSION remains 1. New model instructions/rules/input extraction will not
   automatically repair older wrong labels, especially with incremental checkpoints.

## Approaches

Recommended: harden the existing pipeline and measure the current model before
considering a replacement. This addresses failures that happen before/after inference
and limits operational changes. A model replacement alone cannot fix prefilter drops
or missing input evidence. Compare models later only if the measured results justify it.

## Proposed implementation scope

- Add a labelled evaluation set with interview invitations, scheduling replies,
  confirmations, reminders, reschedules, cancellations, receipts, acknowledgements
  with next steps, shared senders, long HTML, calendar-only messages and quoted threads.
  Include negative cases: interview advice newsletters, job digests, “invite to apply”,
  recruitment marketing, unrelated meetings and rejection messages.
- Make default noise filtering require clear digest evidence. Ambiguous shared-sender
  messages should reach the classifier; keyword matches should not force a category.
- Add explicit interview-versus-receipt definitions and precedence examples. Use the
  existing category IDs initially; define action_required independently. Do not create
  calendar events or change existing interview tracking automatically.
- Preserve bounded relevant evidence, with a larger/higher-signal excerpt and calendar
  metadata where present. Recover only limited necessary quoted context for sparse
  replies; do not feed entire historical threads indiscriminately.
- Replace substring repair with exact category names and explicit harmless aliases.
  Retry incomplete/invalid semantic results once as individual messages. Route still
  ambiguous important-looking messages to manual review rather than silently to noise.
- Version the updated classifier behavior for newly processed messages. Keep historical
  reclassification as a separately approved action, with previewed scope and counts.

## Evaluation and acceptance

Run the labelled set through the current configured model before and after changes.
Measure interview recall, application-ack precision/recall, false noise assignments,
manual-review rate, model requests per message and elapsed time. Select any confidence
threshold from results, not an arbitrary number. Important edge cases must not be
silently hidden; acknowledgement precision must not regress to boost recall. Existing
retry, read-only collection, caching/idempotency and checkpoint guarantees must remain.

No live mailbox or model accuracy was measured in this review. Synthetic function
checks and source inspection establish the listed logic risks, not production rates.

## Approval requested

Approve the scoped evaluation and safeguards above using the current model and
existing categories. Do not change the model or reclassify stored mail yet.

## Approved implementation and rollback

Approved by the user on November 4, 2026, with a requirement to restore the prior
state if needed. Baseline commit: `496f48a`; rollback tag:
`rollback/classifier-before-quality-2.13.2`.

Implementation retains the current model/category IDs, local explicit rules, and
the configured body character allowance. Calendar context and selectively recovered
quoted text share that allowance. Ordinary checks preserve the latest stored label
across prompt versions; explicit reclassification remains a separate action.
The prompt requests an explicit needs_review flag when evidence cannot distinguish
important mail from noise; flagged results are retried, then surfaced for manual
review. No numeric confidence cutoff is applied without calibration data.

No Ollama endpoint is configured in this development workspace, so current-model
before/after inference cannot be measured here. The 26-case synthetic corpus and
`tools/evaluate_classification.py` provide the reproducible evaluation path:

```sh
.venv/bin/python tools/evaluate_classification.py --validate-only
# Run with the same existing endpoint and model for both checkouts:
.venv/bin/python tools/evaluate_classification.py --base-url EXISTING_OLLAMA_URL --model EXISTING_MODEL
# A detached baseline checkout lets the same script/corpus measure old logic:
git worktree add --detach /tmp/classifier-baseline rollback/classifier-before-quality-2.13.2
.venv/bin/python tools/evaluate_classification.py --source-root /tmp/classifier-baseline --base-url EXISTING_OLLAMA_URL --model EXISTING_MODEL
```

The evaluator uses synthetic messages only and reports interview recall, receipt
precision/recall, false-noise count, manual-review count, action accuracy, request
cost, and duration. Its numbers describe this small synthetic corpus, not mailbox
accuracy. The baseline run intentionally does not enforce the improved strict
body-length bound, allowing the same corpus to exercise the old implementation.

To reverse after publishing: use `git revert <classifier-quality-commit>` and push
the revert. This preserves later unrelated commits and avoids destructive reset.
The single classifier commit contains its release and generated frontend artifacts.
No historical mail reclassification or database migration was performed. Messages
classified after deployment keep their recorded labels unless the user separately
requests reclassification. To reproduce the exact old code without changing the
shared branch, check out the rollback tag in a detached worktree.
