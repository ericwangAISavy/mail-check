import { afterEach, beforeEach, expect, it } from "vitest"
import { appearanceIdentity, getAppearance, initAppearance, resetAppearance, setAppearanceIdentity, setMode, setTheme } from "./appearance"

const root = document.documentElement
beforeEach(() => { localStorage.clear(); initAppearance() })
afterEach(() => { localStorage.clear(); setAppearanceIdentity(undefined) })

it("keys appearance by the person, never by workspace or display name", () => {
  expect(appearanceIdentity({ role: "admin", user_id: 7 })).toBe("admin:7")
  expect(appearanceIdentity({ role: "admin" })).toBe("admin:local")
  expect(appearanceIdentity({ role: "bidder", bidder_id: 4 })).toBe("bidder:4")
  expect(appearanceIdentity({ role: null })).toBeUndefined()
})

it("starts in Classic with the device mode before anyone signs in", () => {
  localStorage.setItem("mailcheck.theme", "light"); initAppearance()
  expect(getAppearance()).toEqual({ theme: "classic", mode: "light" })
  expect(root.dataset.palette).toBeUndefined()
  expect(root.dataset.theme).toBe("light")
})

it("keeps each administrator's choice separate across sign-ins", () => {
  setAppearanceIdentity("admin:1"); setTheme("iris"); setMode("dark")
  setAppearanceIdentity("admin:2"); setTheme("midnight"); setMode("light")
  setAppearanceIdentity("admin:9"); setTheme("monograph")
  setAppearanceIdentity(undefined)
  expect(root.dataset.palette).toBeUndefined()
  setAppearanceIdentity("admin:1")
  expect(getAppearance()).toEqual({ theme: "iris", mode: "dark" })
  expect(root.dataset.palette).toBe("iris")
  expect(root.dataset.theme).toBe("dark")
  setAppearanceIdentity("admin:2")
  expect(getAppearance()).toEqual({ theme: "midnight", mode: "light" })
  expect(root.dataset.theme).toBe("light")
  setAppearanceIdentity("admin:9")
  expect(getAppearance().theme).toBe("monograph")
})

it("ignores invalid or corrupted saved values and falls back to Classic", () => {
  localStorage.setItem("offerpath.appearance.v1:admin:3", JSON.stringify({ theme: "neon", mode: "sepia" }))
  setAppearanceIdentity("admin:3")
  expect(getAppearance()).toEqual({ theme: "classic", mode: "dark" })
  localStorage.setItem("offerpath.appearance.v1:admin:4", "{not json")
  setAppearanceIdentity("admin:4")
  expect(getAppearance().theme).toBe("classic")
  expect(setTheme("neon" as never)).toBe(false)
  expect(getAppearance().theme).toBe("classic")
})

it("resets only the signed-in person's appearance", () => {
  setAppearanceIdentity("admin:1"); setTheme("iris")
  setAppearanceIdentity("admin:2"); setTheme("forest"); setMode("light")
  localStorage.setItem("mailcheck.sidebar", "collapsed")
  setAppearanceIdentity("admin:1"); resetAppearance()
  expect(getAppearance()).toEqual({ theme: "classic", mode: "dark" })
  expect(root.dataset.palette).toBeUndefined()
  expect(localStorage.getItem("mailcheck.sidebar")).toBe("collapsed")
  setAppearanceIdentity("admin:2")
  expect(getAppearance()).toEqual({ theme: "forest", mode: "light" })
})

it("reports when this browser cannot remember a choice but still applies it", () => {
  setAppearanceIdentity("admin:5")
  const original = Storage.prototype.setItem
  Storage.prototype.setItem = () => { throw new Error("blocked") }
  try { expect(setTheme("cobalt")).toBe(false) } finally { Storage.prototype.setItem = original }
  expect(root.dataset.palette).toBe("cobalt")
})
