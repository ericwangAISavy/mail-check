// Automatic updates from the GitHub release marked "Latest" (see package.json
// build.publish). Updates download in the background; when one is ready the
// user can restart now, or it installs the next time OfferPath closes.
const { app, dialog } = require("electron")
const { autoUpdater } = require("electron-updater")

const CHECK_EVERY_MS = 4 * 60 * 60 * 1000 // 4 hours
let getWindow = () => null
let manualCheck = false
let promptedVersion = null

function message(options) {
  const win = getWindow()
  return win && !win.isDestroyed() ? dialog.showMessageBox(win, options) : dialog.showMessageBox(options)
}

function check(manual = false) {
  if (!app.isPackaged) {
    if (manual) void message({ type: "info", title: "OfferPath", message: "Updates are only available in the installed app." })
    return
  }
  manualCheck = manual
  autoUpdater.checkForUpdates().catch(() => { /* reported by the "error" event */ })
}

function setupUpdates(windowGetter) {
  getWindow = windowGetter
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.logger = null

  autoUpdater.on("update-not-available", () => {
    if (manualCheck) void message({ type: "info", title: "OfferPath", message: `OfferPath ${app.getVersion()} is up to date.` })
    manualCheck = false
  })
  autoUpdater.on("error", (error) => {
    // Background checks stay quiet (offline, GitHub busy); retry next interval.
    if (manualCheck) void message({ type: "warning", title: "OfferPath", message: "Could not check for updates.", detail: String(error?.message || error) })
    manualCheck = false
  })
  autoUpdater.on("update-downloaded", async ({ version }) => {
    manualCheck = false
    if (promptedVersion === version) return
    promptedVersion = version
    const { response } = await message({
      type: "info", title: "OfferPath update",
      message: `OfferPath ${version} is ready to install.`,
      detail: "Restart now to update, or it will install the next time you close OfferPath.",
      buttons: ["Restart now", "Later"], defaultId: 0, cancelId: 1,
    })
    if (response === 0) setImmediate(() => autoUpdater.quitAndInstall(true, true))
  })

  check()
  setInterval(check, CHECK_EVERY_MS).unref?.()
}

module.exports = { setupUpdates, checkForUpdates: () => check(true) }
