import {expect,it,vi} from 'vitest'
import {weeklyPaymentReport,copyPaymentReport} from './payment-report'
const address='0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD'
it('formats recorded weekly payments exactly and keeps wallet casing',()=>{
 const report=weeklyPaymentReport([{name:'Dany',wallet_network:'USDT.BEP20',wallet_address:address,payment:{amount_cents:4400}},{name:'Daniel',wallet_network:'USDT.BEP20',wallet_address:address,payment:{amount_cents:1970}}])
 expect(report).toEqual({text:`$44 -> USDT.BEP20 -> \`${address}\` -> Bidder -> Dany\n$19.70 -> USDT.BEP20 -> \`${address}\` -> Bidder -> Daniel\n${'='.repeat(80)}\nTotal: $63.7`,issues:[]})
})
it('flags missing details without inventing a payout or wallet',()=>{
 const report=weeklyPaymentReport([{name:'Dany',payment:null}])
 expect(report.text).toBe('');expect(report.issues[0]).toContain('Dany: missing payment amount (set a rate or manual amount), payment network, wallet address')
})

it('falls back to selection copying on HTTP browsers and cleans up the temporary field',async()=>{
 const clipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard'),exec=Object.getOwnPropertyDescriptor(document,'execCommand')
 const copy=vi.fn(()=>true)
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined})
 Object.defineProperty(document,'execCommand',{configurable:true,value:copy})
 try{await copyPaymentReport('payment lines');expect(copy).toHaveBeenCalledWith('copy');expect(document.querySelector('textarea')).toBeNull()}
 finally{if(clipboard)Object.defineProperty(navigator,'clipboard',clipboard);else Reflect.deleteProperty(navigator,'clipboard');if(exec)Object.defineProperty(document,'execCommand',exec);else Reflect.deleteProperty(document,'execCommand')}
})
it('copies calculated or manually overridden amounts before a payment is marked paid',()=>{
 const result=weeklyPaymentReport([{name:'Dany',wallet_network:'USDT.BEP20',wallet_address:address,payment:null,payable_amount_cents:1854}])
 expect(result.issues).toEqual([]);expect(result.text).toContain('$18.54 -> USDT.BEP20')
 const paid=weeklyPaymentReport([{name:'Dany',wallet_network:'USDT.BEP20',wallet_address:address,payment:{amount_cents:4400},payable_amount_cents:1854}])
 expect(paid.text).toContain('$44 ->')
})

it('adds the combined confirmed payment total from integer cents',()=>{
 const values=[1945,2045,2055,1775]
 const report=weeklyPaymentReport(values.map((value,i)=>({name:['Tom','Muazzin','Isaish','Manam'][i],wallet_network:'USDT.BEP20',wallet_address:address,payment:null,payable_amount_cents:value})))
 expect(report.issues).toEqual([])
 expect(report.text.split('\n')).toHaveLength(6)
 expect(report.text.endsWith('='.repeat(80)+'\nTotal: $78.2')).toBe(true)
 expect(weeklyPaymentReport([]).text).toBe('')
})
