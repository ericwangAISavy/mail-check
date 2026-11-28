// Taskbar count badge (like Slack's): a red disc with a white number, drawn as
// a bitmap so it needs no font or image files. Counts above 9 show "9+".
const { nativeImage } = require("electron")

// 5x7 pixel glyphs.
const GLYPHS = {
  0: ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
  1: ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
  2: ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
  3: ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
  4: ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
  5: ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
  6: ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
  7: ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
  8: ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
  9: ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
  "+": ["00000", "00100", "00100", "11111", "00100", "00100", "00000"],
}

const OVERLAY = 16 // overlay size in logical px
const DISC = 11 // badge diameter in logical px, matching Slack's taskbar badge
const RED = [0xe0, 0x1e, 0x5a] // r, g, b
// Display scales to draw pixel-exact. Without an exact match Windows resamples
// the bitmap (e.g. 32px -> 20px at 125%), which blurs the digits.
const SCALES = [1, 1.25, 1.5, 1.75, 2, 2.5, 3]

/** BGRA (premultiplied) bitmap of the badge at one display scale. */
function drawBadge(text, scaleFactor) {
  const SIZE = Math.round(OVERLAY * scaleFactor)
  const px = Buffer.alloc(SIZE * SIZE * 4)
  const set = (x, y, [r, g, b], a) => {
    if (x < 0 || y < 0 || x >= SIZE || y >= SIZE) return
    const i = (y * SIZE + x) * 4
    px[i] = Math.round(b * a); px[i + 1] = Math.round(g * a); px[i + 2] = Math.round(r * a); px[i + 3] = Math.round(255 * a)
  }
  // Windows stretches the overlay to fill its square, so draw a Slack-sized
  // badge in the top-right corner and leave the rest transparent.
  const disc = Math.round(DISC * scaleFactor)
  // Whole-pixel glyph blocks keep the digits crisp (7px tall at 100-175%).
  const scale = Math.max(1, Math.floor((disc * 0.65) / 7))
  // Bold: each 5px glyph is smeared one column right, so it is 6 columns wide.
  const width = text.length * 6 * scale + (text.length - 1) * scale
  const pillH = disc, pillW = Math.min(SIZE, Math.max(disc, width + 2 * Math.round(2 * scaleFactor)))
  const x0 = SIZE - pillW, y0 = 0
  // Disc (or pill for two characters) with 4x4 supersampled edges.
  const r = pillH / 2, cy = y0 + r, segL = x0 + r, segR = x0 + pillW - r
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
    let inside = 0
    for (let sy = 0; sy < 4; sy++) for (let sx = 0; sx < 4; sx++) {
      const px_ = x + (sx + 0.5) / 4, py = y + (sy + 0.5) / 4
      const dx = px_ - Math.min(Math.max(px_, segL), segR), dy = py - cy
      if (dx * dx + dy * dy <= r * r) inside++
    }
    if (inside) set(x, y, RED, inside / 16)
  }
  let left = x0 + Math.round((pillW - width) / 2)
  const top = y0 + Math.round((pillH - 7 * scale) / 2)
  for (const ch of text) {
    GLYPHS[ch].forEach((row, gy) => {
      for (let gx = 0; gx < 6; gx++) {
        if (row[gx] !== "1" && row[gx - 1] !== "1") continue
        for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++)
          set(left + gx * scale + dx, top + gy * scale + dy, [255, 255, 255], 1)
      }
    })
    left += 7 * scale
  }
  return { buffer: px, width: SIZE, height: SIZE }
}

/** NativeImage for the given count, or null for no badge. */
function badgeImage(count) {
  if (!Number.isFinite(count) || count <= 0) return null
  const text = count > 9 ? "9+" : String(count)
  const image = nativeImage.createEmpty()
  for (const scaleFactor of SCALES) image.addRepresentation({ scaleFactor, ...drawBadge(text, scaleFactor) })
  return image
}

// Font-rendered badges (like Slack's): a hidden, sandboxed page draws every
// label at every display scale once with the system UI font, then closes. Each
// label is drawn large, its exact pixel bounds are found, and it is scaled into
// the disc's centre, so font hinting cannot push it off-centre.
const LABELS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "9+"]
const FONT_DISC = 14 // logical px of the 16px overlay
const DIGIT_HEIGHT = 0.56 // digit height as a share of the disc, leaving Slack-like padding
let rendered = null // Promise<Map<label, NativeImage> | null>

