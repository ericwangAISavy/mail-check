import "./dashboard-metrics.css"
import { usePageState } from "@/lib/page-state"
import { lazy, Suspense, useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"

import { ArrowRight, CheckCircle2, Clock3, FilterX, HelpCircle, LoaderCircle, Mail, RefreshCw, SlidersHorizontal } from "lucide-react"
import { api } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { EmptyState, Loading, PageHeading, useToast } from "@/components/common"

const ApplicationActivityChart = lazy(() => import("@/components/application-activity-chart"))
const ProfileQuality = lazy(() => import("@/components/profile-quality"))

const colors = Array.from({length:10},(_,index)=>`var(--category-color-${index})`)
const isoToday = () => new Intl.DateTimeFormat("en-CA").format(new Date())


export default function DashboardPage({ bootstrap, readOnly = false }: { bootstrap: Bootstrap; readOnly?: boolean }) {
  const [search, setSearch] = useSearchParams()
  const [advanced, setAdvanced] = usePageState("dashboard", "advanced", false)
  const toast = useToast()
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  const params = useMemo(() => {
    const value = new URLSearchParams()
    value.set("days", search.get("days") || "7")
    value.set("interval", search.get("interval") === "week" ? "week" : "day")
    value.set("tz", search.get("tz") || zone)
    for (const key of ["start", "end", "account", "bidder", "status", "action"]) if (search.has(key)) value.set(key, search.get(key)!)
    for (const category of search.getAll("category")) value.append("category", category)
    value.set("page", search.get("page") || "1")
    value.set("page_size", "50")
    return value
  }, [search, zone])
  const { data, isPending, isFetching, error, refetch } = useQuery({ queryKey: ["dashboard", params.toString(), false], queryFn: ({ signal }) => api.dashboard(params, signal, false), placeholderData: (previous) => previous })
  const accountDetails = useQuery({ queryKey: ["accounts"], queryFn: ({ signal }) => api.accounts(signal), enabled: !readOnly && !!data })
  const { data: accounts } = useQuery({ queryKey: ["dashboard-accounts"], queryFn: ({ signal }) => api.dashboardAccounts(signal) })
  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(changes)) {
      if (key === "category") next.delete("category")
      if (value) next.set(key, value); else next.delete(key)
    }
    if (!("page" in changes)) next.delete("page")
    if (["start", "end", "days", "tz"].some((key) => key in changes)) {
      if (!("focus_date" in changes)) next.delete("focus_date")
      if (!("focus_category" in changes)) next.delete("focus_category")
    }
    setSearch(next)
  }
  const toggleCategory = (name: string) => {
    const next = new URLSearchParams(search)
    const selected = next.getAll("category")
    next.delete("category")
    for (const item of selected.includes(name) ? selected.filter((item) => item !== name) : [...selected, name]) next.append("category", item)
    next.delete("page")
    setSearch(next)
  }
  const refresh = async () => {
    const result = await refetch()
    if (result.error) toast(result.error.message || "Could not refresh activity.", "error")
    else toast("Activity refreshed.", "success")
  }
  const summary = data?.summary as Record<string, number> | undefined
  const categories = (data?.categories || bootstrap.taxonomy.map((item) => ({ ...item, count: 0 }))) as { name: string; label: string; tier: string; count: number }[]
  const series = data?.daily || []
  const intervalRows = useMemo(() => {
    if (params.get("interval") !== "week" || !series.length) return series
    const weeks = new Map<string, { date: string; total: number; partial: boolean; counts: Record<string, number> }>()
    for (const day of series) {
      const date = new Date(`${day.date}T00:00:00Z`)
      const weekday = date.getUTCDay()
      date.setUTCDate(date.getUTCDate() - ((weekday + 6) % 7))
      const week = date.toISOString().slice(0, 10)
      const item = weeks.get(week) || { date: week, total: 0, partial: false, counts: {} }
      item.total += day.total; item.partial ||= day.partial
      for (const [category, count] of Object.entries(day.counts as Record<string, number>)) item.counts[category] = (item.counts[category] || 0) + count
      weeks.set(week, item)
    }
    return [...weeks.values()]
  }, [series, params])
  const filterCount = params.getAll("category").length + ["account", "bidder", "status", "action"].filter((key) => params.has(key)).length
  const clear = () => { setSearch(new URLSearchParams({ tz: zone, days: "7" })) }
  if (error && !data) return <div className="page-wrap"><EmptyState title="Dashboard is unavailable" description={error instanceof Error ? error.message : "Try loading this dashboard again."} action={<div className="flex flex-wrap justify-center gap-2"><Button onClick={() => void refetch()}>Try again</Button>{search.toString()&&<Button variant="outline" onClick={clear}>Clear filters</Button>}</div>} /></div>
  return <div className="page-wrap analytics-page">
    <PageHeading title="Dashboard" description="A little perspective on the applications in motion." action={!readOnly && <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refresh()}>{isFetching ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}Refresh</Button>} />
    {error && data && <p role="alert" className="inline-error">Could not update this view: {error.message}. Showing the last loaded results.</p>}
    <div className="dashboard-filters cyber-panel"><div className="field-compact"><label htmlFor="range">Date range</label><select id="range" value={params.has("start") ? "custom" : params.get("days") || "7"} onChange={(e) => e.target.value === "custom" ? update({ start: new Intl.DateTimeFormat("en-CA").format(new Date(new Date().setDate(new Date().getDate() - 29))), end: isoToday() }) : update({ start: null, end: null, days: e.target.value })}><option value="7">Last 7 days</option><option value="14">Last 14 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="custom">Custom range</option></select></div>
      {params.has("start") && <><div className="field-compact"><label htmlFor="start">From</label><input id="start" type="date" value={params.get("start") || ""} onChange={(e) => update({ start: e.target.value })} /></div><div className="field-compact"><label htmlFor="end">Through</label><input id="end" type="date" value={params.get("end") || ""} onChange={(e) => update({ end: e.target.value })} /></div></>}
      <div className="field-compact"><label htmlFor="interval">Group by</label><select id="interval" value={params.get("interval") || "day"} onChange={(e) => update({ interval: e.target.value })}><option value="day">Day</option><option value="week">Week</option></select></div>
      <div className="field-compact"><label htmlFor="account">Account</label><select id="account" value={params.get("account") || ""} onChange={(e) => update({ account: e.target.value })}><option value="">All accounts</option>{accounts?.accounts.map((account) => <option value={account.label} key={account.label}>{account.label}</option>)}</select></div>
      {!readOnly && <div className="field-compact"><label htmlFor="bidder">Bidder</label><select id="bidder" value={params.get("bidder") || ""} onChange={(e) => update({ bidder: e.target.value })}><option value="">All bidders</option>{accounts?.bidders?.map((bidder) => <option value={bidder.id} key={bidder.id}>{bidder.name}</option>)}</select></div>}
      {!readOnly && <div className="field-compact"><label htmlFor="status">Status</label><select id="status" value={params.get("status") || "all"} onChange={(e) => update({ status: e.target.value === "all" ? null : e.target.value })}><option value="all">All mail</option><option value="pending">Open</option><option value="done">Completed</option></select></div>}
      {!readOnly && <Button variant={advanced ? "secondary" : "outline"} size="sm" aria-expanded={advanced} onClick={() => setAdvanced((value) => !value)}><SlidersHorizontal size={14} />More</Button>}
      {filterCount > 0 && <Button variant="ghost" size="sm" onClick={clear}><FilterX size={14} />Reset</Button>}</div>
    {!readOnly && advanced && <div className="advanced-filters"><label>Action<select value={params.get("action") || "all"} onChange={(e) => update({ action: e.target.value === "all" ? null : e.target.value })}><option value="all">All actions</option><option value="yes">Action required</option><option value="no">No action required</option></select></label><span className="filter-caption">Select categories below to narrow the timeline.</span></div>}
    {isPending && !data ? <Loading label={"Gathering your local mail history\u2026"} /> : <>
    <div className={`dashboard-layout${readOnly ? " graphs-only" : ""}`}><div className="dashboard-primary">
    <dl className="dashboard-metrics" aria-label="Mail summary">{[
      { label: "Messages collected", value: summary?.total, Icon: Mail },
      { label: "Need your attention", value: summary?.pending_attention, Icon: Clock3 },
      { label: "Completed", value: summary?.completed, Icon: CheckCircle2 },
      { label: "Unclassified", value: summary?.unclassified, Icon: HelpCircle },
    ].map(({ label, value, Icon }) => (
      <div className="dashboard-metric" key={label}>
        <dt><Icon size={17} aria-hidden="true" />{label}</dt>
        <dd>{value == null ? "—" : value.toLocaleString()}</dd>
      </div>
    ))}</dl>
    <div className="analytics-main-grid"><Card className="chart-card activity-chart-card"><div className="card-title-row"><div><p className="eyebrow">ACTIVITY</p><h2>Applications over time</h2><p className="page-description">{readOnly ? "Application activity for your assigned accounts." : ""}</p></div></div>
      <div className="timeline-ranges" role="group" aria-label="Timeline range">{[["7", "1 week"], ["14", "2 weeks"], ["30", "1 month"], ["90", "3 months"]].map(([days, label]) => <Button key={days} type="button" size="sm" variant={!params.has("start") && params.get("days") === days ? "secondary" : "ghost"} aria-pressed={!params.has("start") && params.get("days") === days} onClick={() => update({ days, start: null, end: null })}>{label}</Button>)}</div>
      <Suspense fallback={<Loading label="Loading chart..." />}><ApplicationActivityChart rows={intervalRows} categories={categories} colors={colors}/></Suspense>
      <div className="chart-legend">{categories.filter((category) => category.count).map((category) => <button key={category.name} onClick={() => toggleCategory(category.name)}><span style={{ backgroundColor: colors[categories.findIndex((item) => item.name === category.name) % colors.length] }} />{category.label}<b>{category.count}</b></button>)}</div>
      <details className="accessible-chart-data"><summary>View chart data as a table</summary><div className="table-scroll"><table><thead><tr><th>Date</th>{categories.map((c) => <th key={c.name}>{c.label}</th>)}<th>Total</th></tr></thead><tbody>{intervalRows.map((row: any) => <tr key={row.date}><th>{row.date}{row.partial ? " *" : ""}</th>{categories.map((c) => <td key={c.name}>{row.counts?.[c.name] || 0}</td>)}<td>{row.total}</td></tr>)}</tbody></table></div></details>
    </Card>
      </div></div>
      {!readOnly && <aside className="dashboard-rail" aria-label="Mail information">
        <Card className="account-status-panel"><div className="rail-heading"><p className="eyebrow">ACCOUNT STATUS</p>{!readOnly && <Link to="/accounts">Manage accounts <ArrowRight size={14} /></Link>}</div>
          {!readOnly && accountDetails.error && <p role="alert" className="inline-error">Account status could not be loaded.</p>}
          {accounts?.accounts.length ? <ul className="account-status-list">{accounts.accounts.map((account) => {
            const detail = accountDetails.data?.accounts.find((item) => item.label === account.label)
            return <li key={account.label}><span className={`status-dot ${detail?.enabled === false ? "is-paused" : ""}`} /><span title={detail?.email || account.label}>{detail?.email || account.label}</span>{detail && <Badge variant="outline">{detail.enabled ? "Enabled" : "Paused"}</Badge>}</li>
          })}</ul> : <p className="rail-empty">No mail accounts configured.</p>}
          <p className="rail-context">{readOnly ? "Mailboxes represented in local history." : ""}</p>
        </Card>
      </aside>}</div>
    {data && <Suspense fallback={<Loading label="Loading profile quality..." />}><ProfileQuality outcomes={data.profile_outcomes} /></Suspense>}
    </>}
  </div>
}
