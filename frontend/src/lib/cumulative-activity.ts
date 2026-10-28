/** Convert interval counts to independent running totals; preserve source data. */
export function cumulativeActivity<T extends {counts: Record<string, number>}>(points: T[], ids: string[]): T[] {
  const totals = Object.fromEntries(ids.map(id => [id, 0]))
  return points.map(point => {
    for (const id of ids) totals[id] += Math.max(0, point.counts[id] || 0)
    return {...point, counts: {...totals}}
  })
}
