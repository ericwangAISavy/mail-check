# OfferPath desktop

An Electron window around the OfferPath web app at https://app.offerpath.bid.
The web app itself is unchanged; updates to it appear in the desktop app
automatically.

- Opens only OfferPath in the window; other links open in the default browser.
- Keeps sign-in between launches and remembers the window size and position.
- A second launch focuses the existing window.
- Shows a "Try again" page when the server cannot be reached.

## Build the Windows installer

```powershell
cd desktop
npm install
npm run dist        # -> dist\OfferPath Setup <version>.exe
```

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
