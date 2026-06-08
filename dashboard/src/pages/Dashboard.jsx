import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { getStats, getRuns, getCampaigns } from "../api"

export default function Dashboard() {
  const [stats, setStats] = useState({ total_leads: 0, emails_sent: 0, replies: 0, active_campaigns: 0 })
  const [runs, setRuns] = useState([])
  const [campaigns, setCampaigns] = useState([])

  useEffect(() => {
    getRuns().then(r => setRuns(r.data.slice(0, 5))).catch(() => {})
    getCampaigns().then(r => setCampaigns(r.data)).catch(() => {})
    // Stats endpoint — fallback if not available yet
    getStats().then(r => setStats(r.data)).catch(() => {})
  }, [])

  const METRICS = [
    { label: "Total leads", val: stats.total_leads?.toLocaleString() || "—", delta: "" },
    { label: "Emails sent", val: stats.emails_sent?.toLocaleString() || "—", delta: "" },
    { label: "Replies", val: stats.replies?.toLocaleString() || "—", delta: "" },
    { label: "Active campaigns", val: campaigns.length || "—", delta: "" },
  ]

  const fmtDate = (v) => v ? new Date(v).toLocaleString() : "—"
  const statusClass = (s) => s?.toLowerCase() || "pending"

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Overview</div>
        <div className="topbar-actions">
          <Link to="/runs" className="btn primary">
            <i className="ti ti-plus" aria-hidden="true" /> New run
          </Link>
        </div>
      </div>
      <div className="page-content">
        <div className="grid4" style={{ marginBottom: 20 }}>
          {METRICS.map(m => (
            <div className="metric" key={m.label}>
              <div className="metric-label">{m.label}</div>
              <div className="metric-val">{m.val}</div>
            </div>
          ))}
        </div>
        <div className="grid2">
          <div className="card">
            <div className="card-head"><h2>Recent runs</h2></div>
            <table>
              <thead>
                <tr><th>ID</th><th>Started</th><th>Status</th><th>Leads</th></tr>
              </thead>
              <tbody>
                {runs.length === 0 && (
                  <tr><td colSpan="4" style={{ textAlign: "center", padding: 20, color: "var(--color-text-secondary)" }}>No runs yet</td></tr>
                )}
                {runs.map(r => (
                  <tr key={r.id}>
                    <td><Link to={`/runs/${r.id}`} className="btn xs">{r.id.slice(0, 8)}</Link></td>
                    <td style={{ color: "var(--color-text-secondary)" }}>{fmtDate(r.started_at)}</td>
                    <td><span className={`badge ${statusClass(r.status)}`}>{r.status}</span></td>
                    <td>{r.total_scraped}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <div className="card-head"><h2>Campaigns</h2></div>
            <table>
              <thead><tr><th>Name</th><th>KB files</th></tr></thead>
              <tbody>
                {campaigns.length === 0 && (
                  <tr><td colSpan="2" style={{ textAlign: "center", padding: 20, color: "var(--color-text-secondary)" }}>No campaigns</td></tr>
                )}
                {campaigns.map(c => (
                  <tr key={c.filename}>
                    <td style={{ fontWeight: 500 }}>{c.name}</td>
                    <td style={{ color: "var(--color-text-secondary)" }}>{c.knowledge_bases?.length || 0} files</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  )
}
