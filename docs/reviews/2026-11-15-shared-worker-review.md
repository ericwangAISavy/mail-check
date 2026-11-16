# Shared worker review and fixes

Reviewed commit `003d96b` and addressed the following reproducible issues in 3.0.1.
All reproductions and validation use temporary files/databases and an isolated
RabbitMQ service. Existing application schemas and running admin services are
unchanged.

## Findings addressed

- Successful manual jobs could run again after lost acknowledgments. Private
  success receipts now suppress repeated provider/model work. Redelivery also
  repairs a status write interrupted after the success receipt, exactly once.
- Retryable manual failures published terminal UI status and could be replaced
  after 120 seconds. Queue ownership now lasts through delayed retries; superseded
  deliveries cannot overwrite a newer job, and successful receipts retain no token.
- Busy account locks or pending-queue capacity consumed the business retry budget.
  Confirmed AMQP deferral preserves the attempt count and the original is only
  acknowledged after the deferred publication succeeds.
- A single shared hint budget could fill with mail jobs that could not finish
  until they enqueued classification. Collection and model/schedule hints now have
  independent bounded budgets. A committed pending classification can also be
  recovered by reconciliation after its mail delivery releases its quota slot.
- Manual reclassification selected disabled accounts outside the guarded account
  snapshot. It now freezes the actual candidate IDs and validates/locks every
  selected account before model work or writes.
- Pending shared API sign-ins could outlive shutdown and persist after workspace
  suspension. Each shared app now owns a bounded flow registry, cancels and joins
  its threads, and checks trusted workspace state before credential/account writes.
- Notifications for suspended workspaces raised a registry lookup error and caused
  retryable failures for the whole Microsoft batch. Expected suspension/removal
  now skips that item while genuine registry/broker failures still return 503.
- Shared slot IDs bypassed the original workspace rollback-backup gate. Both API
  and background pool startup now validate that gate before starting work.

## Validation

Regression tests cover duplicate delivery, receipt/status crash recovery, pending
retry ownership, unchanged deferral attempts, disabled reclassification targets,
sign-in cancellation and workspace guards, suspended webhook batches, and backup
gate enforcement. Real RabbitMQ checks exercise confirmed job transport and the
existing two-workspace collection/outbox/SSE paths.

The full backend and frontend suites, production bundle build and release
consistency check are run before committing the patch. The existing deliberate
shutdown policy is retained: ready processes drain active work rather than being
force-killed. A stuck provider can therefore delay shutdown; no live cutover is
performed by these fixes.

Final results: 1,184 backend tests passed, 17 skipped, and 102 subtests passed;
all 546 frontend tests passed. The production bundle and release consistency
checks passed. The backend run included the isolated real-RabbitMQ tests.
