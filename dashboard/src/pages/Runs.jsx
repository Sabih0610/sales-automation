import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { getRuns, startRun, getCampaigns } from "../api"

const PARSE_LIST = (v) => v.split(",").map(s => s.trim()).filter(Boolean)

export default function Runs() {
  const navigate = useNavigate()
  const [runs, setRuns] = useState([])
  const [campaigns, setCampaigns] = useState([])
  const [form, setForm] = useState({
    url: "", max_leads: 100, campaign: "",
    titles: "CTO, CIO, CXO, Head of Data, VP Engineering",
    keywords: "", geos: "", showAdvanced: false
  })
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    getRuns().then(r => setRuns(r.data)).catch(() => {})
    getCampaigns().then(r => {
      setCampaigns(r.data)
      if (r.data.length > 0) setForm(f => ({ ...f, campaign: r.data[0].filename }))
    }).catch(() => {})
    const t = setInterval(() => {
      getRuns().then(r => setRuns(r.data)).catch(() => {})
    }, 5000)
    return () => clearInterval(t)
  }, [])

  const handleStart = async (e) => {
    e.preventDefault()
    if (!form.url.trim()) { setError("URL is required"); return }
    setError(""); setStarting(true)
    try {
      const res = await startRun({
        start_url: form.url.trim(),
        max_leads: Number(form.max_leads) || 100,
        titles: PARSE_LIST(form.titles),
        keywords: form.keywords,
        geos: PARSE_LIST(form.geos),
        industries: [], company_sizes: [],
      })
      navigate(`/runs/${res.data.id}`)
    } catch (err) {
      setError(err.response?.status === 409
        ? "A run is already active. Wait for it to finish."
        : err.response?.data?.detail || "Failed to start run")
    } finally { setStarting(false) }
  }

  const fmtDate = (v) => v ? new Date(v).toLocaleString() : "—"
  const statusClass = (s) => s?.toLowerCase() || "pending"

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Runs</div>
      </div>
      <div className="page-content">
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head"><h2>New scraping run</h2></div>
          <div className="card-body">
            <form onSubmit={handleStart}>
              {error && <div className="form-error" style={{ marginBottom: 14 }}>{error}</div>}
              <div className="form-group">
                <div className="form-label">Source URL *</div>
                <input className="form-input" type="url" placeholder="https://www.yellowpages.com.au/search?search_terms=..."
                  value={form.url} onChange={e => setForm(f => ({ ...f, url: e.target.value }))} autoFocus />
                <div className="form-hint">Paste any search results or directory page. The scraper handles pagination automatically.</div>
              </div>
              <div className="grid2">
                <div className="form-group">
                  <div className="form-label">Campaign</div>
                  <select className="form-input" value={form.campaign}
                    onChange={e => setForm(f => ({ ...f, campaign: e.target.value }))}>
                    <option value="">No campaign</option>
                    {campaigns.map(c => <option key={c.filename} value={c.filename}>{c.name}</option>)}
                  </select>
                </div>
                <div className="form-group">
                  <div className="form-label">Max leads</div>
                  <input className="form-input" type="number" min="1" max="10000"
                    value={form.max_leads} onChange={e => setForm(f => ({ ...f, max_leads: e.target.value }))} />
                </div>
              </div>
              <button type="button" style={{ background: "none", border: "none", color: "var(--purple)", fontSize: 12, cursor: "pointer", marginBottom: 12 }}
                onClick={() => setForm(f => ({ ...f, showAdvanced: !f.showAdvanced }))}>
                {form.showAdvanced ? "▼" : "▶"} Advanced settings
              </button>
              {form.showAdvanced && (
                <div className="grid2">
                  <div className="form-group">
                    <div className="form-label">Target titles</div>
                    <input className="form-input" placeholder="CTO, CIO, Head of Data"
                      value={form.titles} onChange={e => setForm(f => ({ ...f, titles: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <div className="form-label">Locations</div>
                    <input className="form-input" placeholder="United States, Australia"
                      value={form.geos} onChange={e => setForm(f => ({ ...f, geos: e.target.value }))} />
                  </div>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button type="submit" className="btn primary" disabled={starting}>
                  <i className="ti ti-player-play" aria-hidden="true" />
                  {starting ? "Starting..." : "Start run"}
                </button>
              </div>
            </form>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Run history</h2></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>ID</th><th>Started</th><th>Status</th><th>Scraped</th><th>Warm</th><th>Cold</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {runs.length === 0 && (
                  <tr><td colSpan="7" style={{ textAlign: "center", padding: 20, color: "var(--color-text-secondary)" }}>No runs yet</td></tr>
                )}
                {runs.map(r => (
                  <tr key={r.id}>
                    <td style={{ fontFamily: "monospace", color: "var(--color-text-secondary)" }}>{r.id.slice(0, 8)}</td>
                    <td style={{ color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{fmtDate(r.started_at)}</td>
                    <td>
                      {r.status === "RUNNING" && <span className="dot-live" />}
                      <span className={`badge ${statusClass(r.status)}`}>{r.status}</span>
                    </td>
                    <td>{r.total_scraped}</td>
                    <td>{r.total_warm}</td>
                    <td>{r.total_cold}</td>
                    <td><Link to={`/runs/${r.id}`} className="btn xs">View</Link></td>
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
