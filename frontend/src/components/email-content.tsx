import { useEffect, useRef, useState } from "react"

/** Email styles stay inside the frame; scripts and remote resources cannot run. */
export function EmailContent({ html }: { html: string }) {
  const frame = useRef<HTMLIFrameElement>(null)
  const observer = useRef<ResizeObserver | null>(null)
  const [palette, setPalette] = useState({ foreground: "#e7edf4", background: "#071118", link: "#00c8ed", border: "#24404c" })
  useEffect(() => {
    const update = () => {
      const style = getComputedStyle(document.documentElement)
      setPalette({ foreground: style.getPropertyValue("--foreground").trim(), background: style.getPropertyValue("--card").trim(), link: style.getPropertyValue("--primary").trim(), border: style.getPropertyValue("--border").trim() })
    }
    update()
    const theme = new MutationObserver(update)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] })
    return () => { theme.disconnect(); observer.current?.disconnect() }
  }, [])
  const documentHtml = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${html}<style>
    html { overflow-x: auto; }
    body { margin: 0; padding: 0; font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; overflow-wrap: break-word; }
    body, body * { color: ${palette.foreground} !important; background-color: transparent !important; background-image: none !important; border-color: ${palette.border} !important; }
    html, body { background-color: ${palette.background} !important; }
    a, a * { color: ${palette.link} !important; }
    img { max-width: 100%; object-fit: contain; }
    table { max-width: 100%; }
    pre { white-space: pre-wrap; }
  </style></body></html>`
  const loaded = () => {
    observer.current?.disconnect()
    const body = frame.current?.contentDocument?.body
    if (!body || !frame.current) return
    const resize = () => {
      if (frame.current) frame.current.style.height = `${Math.max(80, Math.ceil(body.getBoundingClientRect().height) + 20)}px`
    }
    resize()
    observer.current = new ResizeObserver(resize)
    observer.current.observe(body)
  }
  return <iframe ref={frame} className="email-original" title="Original email content" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={documentHtml} onLoad={loaded} />
}
