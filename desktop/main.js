// OfferPath desktop: opens the OfferPath web workspace in its own window.
// The web app is unchanged; this is only a secure Chromium window around it.
const { app, BrowserWindow, Menu, shell, screen } = require("electron")
const fs = require("node:fs")
const path = require("node:path")
const { countFromTitle, updateBadge } = require("./badge")

const APP_URL = process.env.OFFERPATH_URL || "https://app.offerpath.bid"
const APP_ORIGIN = new URL(APP_URL).origin
const stateFile = () => path.join(app.getPath("userData"), "window-state.json")

/** Remembered size/position, kept on a visible display. */
function loadBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(stateFile(), "utf8"))
    const visible = screen.getAllDisplays().some(({ workArea: a }) =>
      saved.x < a.x + a.width && saved.x + saved.width > a.x && saved.y < a.y + a.height && saved.y + saved.height > a.y)
    if (visible && saved.width >= 800 && saved.height >= 600) return saved
  } catch { /* first launch or unreadable state */ }
  return { width: 1440, height: 900 }
}

function saveBounds(win) {
  try {
    const bounds = win.isMaximized() || win.isFullScreen() ? win.getNormalBounds() : win.getBounds()
    fs.writeFileSync(stateFile(), JSON.stringify({ ...bounds, maximized: win.isMaximized() }))
  } catch { /* a missing preference is harmless */ }
}

const sameApp = (url) => {
  try { return new URL(url).origin === APP_ORIGIN } catch { return false }
}

function createWindow() {
  const bounds = loadBounds()
  const win = new BrowserWindow({
    ...bounds,
    minWidth: 800,
    minHeight: 600,
    show: false,
    title: "OfferPath",
    backgroundColor: "#080f19",
    autoHideMenuBar: true,
    icon: path.join(__dirname, "build", "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: true,
    },
  })
  if (bounds.maximized) win.maximize()
  win.once("ready-to-show", () => win.show())

  // Only OfferPath runs inside the window; other links open in the default browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!sameApp(url) && /^https?:|^mailto:/i.test(url)) void shell.openExternal(url)
    return { action: "deny" }
  })
  win.webContents.on("will-navigate", (event, url) => {
    if (sameApp(url)) return
    event.preventDefault()
    if (/^https?:|^mailto:/i.test(url)) void shell.openExternal(url)
  })

  // Offer a retry instead of a blank window when the server cannot be reached.
  win.webContents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
    if (!isMainFrame || code === -3) return // -3: navigation replaced by another
    const page = `<!doctype html><meta charset="utf-8"><title>OfferPath</title>
      <body style="margin:0;display:grid;place-items:center;height:100vh;background:#080f19;color:#e6f1f7;font:15px system-ui,sans-serif">
      <div style="text-align:center"><h2 style="margin:0 0 8px">OfferPath is not reachable</h2>
      <p style="color:#8aa3b5;margin:0 0 18px">${description.replace(/[<>&]/g, "")} · ${APP_ORIGIN}</p>
      <a href="${url.replace(/"/g, "")}" style="color:#67d6f3">Try again</a></div></body>`
    void win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(page))
  })

  // The web app titles itself "(5) OfferPath" when items need attention.
  win.on("page-title-updated", (_event, title) => updateBadge(app, win, countFromTitle(title)))

  win.on("close", () => saveBounds(win))
  void win.loadURL(APP_URL)
  return win
}

// A second launch focuses the existing window instead of opening another.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  let mainWindow = null
  app.on("second-instance", () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  })
  app.whenReady().then(() => {
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: "OfferPath", submenu: [{ role: "reload" }, { role: "forceReload" }, { type: "separator" }, { role: "quit" }] },
      { role: "editMenu" },
      { label: "View", submenu: [{ role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" }, { role: "toggleDevTools" }] },
    ]))
    mainWindow = createWindow()
    app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) mainWindow = createWindow() })
  })
  app.on("window-all-closed", () => app.quit())
}
