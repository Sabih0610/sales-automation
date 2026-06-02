import { useCallback, useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getCampaigns, getRun, personaliseRun } from "../api"
import LeadTable from "./LeadTable"
import LiveLog from "./LiveLog"
import StatsCards from "./StatsCards"

export default function RunDetail() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [error, setError] = useState("")
  const [phase, setPhase] = useState("")  // "browser_ready"|"copying"|"extracting"|""
  const [campaigns, setCampaigns] = useState([])
  const [selectedCampaign, setSelectedCampaign] = useState("")
  const [personalising, setPersonalising] = useState(false)
  const [personaliseResult, setPersonaliseResult] = useState(null)

  useEffect(() => {
    let mounted = true
    let timer

    const load = async () => {
      try {
        const res = await getRun(id)
        if (mounted) setRun(res.data)
      } catch {
        if (mounted) setError("Run not found.")
      }
    }

    load()
    timer = window.setInterval(load, 3000)
    return () => { mounted = false; clearInterval(timer) }
  }, [id])

  useEffect(() => {
    getCampaigns().then(r => {
      setCampaigns(r.data)
      if (r.data.length > 0) setSelectedCampaign(r.data[0].filename)
    }).catch(() => {})
  }, [])

  // Detect phase from latest events
  const handleEvent = useCallback((event) => {
    const s = event?.payload?.status
    if (s === "browser_ready" || s === "waiting_for_login") setPhase("browser_ready")
    else if (s === "copying") setPhase("copying")
    else if (event?.agent_name === "ScraperAgent" &&
             event?.event_type === "AGENT_COMPLETED") setPhase("extracting")
    else if (event?.event_type === "AGENT_COMPLETED") setPhase("")
  }, [])

  const handlePersonalise = async () => {
    if (!selectedCampaign) return
    setPersonalising(true)
    setPersonaliseResult(null)
    try {
      const res = await personaliseRun(run.id, selectedCampaign)
      setPersonaliseResult(res.data)
    } catch (err) {
      setPersonaliseResult({ error: err.response?.data?.detail || "Failed" })
    } finally {
      setPersonalising(false)
    }
  }

  if (error) return (
    <section className="panel">
      <p className="form-error">{error}</p>
      <Link to="/" className="button secondary">Back</Link>
    </section>
  )

  if (!run) return <p className="loading">Loading...</p>

  const isRunning = run.status === "RUNNING"
  const scrapeUrl = run.filters?.start_url

  return (
    <div className="run-detail">
      <div className="page-title">
        <div>
          <Link to="/" className="back-link">← Runs</Link>
          <h1>Run {run.id.slice(0, 8)}</h1>
          {scrapeUrl && (
            <a className="run-url" href={scrapeUrl} target="_blank" rel="noreferrer">
              {scrapeUrl.length > 60 ? scrapeUrl.slice(0, 60) + "..." : scrapeUrl}
            </a>
          )}
        </div>
        <span className={`status-badge ${run.status.toLowerCase()}`}>
          {isRunning && <span className="pulse-dot" />}
          {run.status}
        </span>
      </div>

      {phase === "browser_ready" && isRunning && (
        <div className="banner banner-yellow">
          <span>🌐</span>
          <div>
            <strong>Browser is open</strong>
            <span>
              Solve any CAPTCHA that appears in the Chrome window.
              Scraping starts automatically once the page loads.
            </span>
          </div>
        </div>
      )}

      {phase === "copying" && isRunning && (
        <div className="banner banner-blue">
          <span>📋</span>
          <div>
            <strong>Phase 1 — Copying pages</strong>
            <span>
              Browser is collecting page content.
              OpenAI extraction runs after all pages are copied.
            </span>
          </div>
        </div>
      )}

      {phase === "extracting" && isRunning && (
        <div className="banner banner-purple">
          <span>🤖</span>
          <div>
            <strong>Phase 2 — Extracting leads</strong>
            <span>OpenAI is processing the collected pages in parallel.</span>
          </div>
        </div>
      )}

      {run.status === "FAILED" && run.error && (
        <div className="banner banner-red">
          <span>⚠️</span>
          <div>
            <strong>Run failed</strong>
            <span>{run.error}</span>
          </div>
        </div>
      )}

      <div className="detail-grid">
        <section className="panel stats-panel">
          <div className="panel-head"><h2>Progress</h2></div>
          <StatsCards run={run} />
        </section>
        <LiveLog runId={run.id} onEvent={handleEvent} />
      </div>

      {run.status === "COMPLETED" && (
        <section className="panel personalise-panel">
          <div className="panel-head">
            <h2>Personalise Messages</h2>
          </div>
          <div className="personalise-controls">
            <label>
              Select Campaign
              <select
                value={selectedCampaign}
                onChange={e => setSelectedCampaign(e.target.value)}
              >
                {campaigns.map(c => (
                  <option key={c.filename} value={c.filename}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="button primary"
              onClick={handlePersonalise}
              disabled={personalising || !selectedCampaign}
            >
              {personalising
                ? `Personalising ${run.total_scraped} leads...`
                : "Generate Personalised Messages"}
            </button>
          </div>
          {personaliseResult && !personaliseResult.error && (
            <div className="personalise-result">
              Done - {personaliseResult.success} messages generated,
              {personaliseResult.failed} failed.
              Refresh the lead table to see messages.
            </div>
          )}
          {personaliseResult?.error && (
            <p className="form-error">{personaliseResult.error}</p>
          )}
        </section>
      )}

      <LeadTable runId={run.id} />
    </div>
  )
}
