/** Calendar-only display preference. Stored event instants are never rewritten. */
export const CALENDAR_TIMEZONE_KEY = "mailcheck.calendar.timezone"
export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
export function validTimezone(value:string|null):value is string {
  if(!value)return false
  try {new Intl.DateTimeFormat("en",{timeZone:value});return true} catch {return false}
}
export function savedCalendarTimezone() {
  try {const value=localStorage.getItem(CALENDAR_TIMEZONE_KEY);return value==='local'||validTimezone(value)?value:'local'} catch {return 'local'}
}
export function calendarTimezone(params:URLSearchParams, preference=savedCalendarTimezone()) {
  const requested=params.get('calendar_tz')
  return validTimezone(requested)?requested:requested==='local'||preference==='local'?browserTimezone():validTimezone(preference)?preference:browserTimezone()
}
export function timezoneChoices(current:string) {
  const supported=(Intl as typeof Intl & {supportedValuesOf?:(key:string)=>string[]}).supportedValuesOf?.('timeZone') || ['America/Chicago','America/New_York','America/Los_Angeles','Europe/London','Asia/Vladivostok','Asia/Tokyo','Asia/Ho_Chi_Minh']
  return [...new Set(['UTC',browserTimezone(),current,...supported])].filter(validTimezone).sort()
}
const formatters=new Map<string,Intl.DateTimeFormat>()
export function calendarParts(value:Date,timeZone?:string) {
  if(!timeZone)return {key:`${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`,year:value.getFullYear(),month:value.getMonth()+1,day:value.getDate(),minutes:value.getHours()*60+value.getMinutes()+value.getSeconds()/60}
  let formatter=formatters.get(timeZone)
  if(!formatter){formatter=new Intl.DateTimeFormat('en-CA-u-ca-gregory-nu-latn',{timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});formatters.set(timeZone,formatter)}
  const p=Object.fromEntries(formatter.formatToParts(value).map(part=>[part.type,part.value]))
  return {key:`${p.year}-${p.month}-${p.day}`,year:Number(p.year),month:Number(p.month),day:Number(p.day),minutes:Number(p.hour)*60+Number(p.minute)+Number(p.second)/60}
}
/** Date-only carrier for existing calendar navigation; never persist as an instant. */
export function calendarWallTime(value:Date,timeZone?:string) {
  const p=calendarParts(value,timeZone)
  return new Date(p.year,p.month-1,p.day,12)
}
