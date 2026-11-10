// @vitest-environment node
import { expect, it } from 'vitest'
import { build } from 'vite'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { assetImportRetry } from '../asset-import-retry'

it('preserves Vite stylesheet dependencies for retried lazy pages', async () => {
 const root=await mkdtemp(path.join(tmpdir(),'offerpath-css-'))
 try {
  await writeFile(path.join(root,'index.html'),'<script type="module" src="/main.js"></script>')
  await writeFile(path.join(root,'main.js'),'window.openPage=()=>import("./page.js")')
  await writeFile(path.join(root,'page.js'),'import "./page.css"; export default "page"')
  await writeFile(path.join(root,'page.css'),'.fixture-page{display:grid;gap:17px}')
  const result=await build({configFile:false,root,plugins:[assetImportRetry()],logLevel:'silent',build:{write:false,minify:false}})
  const output=Array.isArray(result)?result[0].output:'output' in result?result.output:[]
  const entry=output.find(file=>file.type==='chunk'&&file.isEntry)
  const css=output.find(file=>file.type==='asset'&&file.fileName.endsWith('.css'))
  expect(entry?.type).toBe('chunk');expect(css).toBeDefined()
  if(entry?.type!=='chunk'||!css)throw Error('Missing fixture assets')
  expect(entry.code).toContain(css.fileName)
  expect(entry.code).toContain('__offerpathImport(')
 } finally {await rm(root,{recursive:true,force:true})}
})
