import { useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import {
  downloadFile,
  friendlyMessage,
  openWS,
} from "../../api"
import { useToast } from "../../components/ToastProvider"
import { useCampaigns, useRun, useRunEvents, useRunLeads, useUploadRunEnriched } from "../../queries"
import { humanizeEvent } from "../../utils/humanizeEvent"

const timeOnly = (value) => {
  if (!value) return ""
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value).slice(11, 19) : date.toTimeString().slice(0, 8)
}

const fmtDateTime = (value) => {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

const durationLabel = (run) => {
  const start = run?.started_at ? new Date(run.started_at) : null
  const end = run?.completed_at ? new Date(run.completed_at) : new Date()

  if (!start || Number.isNaN(start.getTime())) return "—"

  const seconds = Math.max(0, Math.round((end - start) / 1000))
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60

  if (minutes <= 0) return `${remainingSeconds}s`
  return `${minutes}m ${remainingSeconds}s`
}

const rawPayload = (event) => {
  if (!event?.payload) return ""
  if (typeof event.payload === "string") return event.payload
  try {
    return JSON.stringify(event.payload)
  } catch {
    return String(event.payload)
  }
}

const campaignKey = (run) => run?.filters?.campaign_key || run?.filters?.campaign || ""

export default function RunDetail() {
  const { filename: encodedFilename, runId } = useParams()
  const id = runId
  const filename = decodeURIComponent(encodedFilename || "")
  const toast = useToast()

  const { data: run = null } = useRun(id)
  const { data: campaigns = [] } = useCampaigns()
  const { data: leads = [] } = useRunLeads(id, { limit: 500 })
  const { data: initialEvents } = useRunEvents(id)
  const uploadRunEnriched = useUploadRunEnriched(id)

  const [events, setEvents] = useState([])
  const [phase, setPhase] = useState("")
  const [downloading, setDownloading] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const [following, setFollowing] = useState(true)

  const logRef = useRef(null)
  const uploading = uploadRunEnriched.isPending

  useEffect(() => {
    setEvents([])
    setPhase("")
    setFollowing(true)
  }, [id])

  useEffect(() => {
    if (initialEvents) {
      setEvents(initialEvents.slice().reverse().slice(-120))
    }
  }, [initialEvents])

  useEffect(() => {
    if (!id) return undefined

    const ws = openWS(id, (event) => {
      setEvents((current) => [...current, event].slice(-120))

      const status = event?.payload?.status
      if (status === "browser_ready") setPhase("browser_ready")
      else if (status === "copying") setPhase("copying")
      else if (event?.event_type === "AGENT_COMPLETED") setPhase("")
    })

    return () => ws?.close()
  }, [id])

  useEffect(() => {
    if (!following || !logRef.current) return
    logRef.current.scrollTop = logRef.current.scrollHeight
  }, [events, following, showRaw])

  const handleLogScroll = (event) => {
    const element = event.currentTarget
    const isNearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 48
    setFollowing(isNearBottom)
  }

  const handleJumpLatest = () => {
    setFollowing(true)
    requestAnimationFrame(() => {
      if (logRef.current) {
        logRef.current.scrollTop = logRef.current.scrollHeight
      }
    })
  }

  const handleDownloadZoominfo = async () => {
    setDownloading(true)
    try {
      await downloadFile(
        `/api/runs/${id}/leads/download-for-zoominfo`,
        `leads_${id.slice(0, 8)}_for_zoominfo.csv`,
      )
      toast({ type: "success", title: "Export ready", detail: "ZoomInfo CSV downloaded." })
    } catch (error) {
      toast({ type: "error", title: "Export failed", detail: friendlyMessage(error) || "Could not export leads." })
    } finally {
      setDownloading(false)
    }
  }

  const handleUploadEnriched = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ""

    if (!file) return

    try {
      const response = await uploadRunEnriched.mutateAsync(file)
      const result = response.data
      toast({
        type: "success",
        title: "Upload complete",
        detail: `Matched ${result.matched || 0}, updated ${result.updated || 0}, unmatched ${result.unmatched || 0}.`,
      })
    } catch (error) {
      toast({ type: "error", title: "Upload failed", detail: friendlyMessage(error) || "Could not upload enriched CSV." })
    }
  }

  const runStats = useMemo(() => {
    const withEmail = leads.filter((lead) => lead.email).length
    const needsEnrichment = leads.filter((lead) => !lead.email).length

    return [
      ["Scraped", run?.total_scraped ?? leads.length ?? 0],
      ["Needs enrichment", needsEnrichment],
      ["With email", withEmail],
      ["Warm", run?.total_warm ?? 0],
      ["Cold", run?.total_cold ?? 0],
    ]
  }, [leads, run])

  if (!run) {
    return (
      <div className="page-content run-loading">
        Loading run…
      </div>
    )
  }

  const isRunning = run.status === "RUNNING"
  const statusClass = String(run.status || "").toLowerCase()
  const campaign = campaignKey(run)
  const campaignFilename = filename || campaign
  const campaignName =
    campaigns.find((item) => item.filename === campaignFilename)?.name ||
    campaignFilename ||
    "Campaign"

  return (
    <>
      <div className="run-topbar">
        <div>
          <div className="breadcrumb">
            <Link to={`/campaigns/${encodeURIComponent(campaignFilename)}/sources`}>
              ‹ {campaignName}
            </Link>
            <span>/ Sources / Run</span>
          </div>
          <h1>{run.label || `Run ${id.slice(0, 8)}`}</h1>
        </div>

        <div className="run-topbar-actions">
          {campaignFilename && (
            <Link className="btn sm" to={`/campaigns/${encodeURIComponent(campaignFilename)}`}>
              <i className="ti ti-speakerphone" aria-hidden="true" />
              Campaign workspace
            </Link>
          )}
          {isRunning && <span className="dot-live" />}
          <span className={`badge ${statusClass}`}>{run.status}</span>
        </div>
      </div>

      <div className="page-content run-detail-page">
        <section className="run-hero card">
          <div>
            <span className="eyebrow">Run detail</span>
            <h2>{run.label || `Run ${id.slice(0, 8)}`}</h2>
            <p>
              Started {fmtDateTime(run.started_at)} · Duration {durationLabel(run)}
            </p>

            {run.filters?.start_url && (
              <a
                className="run-source-link"
                href={run.filters.start_url}
                target="_blank"
                rel="noreferrer"
              >
                <i className="ti ti-external-link" aria-hidden="true" />
                {run.filters.start_url}
              </a>
            )}
          </div>

          <div className="run-hero-status">
            {isRunning && <span className="dot-live" />}
            <span className={`badge ${statusClass}`}>{run.status}</span>
          </div>
        </section>

        {phase === "browser_ready" && isRunning && (
          <div className="banner yellow">
            <i className="ti ti-world" aria-hidden="true" />
            <div>
              <div className="banner-title">Browser is open</div>
              <div className="banner-msg">Solve any CAPTCHA in the Chrome window. Scraping starts automatically.</div>
            </div>
          </div>
        )}

        {phase === "copying" && isRunning && (
          <div className="banner blue">
            <i className="ti ti-copy" aria-hidden="true" />
            <div>
              <div className="banner-title">Copying pages</div>
              <div className="banner-msg">Collecting page content before extraction starts.</div>
            </div>
          </div>
        )}

        {run.status === "FAILED" && run.error && (
          <div className="banner red">
            <i className="ti ti-alert-circle" aria-hidden="true" />
            <div>
              <div className="banner-title">Run failed</div>
              <div className="banner-msg">{run.error}</div>
            </div>
          </div>
        )}

        <div className="run-stat-grid">
          {runStats.map(([label, value]) => (
            <div className="metric-card static" key={label}>
              <strong>{value}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>

        <div className="run-grid">
          <section className="card run-log-card">
            <div className="card-head">
              <div>
                <h2>Live log</h2>
                <p>Human-readable progress from the run event stream.</p>
              </div>

              <div className="topbar-actions">
                <button
                  className="btn sm"
                  onClick={() => setShowRaw((value) => !value)}
                  type="button"
                >
                  {showRaw ? "Pretty" : "Raw"}
                </button>
              </div>
            </div>

            <div className="run-log-body" onScroll={handleLogScroll} ref={logRef}>
              {events.length === 0 && (
                <div className="run-log-empty">
                  Waiting for events…
                </div>
              )}

              {events.map((event, index) => {
                const human = humanizeEvent(event)

                if (showRaw) {
                  return (
                    <div className="run-log-line raw" key={`${event.timestamp}-${index}`}>
                      <time>{timeOnly(event.timestamp)}</time>
                      <strong>{event.agent_name || "System"}</strong>
                      <code>{rawPayload(event)}</code>
                    </div>
                  )
                }

                return (
                  <div className={`run-log-line tone-${human.tone}`} key={`${event.timestamp}-${index}`}>
                    <span className="run-log-icon">{human.icon}</span>
                    <time>{timeOnly(event.timestamp)}</time>
                    <span className="run-log-text">{human.text}</span>
                  </div>
                )
              })}
            </div>

            {!following && (
              <button className="jump-latest" onClick={handleJumpLatest} type="button">
                Jump to latest ↓
              </button>
            )}
          </section>

          <section className="card run-enrichment-card">
            <div className="card-head">
              <div>
                <h2>ZoomInfo enrichment</h2>
                <p>Export scraped leads, enrich externally, then upload the enriched CSV.</p>
              </div>
            </div>

            <div className="run-enrichment-actions">
              <button
                className="btn sm"
                onClick={handleDownloadZoominfo}
                disabled={downloading || leads.length === 0}
                type="button"
              >
                <i className="ti ti-download" aria-hidden="true" />
                {downloading ? "Exporting..." : "Export for ZoomInfo"}
              </button>

              <label className={`btn sm ${uploading ? "disabled" : ""}`}>
                <i className="ti ti-upload" aria-hidden="true" />
                {uploading ? "Uploading..." : "Upload enriched"}
                <input type="file" accept=".csv" onChange={handleUploadEnriched} disabled={uploading} hidden />
              </label>
            </div>
          </section>
        </div>

        <section className="card run-leads-card">
          <div className="card-head">
            <div>
              <h2>Leads from this run</h2>
              <p>{leads.length} leads loaded from this run.</p>
            </div>
          </div>

          <div className="table-wrap">
            <table className="run-leads-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Email</th>
                  <th>Phone</th>
                  <th>Segment</th>
                  <th>Status</th>
                  <th>LinkedIn</th>
                </tr>
              </thead>
              <tbody>
                {leads.length === 0 && (
                  <tr>
                    <td colSpan="8" className="empty-cell">
                      No leads yet.
                    </td>
                  </tr>
                )}

                {leads.map((lead) => (
                  <tr key={lead.id}>
                    <td>
                      <strong>{lead.full_name || "—"}</strong>
                    </td>
                    <td className="muted">{lead.title || "—"}</td>
                    <td>{lead.company || "—"}</td>
                    <td>
                      {lead.email ? (
                        <span className="email-text">{lead.email}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>{lead.phone || "—"}</td>
                    <td>
                      <span className={`badge ${lead.segment?.toLowerCase?.() || "pending"}`}>
                        {lead.segment || "—"}
                      </span>
                    </td>
                    <td>{lead.status || "—"}</td>
                    <td>
                      {lead.linkedin_url ? (
                        <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="btn xs icon" title="LinkedIn">
                          <i className="ti ti-brand-linkedin" aria-hidden="true" />
                        </a>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  )
}