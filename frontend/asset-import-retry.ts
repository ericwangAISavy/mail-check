import type { Plugin } from 'vite'

// Preserve native imports through Vite's dependency analysis so lazy CSS and
// shared preload dependencies remain attached. Wrap only the final imports.
export function assetImportRetry(): Plugin {
  return {
    name: 'offerpath-asset-import-retry',
    apply: 'build',
    // Runtime changes must invalidate content hashes even though wrapping is
    // performed after Vite has resolved the dependency graph.
    augmentChunkHash() { return assetImportRuntime },
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        for (const file of Object.values(bundle)) {
          if (file.type !== 'chunk') continue
          let changed = false
          const code = file.code.replace(/\bimport\(\s*(["'])(\.\/[^"']+)\1\s*\)/g, (_match, quote: string, url: string) => {
            changed = true
            return `__offerpathImport(${quote}${url}${quote},import.meta.url)`
          })
          if (changed) file.code = `${assetImportRuntime}\n${code}`
        }
      },
    },
  }
}

export const assetImportRuntime = `
async function __offerpathImport(path,base){
  const url=new URL(path,base);
  for(let attempt=0;attempt<3;attempt++){
    try{return await import(/* @vite-ignore */ url.href)}
    catch(error){
      if(attempt===2||!(error instanceof Error)||!/Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(error.message))throw error;
      await new Promise(resolve=>setTimeout(resolve,attempt===0?600:1800));
      url.searchParams.set('_offerpath_asset_retry',String(attempt+1));
    }
  }
}
`
