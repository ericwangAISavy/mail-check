import "@fontsource-variable/geist/wght.css"
import "./index.css"
import "./cyber.css"
import "./typography.css"
import React from "react"
import ReactDOM from "react-dom/client"
import { BrowserRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import App from "./App"
import { AppErrorBoundary } from "./components/app-error-boundary"

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false } } })

// Match the sign-in screen to the saved theme before the workspace mounts.
const savedTheme = localStorage.getItem("mailcheck.theme") || "dark"
const initialDark = savedTheme === "dark" || (savedTheme === "system" && matchMedia("(prefers-color-scheme: dark)").matches)
document.documentElement.classList.toggle("dark", initialDark)
document.documentElement.dataset.theme = initialDark ? "dark" : "light"
document.documentElement.style.colorScheme = initialDark ? "dark" : "light"

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter><App /></BrowserRouter>
      </QueryClientProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
)
