import { useSyncExternalStore } from "react"
import { Check, Monitor, Moon, Palette, Sun } from "lucide-react"
import { THEMES, getAppearance, resetAppearance, resolvedDark, setMode, setTheme, subscribeAppearance, type AppearanceMode } from "@/lib/appearance"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useToast } from "@/components/common"

const MODES: { id: AppearanceMode; label: string; icon: typeof Sun }[] = [
  { id: "system", label: "System", icon: Monitor },
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
]

/** A miniature OfferPath screen drawn only from the theme's own tokens. */
function ThemePreview({ id, dark }: { id: string; dark: boolean }) {
  return <span className="theme-preview" data-palette={id} data-theme={dark ? "dark" : "light"} aria-hidden="true">
    <span className="tp-nav"><i className="tp-brand" /><i /><i className="is-on" /><i /><i /></span>
    <span className="tp-main">
      <span className="tp-head"><i className="tp-title" /><i className="tp-action" /></span>
      <span className="tp-panel"><span className="tp-bars">{[62, 34, 78, 48, 90, 56].map((h, i) => <i key={i} style={{ height: `${h}%`, background: `var(--category-color-${i % 5})` }} />)}</span></span>
      <span className="tp-rows"><i /><i className="is-on" /><i /></span>
    </span>
  </span>
}

/** Personal appearance: applies at once, saved for this person only, independent of the settings form. */
export function AppearanceSettings() {
  const { theme, mode } = useSyncExternalStore(subscribeAppearance, getAppearance)
  const toast = useToast()
  const dark = resolvedDark(mode)
  const remembered = (ok: boolean) => { if (!ok) toast("Your appearance changed, but this browser could not save it. It will return to the previous look next time.", "error") }
  const reset = () => { remembered(resetAppearance()); toast("Appearance reset to Classic Cyan, dark mode.", "success") }
  return <section id="appearance" className="settings-section">
    <div className="settings-section-title"><span className="section-symbol"><Palette size={17} /></span><div><h2>Appearance</h2><p>Choose your theme and color mode.</p></div></div>
    <Card className="settings-card appearance-card">
      <fieldset className="appearance-mode">
        <legend>Mode</legend>
        <div className="appearance-segments">{MODES.map(({ id, label, icon: Icon }) =>
          <label key={id} className="appearance-segment"><input type="radio" name="appearance-mode" value={id} checked={mode === id} onChange={() => remembered(setMode(id))} /><Icon size={14} aria-hidden="true" />{label}</label>)}
        </div>
      </fieldset>
      <fieldset className="appearance-themes">
        <legend>Theme</legend>
        <div className="theme-grid">{THEMES.map(option =>
          <label key={option.id} className="theme-option">
            <input type="radio" name="appearance-theme" value={option.id} checked={theme === option.id} onChange={() => remembered(setTheme(option.id))} />
            <ThemePreview id={option.id} dark={dark} />
            <span className="theme-label"><span className="theme-name">{option.name}</span>{theme === option.id && <Check size={14} aria-hidden="true" />}</span>
            <span className="theme-note">{option.note}</span>
          </label>)}
        </div>
      </fieldset>
      <div className="appearance-footer">
        <p className="form-hint">Saved for you in this browser. Your choice does not change anyone else's.</p>
        <Button variant="outline" size="sm" onClick={reset} disabled={theme === "classic" && mode === "dark"}>Reset appearance</Button>
      </div>
    </Card>
  </section>
}
