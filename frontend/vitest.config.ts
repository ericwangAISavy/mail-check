import { defineConfig } from "vitest/config"
import path from "node:path"
import { fileURLToPath } from "node:url"

// Newer Node versions define their own `localStorage` global, which is undefined
// without a storage file and hides the one jsdom provides. Turn Node's off in the
// test workers; older Node versions do not know the flag, so check first.
const withoutNodeStorage = ["--no-experimental-webstorage", "--no-webstorage"]
  .filter((flag) => process.allowedNodeEnvironmentFlags.has(flag.replace("--no-", "--")))
  .slice(0, 1)

export default defineConfig({
  resolve: { alias: { "@": path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src") } },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "tests/**/*.test.ts"],
    execArgv: withoutNodeStorage,
  },
})
