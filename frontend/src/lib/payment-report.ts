export type PayoutBidder={name:string;wallet_network?:string;wallet_address?:string;payment:{amount_cents:number}|null;payable_amount_cents?:number|null}
export function weeklyPaymentReport(bidders:PayoutBidder[]) {
 const issues:string[]=[],lines:string[]=[]
 let totalCents=0
 for(const bidder of bidders){
  const missing:string[]=[]
  const amountCents=bidder.payment?.amount_cents ?? bidder.payable_amount_cents
  if(amountCents==null)missing.push('payment amount (set a rate or manual amount)')
  if(!bidder.wallet_network?.trim())missing.push('payment network')
  if(!bidder.wallet_address?.trim())missing.push('wallet address')
  if(missing.length){issues.push(`${bidder.name}: missing ${missing.join(', ')}.`);continue}
  totalCents+=amountCents!
  const amount=(amountCents!/100).toFixed(2).replace(/\.00$/,'')
  lines.push(`$${amount} -> ${bidder.wallet_network!.trim()} -> \`${bidder.wallet_address!.trim()}\` -> Bidder -> ${bidder.name.replace(/[\r\n]+/g,' ')}`)
 }
 if(lines.length&&!issues.length)lines.push('='.repeat(80),`Total: $${(totalCents/100).toFixed(2).replace(/\.?0+$/,'')}`)
 return {text:lines.join('\n'),issues}
}
export async function copyPaymentReport(text:string){
 try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);return}}catch{/* HTTP browsers can use the selection fallback below. */}
 const previous=document.activeElement as HTMLElement|null
 const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.top='0';area.style.left='-9999px';document.body.appendChild(area);area.select()
 try{if(!document.execCommand?.('copy'))throw new Error('Automatic copy is unavailable. Select and copy the report below.')}finally{area.remove();previous?.focus()}
}
