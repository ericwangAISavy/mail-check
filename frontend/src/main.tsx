import { clearAssetRecoveryMarker } from "@/lib/asset-recovery"
import { readBrowserPreference } from "@/lib/browser-preferences"
import "@fontsource-variable/geist/wght.css"
import "./index.css"
import "./cyber.css"
import "./typography.css"
import "./selects.css"
import "./theme-accessibility.css"
import "./components/sidebar-navigation.css"
import "./professional.css"
import "./compact.css"
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
const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })

// Match the sign-in screen to the saved theme before the workspace mounts.
const savedTheme = readBrowserPreference("mailcheck.theme", "dark")
const initialDark = savedTheme === "dark" || (savedTheme === "system" && matchMedia("(prefers-color-scheme: dark)").matches)
document.documentElement.classList.toggle("dark", initialDark)
document.documentElement.dataset.theme = initialDark ? "dark" : "light"
document.documentElement.style.colorScheme = initialDark ? "dark" : "light"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
)
