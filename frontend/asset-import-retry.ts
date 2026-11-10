import type { Plugin } from 'vite'

// Preserve native imports through Vite's dependency analysis so lazy CSS and
// shared preload dependencies remain attached. Wrap only the final imports.
export function assetImportRetry(): Plugin {
  return {
    name: 'offerpath-asset-import-retry',
    apply: 'build',
    // Runtime changes must invalidate content hashes even though wrapping is
    // performed after Vite has resolved the dependency graph.
    augmentChunkHash() { return "ast-v1:" + assetImportRuntime },
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        for (const file of Object.values(bundle)) {
          if (file.type !== 'chunk') continue
          const imports: {start: number; end: number; url: string}[] = []
          const nodes: unknown[] = [this.parse(file.code)]
          while (nodes.length) {
            const value = nodes.pop()
            if (!value || typeof value !== 'object') continue
            if (Array.isArray(value)) { nodes.push(...value); continue }
            const node = value as Record<string, unknown>
            if (node.type === 'ImportExpression' && typeof node.start === 'number' && typeof node.end === 'number') {
              const source = node.source as {type?: string; value?: unknown}
              if (source?.type === 'Literal' && typeof source.value === 'string' && source.value.startsWith('./')) {
                imports.push({start: node.start, end: node.end, url: source.value})
              }
            }
            nodes.push(...Object.values(node))
          }
          let code = file.code
          for (const item of imports.sort((a,b) => b.start-a.start)) {
            code = code.slice(0,item.start) + `__offerpathImport(${JSON.stringify(item.url)},import.meta.url)` + code.slice(item.end)
          }
          if (imports.length) file.code = `${assetImportRuntime}\n${code}`
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
