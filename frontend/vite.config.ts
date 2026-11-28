import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { assetImportRetry } from "./asset-import-retry"
import { liveSafeOutput } from "./live-safe-output"

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss(), assetImportRetry(), liveSafeOutput(path.resolve(rootDir, "public"))],
  resolve: { alias: { "@": path.resolve(rootDir, "./src") } },
  build: {
    outDir: "../mailcheck/web/frontend_dist",
    // Never empty the live folder first; liveSafeOutput removes stale assets afterwards.
    emptyOutDir: false,
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: true,
    // Preserve the browser's Host so the backend can compare the full Origin
    // (including its port) without granting a separate development exception.
    proxy: { "/api": { target: "http://127.0.0.1:52400", changeOrigin: false } },
  },
})
