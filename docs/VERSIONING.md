# OfferPath versions

The version button beside OfferPath's name opens the release history for every
signed-in admin. Version tracking starts at **2.1.0**; earlier version numbers are
not reconstructed. The viewer reads the same `releases.json` used to generate
[the changelog](CHANGELOG.md).

Version updates are automatic for completed runtime changes: the coding agent selects the appropriate bump, writes release notes, runs the release tool and checks, and includes the generated files in the commit without asking for separate confirmation. An explicit user version takes precedence.

For a future fix or performance correction:

```sh
python tools/release.py patch --title "Short release title" --note "Explain the change to users."
```

Use `minor` for new backward-compatible features and `major` for breaking changes.
Add multiple `--note` arguments for several changes. The tool calculates the next
version, dates it in America/Chicago, preserves previous releases, and updates
Python metadata, frontend metadata, the npm lockfile, and the changelog together.
Run it once per completed change, not for each file or a commit/push-only request.
The initial version-history feature itself is part of 2.1.0.

```sh
python tools/release.py --check
npm --prefix frontend run build
```

The build checks metadata consistency. GitHub checks also compare runtime changes
against the previous revision and reject missing version bumps or rewritten old
release notes. Documentation/test-only changes need no new version. `AGENTS.md`
instructs future coding agents to select the appropriate bump and write meaningful
notes; the tool automates the updates, rather than guessing release descriptions.
No application database, stored status, credential, or user setting is changed by
version tracking.

When restoring an older implementation, publish the restored behavior as a new patch release above the latest published version. Preserve prior release entries and Git history instead of moving the published branch backward or force-pushing, unless the user explicitly requests that. For example, restoring 2.13.5 behavior after 2.14.1 is published becomes 2.14.2.
