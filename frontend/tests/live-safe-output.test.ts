// @vitest-environment node
import {expect,it} from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {liveSafeOutput} from '../live-safe-output'

it('retains recently replaced chunks for open pages and expires older assets',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'offerpath-assets-'))
 try{
  const assets=path.join(root,'dist','assets')
  fs.mkdirSync(assets,{recursive:true})
  fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({version:'9.8.7'}))
  for(const name of ['current.js','open-page.js','expired.js'])fs.writeFileSync(path.join(assets,name),'export default 1')
  const old=new Date(Date.now()-48*60*60*1000)
  fs.utimesSync(path.join(assets,'expired.js'),old,old)
  const plugin=liveSafeOutput(path.join(root,'public'))
  ;(plugin.configResolved as Function)({root,build:{outDir:'dist'}})
  ;(plugin.writeBundle as Function).call({warn:()=>{}},{},{'assets/current.js':{}})
  expect(fs.existsSync(path.join(assets,'current.js'))).toBe(true)
  expect(fs.existsSync(path.join(assets,'open-page.js'))).toBe(true)
  expect(fs.existsSync(path.join(assets,'expired.js'))).toBe(false)
  expect(JSON.parse(fs.readFileSync(path.join(assets,'build-info.json'),'utf8')).version).toBe('9.8.7')
 }finally{fs.rmSync(root,{recursive:true,force:true})}
})
