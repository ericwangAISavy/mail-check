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

const SIZE = 32 // drawn at 2x for a 16px overlay
const RED = [0xe0, 0x1e, 0x5a] // r, g, b

/** NativeImage for the given count, or null for no badge. */
function badgeImage(count) {
  if (!Number.isFinite(count) || count <= 0) return null
  const text = count > 9 ? "9+" : String(count)
  const px = Buffer.alloc(SIZE * SIZE * 4) // BGRA, premultiplied
  const set = (x, y, [r, g, b], a) => {
    const i = (y * SIZE + x) * 4
    px[i] = Math.round(b * a); px[i + 1] = Math.round(g * a); px[i + 2] = Math.round(r * a); px[i + 3] = Math.round(255 * a)
  }
  // Disc with 4x4 supersampled edges.
  const c = SIZE / 2, radius = SIZE / 2 - 0.5
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
    let inside = 0
    for (let sy = 0; sy < 4; sy++) for (let sx = 0; sx < 4; sx++) {
      const dx = x + (sx + 0.5) / 4 - c, dy = y + (sy + 0.5) / 4 - c
      if (dx * dx + dy * dy <= radius * radius) inside++
    }
    if (inside) set(x, y, RED, inside / 16)
  }
  // White glyphs, each glyph pixel a 3x3 block (2px for two characters).
  const scale = text.length > 1 ? 2 : 3
  const width = text.length * 5 * scale + (text.length - 1) * scale
  let left = Math.round((SIZE - width) / 2)
  const top = Math.round((SIZE - 7 * scale) / 2)
  for (const ch of text) {
    GLYPHS[ch].forEach((row, gy) => [...row].forEach((on, gx) => {
      if (on !== "1") return
      for (let dy = 0; dy < scale; dy++) for (let dx = 0; dx < scale; dx++)
        set(left + gx * scale + dx, top + gy * scale + dy, [255, 255, 255], 1)
    }))
    left += 6 * scale
  }
  return nativeImage.createFromBitmap(px, { width: SIZE, height: SIZE, scaleFactor: 2 })
}

/** "(5) OfferPath" -> 5; anything else -> 0. */
const countFromTitle = (title) => Number(/^\((\d+)\)/.exec(title || "")?.[1] || 0)

let shown = -1
/** Show the count on the taskbar (Windows overlay) or dock/launcher badge. */
function updateBadge(app, win, count) {
  if (count === shown || win.isDestroyed()) return
  shown = count
  if (process.platform === "win32") {
    const image = badgeImage(count)
    win.setOverlayIcon(image, image ? `${count} item${count === 1 ? "" : "s"} need attention` : "")
  } else {
    app.setBadgeCount(Math.max(0, count))
  }
}

module.exports = { badgeImage, countFromTitle, updateBadge }
