# System monitoring

Available in OfferPath **2.29.0** and later.

The owner can open **System monitoring** in the navigation to inspect all admin workspaces without switching between them. Other admins and bidders cannot access the page or its API. The page loads through the gateway independently of workspace bootstrap, so it remains available when a workspace worker fails.

The page refreshes every three seconds. It shows gateway and control database health, workspace worker and database state, shared model lease activity, account sync evidence, queue counts, publication backlog, and recent operational events. Filter by workspace or event component, select issues only, or pause to freeze the displayed snapshot. A failed refresh labels retained snapshot data as stale.

Health is based on observed evidence. Worker health comes from the existing supervisor, and database checks use bounded read-only queries without initializing missing databases. Mail/calendar collectors and classification show dependency failures and queue issues; unknown means their current liveness or external provider/model reachability has not been established. Account sync success older than ten minutes is unknown. Monitoring does not contact mailbox providers or invoke a model.

For live job events and queue metrics, configure the existing Redis real-time integration described in [Automatic updates](REALTIME.md), including the `realtime` Python extra. When it is disabled or unavailable, local health checks remain available and Redis-dependent metrics are explicitly unavailable or disabled.

Operational events trace automatic jobs through queued, started, completed, retry-or-failed, and published stages. Job/change IDs connect stages of the same Redis job; a delayed retry may receive a new job ID. `completed` means the consumer acknowledged its job, not a guarantee about external business outcomes. Published change events have their own change IDs. Existing manual checks are not a historical Redis event source.

Telemetry uses a process-local buffer of at most 256 hints and an independent background Redis writer with short timeouts. Saturation or connection failure drops hints instead of delaying business operations. Redis retains at most 1,000 events per workspace; the page merges up to 200 per workspace and displays the newest 200 overall. This is operational evidence, not a complete audit log. New events begin after the updated processes start.

Events contain only fixed component/action labels and Redis job IDs. Raw errors, credentials, mailbox addresses, subjects, bodies, and model prompts are not exposed. Monitoring never consumes jobs, acknowledges them, starts workers, or changes account settings.
