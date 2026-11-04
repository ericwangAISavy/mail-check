# Restore original classification and historical estimates

The user requests removal of reconciliation, restoration of the classifier before
release2.13.3, and an explicit way to reclassify historical emails and relog estimates.
Restore classifier/prefilter/normalization/schema/taxonomy from d5f920a^; use a new
prompt cache version so explicit runs are identifiable. Keep later transport,
authentication, tenant isolation and query performance fixes.

Remove reconciliation UI/API report fields and platform-copy deductions. Retain
additive database columns for compatibility. Preserve one-to-one sourcing receipt
assignment, manual checks, recorded payments and payment edit history.

Add admin actions for a Chicago accounting week and all stored emails. Run current
rules and model in the existing background job, bypass classification cache and
200-message retry cap, save classifications/receipt updates and a normal run log,
then rebuild automatic sourcing checks within scope. Repeated runs must not add
receipt duplicates. Unknown/pruned messages cannot be reclassified without their
mail content: tell users to fetch them again rather than invent new classifications.

Approach: targeted restoration plus an explicit history action. A full branch reset
would discard unrelated security fixes. Re-fetching all mail automatically would
make this action depend on provider availability and broaden its scope.
