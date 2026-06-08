import { useEffect, useState, useCallback } from "react"
import { getRuns, getRunLeads, exportRun, downloadForZoominfo, uploadEnrichedCsv } from "../api"

const LIMIT = 50
const SEG_FILTERS = [["", "All"], ["warm", "Warm"], ["cold", "Cold"], ["no_email", "No email"]]

export default function Leads() {
  const [runs, setRuns] = useState([])
  const [selectedRun, setSelectedRun] = useState("")
  const [leads, setLeads] = useState([])
  const [segment, setSegment] = useState("")
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    getRuns().then(r => {
      setRuns(r.data)
      if (r.data.length > 0) setSelectedRun(r.data[0].id)
    }).catch(() => {})
  }, [])

  const loadLeads = useCallback(() => {
    if (!selectedRun) return
    setLoading(true)
    getRunLeads(selectedRun, { segment: segment || undefined, limit: LIMIT, offset })
      .then(r => setLeads(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [selectedRun, segment, offset])

  useEffect(() => {
    if (!selectedRun) return
    let mounted = true
    Promise.resolve()
      .then(() => {
        if (mounted) setLoading(true)
        return getRunLeads(selectedRun, { segment: segment || undefined, limit: LIMIT, offset })
      })
      .then(r => {
        if (mounted) setLeads(r.data)
      })
      .catch(() => {})
      .finally(() => {
        if (mounted) setLoading(false)
      })
    return () => { mounted = false }
  }, [selectedRun, segment, offset])

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file || !selectedRun) return
    setUploading(true); setUploadResult(null)
    try {
      const res = await uploadEnrichedCsv(selectedRun, file)
      setUploadResult(res.data)
      loadLeads()
    } catch (err) {
      setUploadResult({ error: err.response?.data?.detail || "Upload failed" })
    } finally { setUploading(false); e.target.value = "" }
  }

  const handleExport = async () => {
    if (!selectedRun) return
    setExporting(true)
    try {
      const res = await exportRun(selectedRun)
      alert(`Exported:\n${res.data.files.join("\n")}`)
    } catch { alert("Export failed") }
    finally { setExporting(false) }
  }

  const segClass = (s) => {
    if (!s) return "no-email"
    const m = { WARM: "warm", COLD: "cold", NO_EMAIL: "no-email" }
    return m[s] || "pending"
  }

  const seqClass = (s) => {
    if (!s) return "pending"
    const m = { day1_sent: "day1", day3_sent: "day3", day7_sent: "day7", replied: "replied", complete: "complete" }
    return m[s] || "pending"
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Leads</div>
        <div className="topbar-actions">
          {selectedRun && (
            <a className="btn sm" href={downloadForZoominfo(selectedRun)} download>
              <i className="ti ti-download" aria-hidden="true" /> Download for ZoomInfo
            </a>
          )}
          <label className="btn sm" style={{ cursor: "pointer" }}>
            <i className="ti ti-upload" aria-hidden="true" />
            {uploading ? "Uploading..." : "Upload enriched"}
            <input type="file" accept=".csv" style={{ display: "none" }} onChange={handleUpload} disabled={uploading} />
          </label>
          <button className="btn sm" onClick={handleExport} disabled={exporting}>
            <i className="ti ti-file-spreadsheet" aria-hidden="true" />
            {exporting ? "Exporting..." : "Export XLSX"}
          </button>
        </div>
      </div>
      <div className="page-content">
        {uploadResult && (
          <div className={`banner ${uploadResult.error ? "red" : "green"}`} style={{ marginBottom: 14 }}>
            <i className={`ti ti-${uploadResult.error ? "alert-circle" : "check"}`} aria-hidden="true" />
            <div>
              <div className="banner-title">{uploadResult.error ? "Upload failed" : "Upload complete"}</div>
              <div className="banner-msg">
                {uploadResult.error || `${uploadResult.matched} matched, ${uploadResult.updated} updated, ${uploadResult.unmatched} unmatched`}
              </div>
            </div>
          </div>
        )}
        <div className="filter-row">
          <div className="seg">
            {SEG_FILTERS.map(([val, label]) => (
              <button key={val} className={`seg-btn${segment === val ? " active" : ""}`}
                onClick={() => { setSegment(val); setOffset(0) }}>{label}</button>
            ))}
          </div>
          <select className="form-input" style={{ width: "auto" }} value={selectedRun}
            onChange={e => { setSelectedRun(e.target.value); setOffset(0) }}>
            {runs.map(r => (
              <option key={r.id} value={r.id}>Run {r.id.slice(0, 8)} — {r.status}</option>
            ))}
          </select>
        </div>
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th><th>Company</th><th>Title</th>
                  <th>Email</th><th>Phone</th><th>Location</th>
                  <th>Segment</th><th>Sequence</th><th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan="9" style={{ textAlign: "center", padding: 20, color: "var(--color-text-secondary)" }}>Loading...</td></tr>
                )}
                {!loading && leads.length === 0 && (
                  <tr><td colSpan="9" style={{ textAlign: "center", padding: 20, color: "var(--color-text-secondary)" }}>No leads found</td></tr>
                )}
                {leads.map(lead => (
                  <tr key={lead.id}>
                    <td style={{ fontWeight: 500, whiteSpace: "nowrap" }}>{lead.full_name || "—"}</td>
                    <td className="truncate">{lead.company || "—"}</td>
                    <td className="truncate" style={{ color: "var(--color-text-secondary)" }}>{lead.title || "—"}</td>
                    <td style={{ color: lead.email ? "var(--blue)" : "var(--color-text-tertiary)" }}>
                      {lead.email || "—"}
                    </td>
                    <td style={{ color: "var(--color-text-secondary)", whiteSpace: "nowrap" }}>{lead.phone || "—"}</td>
                    <td className="truncate" style={{ color: "var(--color-text-secondary)" }}>{lead.location || "—"}</td>
                    <td><span className={`badge ${segClass(lead.segment)}`}>{lead.segment || "—"}</span></td>
                    <td><span className={`badge ${seqClass(lead.email_sequence_status)}`}>
                      {(lead.email_sequence_status || "not started").replace(/_/g, " ")}
                    </span></td>
                    <td>
                      {lead.linkedin_url && (
                        <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="btn xs icon" title="LinkedIn">
                          <i className="ti ti-brand-linkedin" aria-hidden="true" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-footer">
            <span>Showing {offset + 1}–{offset + leads.length}</span>
            <div className="pagination">
              <button className="btn sm icon" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
                <i className="ti ti-chevron-left" aria-hidden="true" />
              </button>
              <button className="btn sm icon" disabled={leads.length < LIMIT}
                onClick={() => setOffset(offset + LIMIT)}>
                <i className="ti ti-chevron-right" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
