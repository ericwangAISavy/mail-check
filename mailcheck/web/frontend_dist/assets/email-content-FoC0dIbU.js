import{c as m,r as c,j as g}from"./index-vRhKb1ep.js";/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=m("ArrowUpRight",[["path",{d:"M7 7h10v10",key:"1tivn9"}],["path",{d:"M7 17 17 7",key:"1vkiza"}]]);/**
 * @license lucide-react v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const w=m("RotateCcw",[["path",{d:"M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8",key:"1357e3"}],["path",{d:"M3 3v5h5",key:"1xhq8a"}]]);function x({html:u}){const n=c.useRef(null),a=c.useRef(null),[i,p]=c.useState({foreground:"#e7edf4",background:"#071118",link:"#00c8ed",border:"#24404c"});c.useEffect(()=>{const e=()=>{const t=getComputedStyle(document.documentElement);p({foreground:t.getPropertyValue("--foreground").trim(),background:t.getPropertyValue("--card").trim(),link:t.getPropertyValue("--primary").trim(),border:t.getPropertyValue("--border").trim()})};e();const r=new MutationObserver(e);return r.observe(document.documentElement,{attributes:!0,attributeFilter:["class","data-theme"]}),()=>{var t;r.disconnect(),(t=a.current)==null||t.disconnect()}},[]);const h=`<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${u}<style>
    html { overflow-x: auto; }
    html, body { height: auto !important; min-height: 0 !important; max-height: none !important; }
    body { margin: 0; padding: 0; font-family: Arial, sans-serif; font-size: 14px; line-height: 1.5; overflow-wrap: break-word; }
    body, body * { color: ${i.foreground} !important; background-color: transparent !important; background-image: none !important; border-color: ${i.border} !important; }
    html, body { background-color: ${i.background} !important; }
    a, a * { color: ${i.link} !important; }
    img { max-width: 100%; object-fit: contain; }
    table { max-width: 100%; }
    pre { white-space: pre-wrap; }
  </style></body></html>`,b=()=>{var t,s,l;(t=a.current)==null||t.disconnect();const e=(l=(s=n.current)==null?void 0:s.contentDocument)==null?void 0:l.body;if(!e||!n.current)return;const r=()=>{const o=n.current,d=o==null?void 0:o.contentDocument;!o||!d||(o.style.height="80px",o.style.height=`${Math.max(80,d.documentElement.scrollHeight,e.scrollHeight)+20}px`)};r(),a.current=new ResizeObserver(r),a.current.observe(e)};return g.jsx("iframe",{ref:n,className:"email-original",title:"Original email content",sandbox:"allow-same-origin allow-popups allow-popups-to-escape-sandbox",referrerPolicy:"no-referrer",srcDoc:h,onLoad:b})}export{f as A,x as E,w as R};
