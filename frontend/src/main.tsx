import { clearAssetRecoveryMarker } from "@/lib/asset-recovery"
import { initAppearance } from "@/lib/appearance"
import "@fontsource-variable/geist/wght.css"
import "./index.css"
import "./cyber.css"
import "./typography.css"
import "./selects.css"
import "./theme-accessibility.css"
import "./professional.css"
import "./compact.css"
import "./design/foundation.css"
import "./design/shell.css"
import "./design/components.css"
import "./design/triage.css"
import "./design/analytics.css"
import "./design/operations.css"
import "./design/workspaces.css"
import "./design/auth-monitoring.css"
import "./design/states.css"
import "./design/appearance.css"
import "./design/themes.css"
import "./design/tables.css"
import "./design/calendar-events.css"
import "./design/workspace-polish.css"
import "./design/menus.css"
import "./design/bidder-management.css"
import "./design/sourcing-table.css"
import "./design/operational-dashboard.css"
import "./components/sidebar-navigation.css"
import "./design/calendar-account-colors.css"
import React from "react"
import ReactDOM from "react-dom/client"
import { createBrowserRouter, RouterProvider } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import App from "./App"
import { AppErrorBoundary } from "./components/app-error-boundary"

// A bounded boot retry may add a cache-busting marker. Remove it before the
// router reads the URL so it cannot override remembered filters or deep links.
try {
  const url = new URL(window.location.href)
  if (url.searchParams.has("_offerpath_boot")) {
    url.searchParams.delete("_offerpath_boot")
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash)
  }
} catch { /* Startup does not depend on optional URL cleanup. */ }

clearAssetRecoveryMarker()

const router = createBrowserRouter([{ path: "*", element: <AppErrorBoundary><App /></AppErrorBoundary> }])
const LocalMonitor = React.lazy(() => import("./components/local-monitor"))
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })

// Match the sign-in screen to this device's saved mode before the workspace mounts.
// A person's own theme is applied once their session is known.
initAppearance()

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        {document.documentElement.dataset.localMonitor === "true"
          ? <React.Suspense fallback={<p>Loading monitoring…</p>}><LocalMonitor/></React.Suspense>
          : <RouterProvider router={router} />}
      </QueryClientProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
)
