import { useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import {
  getCampaigns,
  getEmailPreview,
  getRun,
  getRunEvents,
  getRunLeads,
  openWS,
  personaliseRun,
  sendEmails,
  sendSingleEmail,
  updateEmailContent,
} from "../api"

const timeOnly = (v) => {
  if (!v) return ""
  const d = new Date(v)
  return isNaN(d) ? v.slice(11, 19) : d.toTimeString().slice(0, 8)
}

const logClass = (ev) => {
  const s = ev?.payload?.status
  const t = ev?.event_type
  if (s === "browser_ready" || s === "waiting_for_login") return "log-row yellow"
  if (s === "copying") return "log-row blue"
  if (t === "LEAD_SCRAPED" && !s) return "log-row green"
  if (t === "AGENT_FAILED" || t === "PIPELINE_FAILED") return "log-row red"
  return "log-row"
}

const logSummary = (ev) => {
  const p = ev?.payload || {}
  if (p.message) return p.message
  if (p.name) return `${p.name}${p.company ? " @ " + p.company : ""}`
  if (p.status) return p.status
  const t = JSON.stringify(p)
  return t.length > 80 ? `${t.slice(0, 77)}...` : t
}

export default function RunDetail() {
  const { id } = useParams()
  const [run, setRun] = useState(null)
  const [leads, setLeads] = useState([])
  const [events, setEvents] = useState([])
  const [campaigns, setCampaigns] = useState([])
  const [selectedCampaign, setSelectedCampaign] = useState("")
  const [preview, setPreview] = useState([])
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [composeLead, setComposeLead] = useState(null)
  const [composeData, setComposeData] = useState({
    recipient_email: "",
    email_subject: "",
    email_body: "",
    linkedin_message: "",
  })
  const [composeSaving, setComposeSaving] = useState(false)
  const [composeSending, setComposeSending] = useState(false)
  const [composeResult, setComposeResult] = useState(null)
  const [activeTab, setActiveTab] = useState("email")
  const [phase, setPhase] = useState("")
  const [personalising, setPersonalising] = useState(false)
  const [sending, setSending] = useState(false)
  const [personaliseResult, setPersonaliseResult] = useState(null)
  const [sendResult, setSendResult] = useState(null)
  const bottomRef = useRef(null)

  const loadPreview = () => {
    if (!id) return
    setLoadingPreview(true)
    getEmailPreview(id)
      .then(r => setPreview(r.data))
      .catch(() => {})
      .finally(() => setLoadingPreview(false))
  }

  const openCompose = (p) => {
    setComposeLead(p)
    setComposeData({
      recipient_email: p.email || "",
      email_subject: p.email_subject || "",
      email_body: p.email_body || "",
      linkedin_message: p.linkedin_message || "",
    })
    setComposeResult(null)
    setActiveTab("email")
  }

  const handleSaveEdits = async () => {
    if (!composeLead) return
    setComposeSaving(true)
    try {
      await updateEmailContent(composeLead.lead_id, composeData)
      setPreview(prev => prev.map(p =>
        p.lead_id === composeLead.lead_id
          ? { ...p, ...composeData, email: composeData.recipient_email }
          : p
      ))
    } catch {
      setComposeResult({ error: "Save failed" })
    } finally {
      setComposeSaving(false)
    }
  }

  const handleSendSingle = async () => {
    if (!composeLead) return
    setComposeSending(true)
    setComposeResult(null)
    try {
      await updateEmailContent(composeLead.lead_id, composeData)
      const res = await sendSingleEmail(composeLead.lead_id)
      setComposeResult({ success: true, data: res.data })
      loadPreview()
      setTimeout(() => {
        setComposeLead(null)
        setComposeResult(null)
      }, 2000)
    } catch (err) {
      setComposeResult({
        error: err.response?.data?.detail || "Send failed",
      })
    } finally {
      setComposeSending(false)
    }
  }

  useEffect(() => {
    let mounted = true
    const loadRun = () => getRun(id)
      .then(r => { if (mounted) setRun(r.data) })
      .catch(() => {})
    loadRun()
    const t = setInterval(loadRun, 3000)
    return () => { mounted = false; clearInterval(t) }
  }, [id])

  useEffect(() => {
    getCampaigns().then(r => {
      setCampaigns(r.data)
      if (r.data.length > 0) setSelectedCampaign(r.data[0].filename)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!id) return
    getRunEvents(id).then(r => setEvents(r.data.slice().reverse().slice(-80))).catch(() => {})
    getRunLeads(id, { limit: 50 }).then(r => setLeads(r.data)).catch(() => {})
    const ws = openWS(id, (ev) => {
      setEvents(cur => [...cur, ev].slice(-80))
      const s = ev?.payload?.status
      if (s === "browser_ready") setPhase("browser_ready")
      else if (s === "copying") setPhase("copying")
      else if (ev?.event_type === "AGENT_COMPLETED") setPhase("")
    })
    return () => ws?.close()
  }, [id])

  useEffect(() => {
    if (run?.status !== "COMPLETED" || !id) return
    let mounted = true
    Promise.resolve()
      .then(() => {
        if (mounted) setLoadingPreview(true)
        return getEmailPreview(id)
      })
      .then(r => {
        if (mounted) setPreview(r.data)
      })
      .catch(() => {})
      .finally(() => {
        if (mounted) setLoadingPreview(false)
      })
    return () => { mounted = false }
  }, [id, run?.status])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [events])

  const handlePersonalise = async () => {
    if (!selectedCampaign) return
    setPersonalising(true)
    setPersonaliseResult(null)
    try {
      const res = await personaliseRun(id, selectedCampaign)
      setPersonaliseResult(res.data)
      getRunLeads(id, { limit: 50 }).then(r => setLeads(r.data)).catch(() => {})
      loadPreview()
    } catch (err) {
      setPersonaliseResult({ error: err.response?.data?.detail || "Failed" })
    } finally {
      setPersonalising(false)
    }
  }

  const handleSend = async () => {
    setSending(true)
    setSendResult(null)
    try {
      const res = await sendEmails(id)
      setSendResult(res.data)
      loadPreview()
    } catch (err) {
      setSendResult({ error: err.response?.data?.detail || "Failed" })
    } finally {
      setSending(false)
    }
  }

  if (!run) {
    return (
      <div className="page-content" style={{ textAlign: "center", paddingTop: 60, color: "var(--color-text-secondary)" }}>
        Loading...
      </div>
    )
  }

  const isRunning = run.status === "RUNNING"
  const statusClass = run.status.toLowerCase()

  return (
    <>
      <div className="topbar">
        <Link to="/runs" style={{ color: "var(--color-text-secondary)", textDecoration: "none", fontSize: 13, display: "flex", alignItems: "center", gap: 4 }}>
          <i className="ti ti-arrow-left" aria-hidden="true" /> Runs
        </Link>
        <div className="topbar-title">Run {id.slice(0, 8)}</div>
        <div className="topbar-actions">
          {isRunning && <span className="dot-live" />}
          <span className={`badge ${statusClass}`}>{run.status}</span>
        </div>
      </div>

      <div className="page-content">
        {run.filters?.start_url && (
          <a href={run.filters.start_url} target="_blank" rel="noreferrer"
            style={{ fontSize: 12, color: "var(--blue)", display: "block", marginBottom: 16, wordBreak: "break-all" }}>
            <i className="ti ti-external-link" aria-hidden="true" /> {run.filters.start_url}
          </a>
        )}

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
              <div className="banner-title">Phase 1 - Copying pages</div>
              <div className="banner-msg">Collecting page content. OpenAI extraction runs after all pages are copied.</div>
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

        <div className="grid4" style={{ marginBottom: 16 }}>
          {[["total_scraped", "Scraped"], ["total_enriched", "Enriched"], ["total_warm", "Warm"], ["total_cold", "Cold"]].map(([k, l]) => (
            <div className="metric" key={k}>
              <div className="metric-label">{l}</div>
              <div className="metric-val">{run[k] ?? 0}</div>
            </div>
          ))}
        </div>

        <div className="grid2" style={{ marginBottom: 16 }}>
          <div className="card">
            <div className="card-head"><h2>Live log</h2></div>
            <div className="log-list">
              {events.length === 0 && <p style={{ padding: 20, textAlign: "center", color: "var(--color-text-secondary)", fontFamily: "sans-serif" }}>Waiting for events...</p>}
              {events.map((ev, i) => (
                <div className={logClass(ev)} key={`${ev.timestamp}-${i}`}>
                  <time>{timeOnly(ev.timestamp)}</time>
                  <strong>{ev.agent_name}</strong>
                  <small style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{logSummary(ev)}</small>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </div>
          <div className="card">
            <div className="card-head"><h2>Sample leads</h2></div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Company</th><th>Email</th></tr></thead>
                <tbody>
                  {leads.length === 0 && <tr><td colSpan="3" style={{ textAlign: "center", padding: 16, color: "var(--color-text-secondary)" }}>No leads yet</td></tr>}
                  {leads.slice(0, 8).map(l => (
                    <tr key={l.id}>
                      <td style={{ fontWeight: 500 }}>{l.full_name || "-"}</td>
                      <td style={{ color: "var(--color-text-secondary)" }}>{l.company || "-"}</td>
                      <td style={{ color: l.email ? "var(--blue)" : "var(--color-text-tertiary)", fontSize: 11 }}>{l.email || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {run.status === "COMPLETED" && (
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head"><h2>Personalise messages</h2></div>
            <div className="card-body">
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <div className="form-group" style={{ margin: 0, flex: 1 }}>
                  <div className="form-label">Campaign</div>
                  <select className="form-input" value={selectedCampaign}
                    onChange={e => setSelectedCampaign(e.target.value)}>
                    {campaigns.map(c => <option key={c.filename} value={c.filename}>{c.name}</option>)}
                  </select>
                </div>
                <button className="btn primary" onClick={handlePersonalise}
                  disabled={personalising || !selectedCampaign}>
                  <i className="ti ti-sparkles" aria-hidden="true" />
                  {personalising ? `Generating for ${run.total_scraped} leads...` : "Generate messages"}
                </button>
              </div>
              {personaliseResult && (
                <div className={`banner ${personaliseResult.error ? "red" : "green"}`} style={{ marginTop: 12, marginBottom: 0 }}>
                  <i className={`ti ti-${personaliseResult.error ? "alert-circle" : "check"}`} aria-hidden="true" />
                  <div>
                    <div className="banner-msg">
                      {personaliseResult.error || `${personaliseResult.success} messages generated, ${personaliseResult.failed} failed`}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {run.status === "COMPLETED" && (
          <div className="card">
            <div className="card-head">
              <h2>Email sequence</h2>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <button className="btn sm" onClick={loadPreview} disabled={loadingPreview}>
                  <i className="ti ti-refresh" aria-hidden="true" />
                  {loadingPreview ? "Loading..." : `Preview (${preview.length} due)`}
                </button>
                <button className="btn primary sm" onClick={handleSend} disabled={sending || preview.length === 0}>
                  <i className="ti ti-send" aria-hidden="true" />
                  {sending ? "Sending..." : `Send ${preview.length} emails`}
                </button>
              </div>
            </div>

            {sendResult && (
              <div className={`banner ${sendResult.error ? "red" : "green"}`} style={{ margin: "12px 18px 0" }}>
                <i className={`ti ti-${sendResult.error ? "alert-circle" : "check"}`} aria-hidden="true" />
                <div className="banner-msg">
                  {sendResult.error || `${sendResult.sent} emails sent`}
                </div>
              </div>
            )}

            {preview.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Email</th>
                      <th>Company</th>
                      <th>Day</th>
                      <th>Subject</th>
                      <th>Preview</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map(p => (
                      <tr key={p.lead_id}>
                        <td style={{ fontWeight: 500, whiteSpace: "nowrap" }}>{p.full_name}</td>
                        <td style={{ fontFamily: "monospace", fontSize: 11, color: "var(--blue)" }}>
                          {p.email}
                        </td>
                        <td style={{ color: "var(--color-text-secondary)" }}>{p.company || "-"}</td>
                        <td><span className={`badge day${p.day_due}`}>Day {p.day_due}</span></td>
                        <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {p.email_subject}
                        </td>
                        <td>
                          <button className="btn xs" onClick={() => openCompose(p)}>
                            <i className="ti ti-eye" aria-hidden="true" /> View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {preview.length === 0 && !loadingPreview && (
              <p style={{ padding: 20, textAlign: "center", color: "var(--color-text-secondary)", fontSize: 13 }}>
                No emails due today. Run personalisation first, or check back in 3 days for follow-ups.
              </p>
            )}
          </div>
        )}

        {composeLead && (
          <div className="modal-backdrop"
            onClick={e => e.target === e.currentTarget && setComposeLead(null)}>
            <div className="modal" style={{ width: 680, maxHeight: "90vh" }}>
              <div className="modal-head">
                <div>
                  <h2 style={{ marginBottom: 2 }}>
                    Compose - {composeLead.full_name}
                  </h2>
                  <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
                    {composeLead.company || ""}
                    {composeLead.title ? ` - ${composeLead.title}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className={`badge day${composeLead.day_due}`}>
                    Day {composeLead.day_due}
                  </span>
                  <button className="btn icon" onClick={() => setComposeLead(null)}>
                    <i className="ti ti-x" aria-hidden="true" />
                  </button>
                </div>
              </div>

              <div className="modal-body">
                <div style={{
                  display: "flex",
                  borderBottom: "0.5px solid var(--color-border-tertiary)",
                  marginBottom: 16,
                  gap: 0,
                }}>
                  {[["email", "Email"], ["linkedin", "LinkedIn message"]].map(([tab, label]) => (
                    <button key={tab}
                      onClick={() => setActiveTab(tab)}
                      style={{
                        padding: "8px 16px",
                        border: "none",
                        background: "none",
                        fontSize: 13,
                        fontWeight: activeTab === tab ? 500 : 400,
                        color: activeTab === tab
                          ? "var(--purple)"
                          : "var(--color-text-secondary)",
                        borderBottom: activeTab === tab
                          ? "2px solid var(--purple)"
                          : "2px solid transparent",
                        cursor: "pointer",
                        marginBottom: -1,
                      }}>
                      {label}
                    </button>
                  ))}
                </div>

                {activeTab === "email" && (
                  <>
                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      padding: "8px 12px",
                      borderBottom: "0.5px solid var(--color-border-tertiary)",
                      fontSize: 13,
                      gap: 12,
                    }}>
                      <span style={{
                        width: 60,
                        color: "var(--color-text-secondary)",
                        fontWeight: 500,
                        flexShrink: 0,
                      }}>From</span>
                      <span style={{ color: "var(--color-text-primary)" }}>
                        {import.meta.env.VITE_SENDER_EMAIL
                          || "sabih.aamir@royalcyber.com"}
                      </span>
                      <span style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        color: "var(--color-text-tertiary)",
                        background: "var(--color-background-secondary)",
                        padding: "2px 8px",
                        borderRadius: 10,
                      }}>via Microsoft Graph</span>
                    </div>

                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      borderBottom: "0.5px solid var(--color-border-tertiary)",
                      gap: 12,
                      padding: "0 12px",
                    }}>
                      <span style={{
                        width: 60,
                        color: "var(--color-text-secondary)",
                        fontWeight: 500,
                        flexShrink: 0,
                        fontSize: 13,
                      }}>To</span>
                      <input
                        style={{
                          flex: 1,
                          border: "none",
                          outline: "none",
                          fontSize: 13,
                          padding: "10px 0",
                          background: "transparent",
                          color: "var(--color-text-primary)",
                        }}
                        placeholder="recipient@company.com"
                        value={composeData.recipient_email}
                        onChange={e => setComposeData(d => ({
                          ...d, recipient_email: e.target.value
                        }))}
                      />
                    </div>

                    <div style={{
                      display: "flex",
                      alignItems: "center",
                      borderBottom: "0.5px solid var(--color-border-tertiary)",
                      gap: 12,
                      padding: "0 12px",
                    }}>
                      <span style={{
                        width: 60,
                        color: "var(--color-text-secondary)",
                        fontWeight: 500,
                        flexShrink: 0,
                        fontSize: 13,
                      }}>Subject</span>
                      <input
                        style={{
                          flex: 1,
                          border: "none",
                          outline: "none",
                          fontSize: 13,
                          padding: "10px 0",
                          background: "transparent",
                          color: "var(--color-text-primary)",
                          fontWeight: 500,
                        }}
                        placeholder="Email subject line"
                        value={composeData.email_subject}
                        onChange={e => setComposeData(d => ({
                          ...d, email_subject: e.target.value
                        }))}
                      />
                    </div>

                    <textarea
                      style={{
                        width: "100%",
                        minHeight: 220,
                        border: "none",
                        outline: "none",
                        resize: "vertical",
                        fontSize: 13,
                        lineHeight: 1.7,
                        padding: "14px 12px",
                        fontFamily: "inherit",
                        background: "transparent",
                        color: "var(--color-text-primary)",
                      }}
                      placeholder="Write your email here..."
                      value={composeData.email_body}
                      onChange={e => setComposeData(d => ({
                        ...d, email_body: e.target.value
                      }))}
                    />
                  </>
                )}

                {activeTab === "linkedin" && (
                  <div style={{ padding: "0 4px" }}>
                    <div className="form-label" style={{ marginBottom: 8 }}>
                      LinkedIn message
                      <span style={{
                        marginLeft: 8,
                        fontSize: 11,
                        color: composeData.linkedin_message.length > 280
                          ? "var(--red)" : "var(--color-text-tertiary)"
                      }}>
                        {composeData.linkedin_message.length}/280 chars
                      </span>
                    </div>
                    <textarea
                      style={{
                        width: "100%",
                        minHeight: 120,
                        padding: "12px",
                        border: "0.5px solid var(--color-border-secondary)",
                        borderRadius: "var(--radius)",
                        fontSize: 13,
                        lineHeight: 1.6,
                        fontFamily: "inherit",
                        resize: "vertical",
                        background: "var(--color-background-primary)",
                        color: "var(--color-text-primary)",
                      }}
                      placeholder="LinkedIn connection message..."
                      value={composeData.linkedin_message}
                      onChange={e => setComposeData(d => ({
                        ...d, linkedin_message: e.target.value
                      }))}
                    />
                  </div>
                )}

                {composeResult && (
                  <div className={`banner ${composeResult.error ? "red" : "green"}`}
                    style={{ margin: "12px 0 0" }}>
                    <i className={`ti ti-${composeResult.error
                      ? "alert-circle" : "check"}`} aria-hidden="true" />
                    <div className="banner-msg">
                      {composeResult.error
                        || `Email sent successfully to ${composeData.recipient_email}`}
                    </div>
                  </div>
                )}

                <div style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginTop: 16,
                  paddingTop: 14,
                  borderTop: "0.5px solid var(--color-border-tertiary)",
                }}>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      className="btn primary"
                      onClick={handleSendSingle}
                      disabled={
                        composeSending
                        || !composeData.recipient_email
                        || !composeData.email_subject
                        || !composeData.email_body
                      }>
                      <i className="ti ti-send" aria-hidden="true" />
                      {composeSending ? "Sending..." : "Send email"}
                    </button>
                    <button
                      className="btn"
                      onClick={handleSaveEdits}
                      disabled={composeSaving}>
                      <i className="ti ti-device-floppy" aria-hidden="true" />
                      {composeSaving ? "Saving..." : "Save edits"}
                    </button>
                  </div>
                  <button className="btn" onClick={() => setComposeLead(null)}>
                    Discard
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
