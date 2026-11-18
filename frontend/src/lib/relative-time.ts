/** "Updated 20 seconds ago"-style freshness, ticking from the caller's clock. */
export function timeAgo(date: Date, now: number) {
  const seconds = Math.max(0, Math.round((now - date.getTime()) / 1000))
  if (seconds < 10) return "just now"
  if (seconds < 60) return `${seconds} seconds ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return minutes === 1 ? "1 min ago" : `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return hours === 1 ? "1 hour ago" : `${hours} hours ago`
  return date.toLocaleDateString()
}

export function parseStamp(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date : null
}