function renderScript() {
  return `(() => {
    const out = {}, labels = ${JSON.stringify(LABELS)}, scales = ${JSON.stringify(SCALES)}
    const BIG = 200
    // Exact ink box of a label drawn at BIG px.
    function ink(label) {
      const c = document.createElement("canvas"); c.width = BIG * 2; c.height = BIG * 2
      const g = c.getContext("2d")
      g.font = "700 " + BIG + "px 'Segoe UI', system-ui, sans-serif"
      g.fillStyle = "#fff"; g.textBaseline = "alphabetic"; g.fillText(label, BIG / 4, BIG * 1.5)
      const data = g.getImageData(0, 0, c.width, c.height).data
      let x1 = c.width, y1 = c.height, x2 = -1, y2 = -1
      for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
        if (data[(y * c.width + x) * 4 + 3] > 8) { if (x < x1) x1 = x; if (x > x2) x2 = x; if (y < y1) y1 = y; if (y > y2) y2 = y }
      }
      return { canvas: c, x: x1, y: y1, w: x2 - x1 + 1, h: y2 - y1 + 1 }
    }
    // One height for every label (from "8") so digits look consistent.
    const reference = ink("8").h
    for (const label of labels) {
      const glyph = ink(label)
      out[label] = {}
      for (const s of scales) {
        const size = Math.round(${OVERLAY} * s), d = ${FONT_DISC} * s
        const k = (d * ${DIGIT_HEIGHT}) / reference
        const tw = glyph.w * k, th = glyph.h * k
        const w = Math.min(size, Math.max(d, tw + d * 0.56)), h = d
        const x0 = size - w, r = h / 2
        const c = document.createElement("canvas"); c.width = c.height = size
        const g = c.getContext("2d")
        g.fillStyle = "rgb(${RED.join(",")})"
        g.beginPath()
        g.arc(x0 + r, r, r, Math.PI / 2, Math.PI * 1.5)
        g.arc(x0 + w - r, r, r, Math.PI * 1.5, Math.PI / 2)
        g.closePath(); g.fill()
        g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high"
        g.drawImage(glyph.canvas, glyph.x, glyph.y, glyph.w, glyph.h, x0 + (w - tw) / 2, (h - th) / 2, tw, th)
        out[label][s] = c.toDataURL("image/png")
      }
    }
    return out
  })()`
}

function renderBadges() {
  if (rendered) return rendered
  const { BrowserWindow } = require("electron")
  rendered = (async () => {
    const painter = new BrowserWindow({ show: false, width: 64, height: 64,
      skipTaskbar: true, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } })
    try {
      await painter.loadURL("data:text/html,<!doctype html><meta charset=utf-8>")
      const urls = await painter.webContents.executeJavaScript(renderScript())
      const images = new Map()
      for (const label of LABELS) {
        const image = nativeImage.createEmpty()
        for (const scaleFactor of SCALES) image.addRepresentation({ scaleFactor, dataURL: urls[label][scaleFactor] })
        images.set(label, image)
      }
      return images
    } catch {
      return null // fall back to the pixel-font badge
    } finally {
      if (!painter.isDestroyed()) painter.destroy()
    }
  })()
  return rendered
}

/** "(5) OfferPath" -> 5; anything else -> 0. */
const countFromTitle = (title) => Number(/^\((\d+)\)/.exec(title || "")?.[1] || 0)

let shown = -1
/** Show the count on the taskbar (Windows overlay) or dock/launcher badge. */
async function updateBadge(app, win, count) {
  if (count === shown || win.isDestroyed()) return
  shown = count
  if (process.platform !== "win32") {
    app.setBadgeCount(Math.max(0, count))
    return
  }
  let image = null
  if (count > 0) {
    const images = await renderBadges()
    if (count !== shown || win.isDestroyed()) return // a newer count won the race
    image = images?.get(count > 9 ? "9+" : String(count)) ?? badgeImage(count)
  }
  win.setOverlayIcon(image, image ? `${count} item${count === 1 ? "" : "s"} need attention` : "")
}

module.exports = { badgeImage, countFromTitle, renderBadges, updateBadge }
