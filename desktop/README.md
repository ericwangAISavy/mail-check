# OfferPath desktop

An Electron window around the OfferPath web app at https://app.offerpath.bid.
The web app itself is unchanged; updates to it appear in the desktop app
automatically.

- Opens only OfferPath in the window; other links open in the default browser.
- Keeps sign-in between launches and remembers the window size and position.
- A second launch focuses the existing window.
- Shows a "Try again" page when the server cannot be reached.
- Shows the web app's attention count as a taskbar badge.
- Updates itself from the GitHub release marked "Latest": it checks at start
  and every 4 hours, downloads in the background, then offers "Restart now"
  or installs the next time OfferPath closes. Menu: OfferPath → Check for updates…

## Build the Windows installer

```powershell
cd desktop
npm install
npm run dist        # -> dist\OfferPath-Setup-<version>.exe, .blockmap, latest.yml
```

## Release an update

1. Raise `version` in `package.json` (patch for fixes, minor for features).
2. `npm run dist`, then commit and push.
3. `python publish.py --note "What changed"` (repeat `--note` for more).

`publish.py` creates the `desktop-v<version>` release at the pushed commit,
uploads the installer, blockmap and `latest.yml`, and marks it "Latest".
Installed apps only see an update once all three files are on the Latest
release, so don't create desktop releases by hand or push only the tag.

Run without installing: `npm start`. Point at another server with the
`OFFERPATH_URL` environment variable.

Notes:

- Inside a VS Code terminal, `ELECTRON_RUN_AS_NODE` may be set; clear it before
  `npm start` or launching the built exe (`Remove-Item Env:ELECTRON_RUN_AS_NODE`).
- If `npm run dist` fails with "Cannot create symbolic link", either enable
  Windows Developer Mode, or extract
  `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\*.7z` into
  `...\winCodeSign\winCodeSign-2.6.0` once (the two macOS symlink errors are
  harmless) and build again.
- The installer is unsigned, so Windows SmartScreen will warn on first install
  ("More info" → "Run anyway") until a code-signing certificate is added.
