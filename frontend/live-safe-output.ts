import fs from "node:fs"
import path from "node:path"
import type { Plugin } from "vite"

/**
 * The build writes straight into the folder a running OfferPath server serves.
 * Vite's emptyOutDir deletes that folder before writing, which leaves the live
 * site without its files mid-build, and on Windows a file the server holds open
 * makes the delete fail halfway (EBUSY), leaving the site broken.
 *
 * Never empty first. Keep older chunks for 24 hours so open browser tabs can
 * still import their dependencies after a rebuild. Expire them on later builds,
 * skipping any file that is still locked.
 */
export function liveSafeOutput(publicDir: string): Plugin {
  let outDir = ""
  return {
    name: "offerpath-live-safe-output",
    apply: "build",
    configResolved(config) { outDir = path.resolve(config.root, config.build.outDir) },
    writeBundle(_options, bundle) {
      const keep = new Set(Object.keys(bundle).map((name) => path.normalize(name)))
      const walk = (dir: string, base: string): string[] => fs.existsSync(dir)
        ? fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => entry.isDirectory()
          ? walk(path.join(dir, entry.name), path.join(base, entry.name))
          : [path.join(base, entry.name)])
        : []
      for (const name of walk(publicDir, "")) keep.add(path.normalize(name))
      for (const name of walk(path.join(outDir, "assets"), "assets")) {
        if (keep.has(path.normalize(name))) continue
        try {
          if (Date.now() - fs.statSync(path.join(outDir, name)).mtimeMs < 24 * 60 * 60 * 1000) continue
          fs.unlinkSync(path.join(outDir, name))
        } catch (error) {
          const code = (error as NodeJS.ErrnoException).code
          if (code !== "EBUSY" && code !== "EPERM" && code !== "ENOENT") throw error
          this.warn(`Left ${name} in place (${code}); it is removed on a later build.`)
        }
      }
    },
  }
}
