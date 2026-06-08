import { useEffect, useState } from "react"
import { getCampaigns, sendEmailsAll, getSequenceStats } from "../api"

export default function Sequences() {
  const [campaigns, setCampaigns] = useState([])
  const [selectedCampaign, setSelectedCampaign] = useState("")
  const [stats, setStats] = useState(null)
  const [sending, setSending] = useState(false)
  const [sendResult, setSendResult] = useState(null)

  useEffect(() => {
    getCampaigns().then(r => {
      setCampaigns(r.data)
      if (r.data.length > 0) setSelectedCampaign(r.data[0].filename)
    }).catch(() => {})
    getSequenceStats().then(r => setStats(r.data)).catch(() => {})
  }, [])

  const handleSend = async () => {
    if (!selectedCampaign) return
    setSending(true); setSendResult(null)
    try {
      const res = await sendEmailsAll(selectedCampaign)
      setSendResult(res.data)
      getSequenceStats().then(r => setStats(r.data)).catch(() => {})
    } catch (err) {
      setSendResult({ error: err.response?.data?.detail || "Send failed" })
    } finally { setSending(false) }
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Email sequences</div>
        <div className="topbar-actions">
          <select className="form-input" style={{ width: "auto" }} value={selectedCampaign}
            onChange={e => setSelectedCampaign(e.target.value)}>
            <option value="">All campaigns</option>
            {campaigns.map(c => <option key={c.filename} value={c.filename}>{c.name}</option>)}
          </select>
          <button className="btn primary" onClick={handleSend} disabled={sending || !selectedCampaign}>
            <i className="ti ti-send" aria-hidden="true" />
            {sending ? "Sending..." : "Send today's batch"}
          </button>
        </div>
      </div>
      <div className="page-content">
        {sendResult && (
          <div className={`banner ${sendResult.error ? "red" : "green"}`}>
            <i className={`ti ti-${sendResult.error ? "alert-circle" : "check"}`} aria-hidden="true" />
            <div>
              <div className="banner-title">{sendResult.error ? "Send failed" : "Emails sent"}</div>
              <div className="banner-msg">
                {sendResult.error || `${sendResult.sent} emails sent out of ${sendResult.total_leads} leads`}
              </div>
            </div>
          </div>
        )}
        {stats && (
          <div className="grid4" style={{ marginBottom: 20 }}>
            <div className="metric"><div className="metric-label">Due today</div><div className="metric-val">{stats.due_today ?? "—"}</div></div>
            <div className="metric"><div className="metric-label">In sequence</div><div className="metric-val">{stats.in_sequence ?? "—"}</div></div>
            <div className="metric"><div className="metric-label">Replied</div><div className="metric-val">{stats.replied ?? "—"}</div></div>
            <div className="metric"><div className="metric-label">Complete</div><div className="metric-val">{stats.complete ?? "—"}</div></div>
          </div>
        )}
        <div className="card">
          <div className="card-head"><h2>Sequence guide</h2></div>
          <div className="card-body">
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", lineHeight: 1.7 }}>
              Click <strong>Send today's batch</strong> once per day. The system automatically determines
              which leads receive Day 1, Day 3, or Day 7 based on when previous emails were sent.
              Leads that have replied or completed the sequence are skipped automatically.
            </p>
            <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
              <div style={{ flex: 1, padding: "12px 14px", background: "var(--color-background-secondary)", borderRadius: "var(--radius)" }}>
                <div className="form-label" style={{ marginBottom: 4 }}>Day 1</div>
                <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Personalised introduction — sent to new leads</div>
              </div>
              <div style={{ flex: 1, padding: "12px 14px", background: "var(--color-background-secondary)", borderRadius: "var(--radius)" }}>
                <div className="form-label" style={{ marginBottom: 4 }}>Day 3</div>
                <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Follow-up with industry use case — sent 3 days after Day 1</div>
              </div>
              <div style={{ flex: 1, padding: "12px 14px", background: "var(--color-background-secondary)", borderRadius: "var(--radius)" }}>
                <div className="form-label" style={{ marginBottom: 4 }}>Day 7</div>
                <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>Final touch with booking link — sent 4 days after Day 3</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
