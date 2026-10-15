import path from "node:path"
import { fileURLToPath } from "node:url"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(rootDir, "./src") } },
  build: {
    outDir: "../mailcheck/web/frontend_dist",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    strictPort: true,
    // Preserve the browser's Host so the backend can compare the full Origin
    // (including its port) without granting a separate development exception.
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
})
