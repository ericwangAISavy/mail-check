# System monitoring

The owner can open **System monitoring** to inspect shared services, queue backlog, and live operational events. Other admins and bidders cannot access the page or its API.

As of **3.0.3**, the page shows global service health and aggregate process-pool readiness, without per-admin worker, database, or account-sync cards. Shared architecture diagrams separate API data access, job processing, and browser change delivery.

Queue totals show ready jobs, delayed retries, and dead letters across global RabbitMQ queues. Ready jobs exclude in-flight work. In legacy mode, queue counts are aggregated across workspaces and outstanding jobs include in-progress work. Missing metrics display as unavailable rather than zero.

The page refreshes every three seconds. Pause freezes the displayed snapshot; a failed refresh marks retained data as stale. Workspace and component filters apply only to live events, keeping global service health and queue totals visible.

Health reflects local checks and recorded process readiness. Monitoring does not contact mailbox providers or invoke a model, so healthy local components do not establish external provider reachability.

Operational events trace queued, started, completed, retry/failure, and publication stages. Job/change IDs help connect stages. Telemetry is best effort and bounded; it is operational evidence rather than a complete audit log. Events begin after updated processes start and contain no email content or credentials.

Monitoring does not consume or acknowledge business jobs, start workers, or change databases or account settings. See [Shared architecture](SHARED_WORKERS.md) for RabbitMQ deployment details.

As of **3.1.0**, status history uses an interactive time graph instead of an event table. Each component has its own lane. Points are colored by recorded status; nearby events of the same component and status share a point, with size indicating event volume. Select a point with the mouse or keyboard to inspect workspace, timestamp, action, and job/change IDs. Filters and pause apply to the graph. Gaps indicate no recorded events, not continuous service health.

**3.1.1** makes model-process liveness checks read-only on Windows. Earlier shared-mode monitoring used a POSIX-style signal-zero check, which Windows interprets as a console-control operation. Upgrade before using monitoring alongside active model work on Windows.
