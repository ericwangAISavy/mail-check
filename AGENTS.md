# OfferPath release tracking

The current release baseline is 2.1.0, explicitly set by the user on October 28, 2026.
This initial version-history implementation remains part of 2.1.0.

For future changes to runtime features or behavior:
- Add a release before completing the task. New backward-compatible features use a minor bump; fixes, performance improvements, and behavior corrections use a patch bump. Breaking changes use a major bump. An explicit user version takes precedence.
- Run `python tools/release.py minor --title "Short title" --note "User-facing change"` (or patch/major). Use multiple --note arguments for several changes. Bump once per completed change, not once per edited file or commit. Do not bump again for a commit/push-only request.
- The command updates releases.json, Python/frontend versions, the npm lockfile, and docs/CHANGELOG.md together. Do not edit generated CHANGELOG.md by hand or rewrite published entries.
- Run `python tools/release.py --check`, relevant tests, and the frontend production build when UI/release history changes. Include regenerated frontend_dist files in the same commit.
- Documentation/test-only changes need no bump unless runtime behavior also changes.
- Never modify application databases, stored statuses, credentials, or user settings to update an application version.
