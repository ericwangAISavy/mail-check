import { Component, type ErrorInfo, type ReactNode } from "react"
import { isAssetLoadError, recoverPageAssets } from "@/lib/asset-recovery"
import { OfferPathMark } from "@/components/offerpath-mark"
import { Button } from "@/components/ui/button"

type Props = { children: ReactNode }
type State = { error: Error | null; componentStack: string; recovering: boolean; recoveryMessage: string }

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: "", recovering: false, recoveryMessage: "" }
  private active = true
  private recovery: AbortController | null = null
  componentDidMount() { this.active = true; if (this.state.error && isAssetLoadError(this.state.error) && !this.recovery) void this.recover() }
  componentWillUnmount() { this.active = false; this.recovery?.abort(); this.recovery = null }
  private recover = async (manual = false) => {
    this.recovery?.abort()
    const controller = new AbortController(); this.recovery = controller
    this.setState({ recovering: true, recoveryMessage: "Checking connection before reloading…" })
    const result = await recoverPageAssets({ signal: controller.signal, manual })
    if (!this.active || this.recovery !== controller) return
    this.setState({ recovering: false, recoveryMessage: result === "exhausted" ? "Automatic recovery was already attempted. You can try again when the connection is available." : result === "unavailable" ? "Could not reconnect to OfferPath. Keep this page open and try again shortly." : "Reloading the latest page files…" })
  }

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("OfferPath failed while rendering", error, info.componentStack)
    this.setState({ componentStack: info.componentStack || "" })
    if (isAssetLoadError(error) && !this.recovery) void this.recover()
  }

  render() {
    if (this.state.error) {
      const assetError = isAssetLoadError(this.state.error)
      return <main className="recovery-page" role="alert">
        <div className="brand-mark"><OfferPathMark size={34} /></div>
        <p className="eyebrow">SAFE RECOVERY</p>
        <h1>{assetError ? "This page couldn’t finish loading" : "Mail-check couldn’t open this page"}</h1>
        <p className="recovery-description">{assetError ? "The page files could not be downloaded. This can happen during an update or a temporary connection outage." : "An error interrupted the page. Reload to try again. If it happens again, share the technical details below."}</p>
        {assetError ? <><Button disabled={this.state.recovering} onClick={() => void this.recover(true)}>{this.state.recovering ? "Checking connection…" : "Retry loading page"}</Button><p role="status" aria-live="polite">{this.state.recoveryMessage}</p></> : <Button onClick={() => window.location.reload()}>Reload page</Button>}
        <details className="recovery-card" style={{ marginTop: "1.5rem", textAlign: "left" }}>
          <summary>Technical details</summary>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{this.state.error.stack || this.state.error.message}{this.state.componentStack}</pre>
        </details>
      </main>
    }
    return this.props.children
  }
}
