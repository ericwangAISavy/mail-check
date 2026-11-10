import type { Plugin } from 'vite'

// Rollup supplies the final hashed URL here, avoiding runtime guesses about
// which page or shared dependency failed. Keep native imports in development.
export function assetImportRetry(): Plugin {
  return {
    name: 'offerpath-asset-import-retry',
    apply: 'build',
    renderDynamicImport({ targetModuleId }) {
      if (!targetModuleId) return null
      return { left: '__offerpathImport(', right: ',import.meta.url)' }
    },
    renderChunk(code) {
      if (!code.includes('__offerpathImport(')) return null
      return { code: `${assetImportRuntime}\n${code}`, map: null }
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
