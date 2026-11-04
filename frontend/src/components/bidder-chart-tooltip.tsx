import { useLayoutEffect, useRef, type RefObject } from "react"
import { createPortal } from "react-dom"
import type { TooltipProps } from "recharts"

type Props = Pick<TooltipProps<number, string>, "active" | "payload" | "coordinate"> & {
  title: string
  chart: RefObject<HTMLDivElement | null>
}

/** Escape chart/card overflow while keeping long lists inside the viewport. */
export function BidderChartTooltip({ active, payload, coordinate, title, chart }: Props) {
  const popup = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!active || !payload?.length) return
    const place = () => {
      const element = popup.current
      const anchor = chart.current
      if (!element || !anchor) return
      const rect = anchor.getBoundingClientRect()
      const { width, height } = element.getBoundingClientRect()
      const x = rect.left + (coordinate?.x ?? 0) + 12
      const y = rect.top + (coordinate?.y ?? 0) + 12
      element.style.left = `${Math.max(12, Math.min(x, window.innerWidth - width - 12))}px`
      element.style.top = `${Math.max(12, Math.min(y, window.innerHeight - height - 12))}px`
    }
    place()
    window.addEventListener("resize", place)
    window.addEventListener("scroll", place, true)
    return () => {
      window.removeEventListener("resize", place)
      window.removeEventListener("scroll", place, true)
    }
  }, [active, payload, coordinate?.x, coordinate?.y, title, chart])
  if (!active || !payload?.length) return null
  return createPortal(<div ref={popup} role="tooltip" className="bidder-chart-tooltip"
    onMouseMove={event => event.stopPropagation()}>
    <div className="bidder-chart-tooltip-title">{title}</div>
    <div className="bidder-chart-tooltip-list" tabIndex={0} aria-label="Activity counts">
      {payload.map((item, index) => <div className="bidder-chart-tooltip-item" key={String(item.dataKey ?? index)} style={{ color: item.color }}>
        <span>{item.name}</span><strong>{item.value ?? 0}</strong>
      </div>)}
    </div>
  </div>, document.body)
}
