import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  exportCampaignZoomInfo,
  getCampaignDrafts,
  getCampaignLeads,
  getCampaignOverview,
  getCampaignRuns,
  getCampaigns,
  getSequenceSettings,
  personaliseRun,
  saveSequenceSettings,
  sendEmails,
  sendTestCopy,
  uploadCampaignEnriched,
  updateDraft,
} from "../api"

const tabs = ["Overview", "Leads", "Drafts", "Sequence", "Settings"]

const emptyOverview = {
  total_leads: 0,
  with_email: 0,
  no_email: 0,
  drafts_generated: 0,
  emails_sent: 0,
  followups_due: 0,
  replies: 0,
  completed: 0,
  total_runs: 0,
  runs: [],
}

const fmtDate = (value) => value ? new Date(value).toLocaleString() : "-"
const statusClass = (value) => (value || "pending").toLowerCase().replace("_", "-")

const groupIdsByRun = (items, selectedIds) => {
  const selected = new Set(selectedIds)
  return items.reduce((groups, item) => {
    if (!selected.has(item.id) || !item.run_id) return groups
    groups[item.run_id] = groups[item.run_id] || []
    groups[item.run_id].push(item.id)
    return groups
  }, {})
}

export default function CampaignDetail() {
  const { filename: encodedFilename } = useParams()
  const filename = decodeURIComponent(encodedFilename || "")
  const navigate = useNavigate()

  const [campaign, setCampaign] = useState(null)
  const [overview, setOverview] = useState(emptyOverview)
  const [runs, setRuns] = useState([])
  const [leads, setLeads] = useState([])
  const [drafts, setDrafts] = useState([])
  const [sequence, setSequence] = useState({ touches: [] })
  const [activeTab, setActiveTab] = useState("Overview")
  const [leadSegment, setLeadSegment] = useState("")
  const [selectedLeadIds, setSelectedLeadIds] = useState([])
  const [selectedDraftIds, setSelectedDraftIds] = useState([])
  const [selectedDraft, setSelectedDraft] = useState(null)
  const [draftForm, setDraftForm] = useState({
    email: "",
    email_subject: "",
    email_body: "",
    linkedin_message: "",
    research_summary: "",
  })
  const [testToEmail, setTestToEmail] = useState("")
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [savingDraft, setSavingDraft] = useState(false)
  const [savingSequence, setSavingSequence] = useState(false)
  const [uploadingEnriched, setUploadingEnriched] = useState(false)
  const [notice, setNotice] = useState(null)

  const loadWorkspace = useCallback(async () => {
    try {
      const [
        campaignsRes,
        overviewRes,
        runsRes,
        leadsRes,
        draftsRes,
        sequenceRes,
      ] = await Promise.all([
        getCampaigns(),
        getCampaignOverview(filename),
        getCampaignRuns(filename),
        getCampaignLeads(filename, {
          segment: leadSegment || undefined,
          limit: 500,
        }),
        getCampaignDrafts(filename),
        getSequenceSettings(filename),
      ])
      setCampaign(campaignsRes.data.find(c => c.filename === filename) || null)
      setOverview(overviewRes.data || emptyOverview)
      setRuns(runsRes.data || [])
      setLeads(leadsRes.data || [])
      setDrafts(draftsRes.data || [])
      setSequence(sequenceRes.data || { touches: [] })
    } catch (err) {
      setNotice({
        error: err.response?.data?.detail || "Campaign workspace failed to load",
      })
    } finally {
      setLoading(false)
    }
  }, [filename, leadSegment])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadWorkspace()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadWorkspace])

  const campaignName = campaign?.name || filename

  const toggleLead = (id) => {
    setSelectedLeadIds(cur =>
      cur.includes(id) ? cur.filter(item => item !== id) : [...cur, id]
    )
  }

  const toggleDraft = (id) => {
    setSelectedDraftIds(cur =>
      cur.includes(id) ? cur.filter(item => item !== id) : [...cur, id]
    )
  }

  const selectFirstFive = () => {
    setSelectedLeadIds(leads.filter(lead => lead.email).slice(0, 5).map(lead => lead.id))
  }

  const selectAllLeads = () => {
    setSelectedLeadIds(leads.filter(lead => lead.email).map(lead => lead.id))
  }

  const handleExportZoomInfo = () => {
    window.location.href = exportCampaignZoomInfo(filename)
  }

  const handleUploadEnriched = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploadingEnriched(true)
    setNotice(null)
    try {
      const res = await uploadCampaignEnriched(filename, file)
      setNotice({
        success: true,
        message: `Rows ${res.data.total_rows}, matched ${res.data.matched}, updated ${res.data.updated}, unmatched ${res.data.unmatched}`,
      })
      await loadWorkspace()
    } catch (err) {
      setNotice({
        error: err.response?.data?.detail || "Enriched upload failed",
      })
    } finally {
      setUploadingEnriched(false)
      event.target.value = ""
    }
  }

  const handleGenerateDrafts = async () => {
    if (selectedLeadIds.length === 0) {
      setNotice({ error: "Select at least one lead" })
      return
    }
    const grouped = groupIdsByRun(leads, selectedLeadIds)
    setGenerating(true)
    setNotice(null)
    try {
      const results = await Promise.all(
        Object.entries(grouped).map(([runId, ids]) =>
          personaliseRun(runId, {
            campaign_name: campaignName,
            lead_ids: ids,
            limit: ids.length,
          })
        )
      )
      const generated = results.reduce(
        (sum, res) => sum + (res.data.generated || 0),
        0,
      )
      setNotice({ success: true, message: `Generated ${generated} drafts` })
      setSelectedLeadIds([])
      await loadWorkspace()
      setActiveTab("Drafts")
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Draft generation failed" })
    } finally {
      setGenerating(false)
    }
  }

  const openDraft = (draft) => {
    setSelectedDraft(draft)
    setDraftForm({
      email: draft.email || "",
      email_subject: draft.email_subject || "",
      email_body: draft.email_body || "",
      linkedin_message: draft.linkedin_message || "",
      research_summary: draft.research_summary || "",
    })
    setNotice(null)
  }

  const saveDraft = async () => {
    if (!selectedDraft) return null
    setSavingDraft(true)
    try {
      const res = await updateDraft(
        selectedDraft.run_id,
        selectedDraft.id,
        {
          email: draftForm.email,
          email_subject: draftForm.email_subject,
          email_body: draftForm.email_body,
          linkedin_message: draftForm.linkedin_message,
        },
      )
      setSelectedDraft({ ...selectedDraft, ...res.data })
      setNotice({ success: true, message: "Draft saved" })
      await loadWorkspace()
      return res.data
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Save failed" })
      return null
    } finally {
      setSavingDraft(false)
    }
  }

  const handleSendTestCopy = async () => {
    if (!selectedDraft) return
    const target = testToEmail.trim()
    if (!target) {
      setNotice({ error: "Enter a test recipient email" })
      return
    }
    setSending(true)
    try {
      const saved = await saveDraft()
      if (!saved) return
      const res = await sendTestCopy(selectedDraft.run_id, selectedDraft.id, {
        test_to_email: target,
      })
      setNotice(
        res.data.success
          ? { success: true, message: `Test copy sent to ${target}` }
          : { error: res.data.error || "Test copy failed" },
      )
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Test copy failed" })
    } finally {
      setSending(false)
    }
  }

  const handleSendDraft = async (draft = selectedDraft) => {
    if (!draft) return
    setSending(true)
    try {
      if (selectedDraft?.id === draft.id) {
        const saved = await saveDraft()
        if (!saved) return
      }
      const res = await sendEmails(draft.run_id, [draft.id])
      setNotice({
        success: true,
        message: `Sent ${res.data.sent || 0}, skipped ${res.data.skipped || 0}, failed ${res.data.failed || 0}`,
      })
      await loadWorkspace()
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Send failed" })
    } finally {
      setSending(false)
    }
  }

  const handleSendSelectedDrafts = async () => {
    if (selectedDraftIds.length === 0) {
      setNotice({ error: "Select at least one draft" })
      return
    }
    const grouped = groupIdsByRun(drafts, selectedDraftIds)
    setSending(true)
    try {
      const results = await Promise.all(
        Object.entries(grouped).map(([runId, ids]) => sendEmails(runId, ids))
      )
      const sent = results.reduce((sum, res) => sum + (res.data.sent || 0), 0)
      const failed = results.reduce((sum, res) => sum + (res.data.failed || 0), 0)
      setNotice({ success: true, message: `Sent ${sent}, failed ${failed}` })
      setSelectedDraftIds([])
      await loadWorkspace()
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Send failed" })
    } finally {
      setSending(false)
    }
  }

  const updateTouch = (idx, key, value) => {
    setSequence(cur => ({
      ...cur,
      touches: (cur.touches || []).map((touch, i) =>
        i === idx ? { ...touch, [key]: value } : touch
      ),
    }))
  }

  const saveSequence = async () => {
    setSavingSequence(true)
    try {
      const touches = (sequence.touches || []).map(touch => ({
        number: Number(touch.number) || 1,
        name: touch.name || "",
        delay_days: Number(touch.delay_days) || 0,
        subject_template: touch.subject_template ?? touch.subject_prefix ?? "",
        email_body_template: touch.email_body_template || "",
        linkedin_message_template: touch.linkedin_message_template || "",
      }))
      await saveSequenceSettings(filename, { touches })
      setSequence({ touches })
      setNotice({ success: true, message: "Sequence settings saved" })
    } catch (err) {
      setNotice({ error: err.response?.data?.detail || "Save failed" })
    } finally {
      setSavingSequence(false)
    }
  }

  const pipeline = [
    ["Scraped", overview.total_leads],
    ["Email found", overview.with_email],
    ["Drafted", overview.drafts_generated],
    ["Sent", overview.emails_sent],
    ["Replied", overview.replies],
  ]

  return (
    <>
      <div className="topbar">
        <Link to="/campaigns" className="topbar-link">
          <i className="ti ti-arrow-left" aria-hidden="true" /> Campaigns
        </Link>
        <div className="topbar-title">{campaignName}</div>
        <div className="topbar-actions">
          <button
            className="btn"
            onClick={() => navigate("/runs", { state: { campaign: filename } })}
          >
            <i className="ti ti-player-play" aria-hidden="true" /> New run
          </button>
        </div>
      </div>

      <div className="page-content">
        {notice && (
          <div className={`banner ${notice.error ? "red" : "green"}`}>
            <i className={`ti ti-${notice.error ? "alert-circle" : "check"}`} aria-hidden="true" />
            <div className="banner-msg">{notice.error || notice.message}</div>
          </div>
        )}

        <div className="workspace-header">
          <div>
            <h1>{campaignName}</h1>
            <p>{campaign?.description || "Campaign sales workspace"}</p>
          </div>
          <span className="badge completed">Active</span>
        </div>

        <div className="workspace-tabs">
          {tabs.map(tab => (
            <button
              type="button"
              className={`workspace-tab${activeTab === tab ? " active" : ""}`}
              key={tab}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {loading && (
          <div className="card">
            <div className="card-body" style={{ color: "var(--color-text-secondary)" }}>
              Loading campaign workspace...
            </div>
          </div>
        )}

        {!loading && activeTab === "Overview" && (
          <>
            <div className="workspace-stats">
              {[
                ["total_leads", "Total leads"],
                ["with_email", "With email"],
                ["drafts_generated", "Drafts generated"],
                ["emails_sent", "Emails sent"],
                ["followups_due", "Follow-ups due"],
                ["replies", "Replies"],
              ].map(([key, label]) => (
                <div className="workspace-stat" key={key}>
                  <span>{label}</span>
                  <strong>{overview[key] || 0}</strong>
                </div>
              ))}
            </div>

            <div className="card">
              <div className="card-head"><h2>Pipeline</h2></div>
              <div className="card-body">
                <div className="pipeline-stepper">
                  {pipeline.map(([label, value]) => (
                    <div className="pipeline-step" key={label}>
                      <div className="pipeline-dot">{value || 0}</div>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-head"><h2>Runs</h2></div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Started</th>
                      <th>Scraped</th>
                      <th>Warm</th>
                      <th>Cold</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.length === 0 && (
                      <tr>
                        <td colSpan="7" style={{ textAlign: "center", padding: 18, color: "var(--color-text-secondary)" }}>
                          No runs attached to this campaign yet.
                        </td>
                      </tr>
                    )}
                    {runs.map(run => (
                      <tr key={run.id}>
                        <td style={{ fontFamily: "monospace" }}>{run.id.slice(0, 8)}</td>
                        <td><span className={`badge ${statusClass(run.status)}`}>{run.status}</span></td>
                        <td>{fmtDate(run.started_at)}</td>
                        <td>{run.total_scraped}</td>
                        <td>{run.total_warm}</td>
                        <td>{run.total_cold}</td>
                        <td><Link className="btn xs" to={`/runs/${run.id}`}>View logs</Link></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {!loading && activeTab === "Leads" && (
          <div className="card">
            <div className="card-head">
              <h2>Campaign leads</h2>
              <div className="topbar-actions">
                <button className="btn sm" onClick={handleExportZoomInfo}>
                  <i className="ti ti-download" aria-hidden="true" />
                  Export for ZoomInfo
                </button>
                <label className="btn sm" style={{ cursor: "pointer" }}>
                  <i className="ti ti-upload" aria-hidden="true" />
                  {uploadingEnriched ? "Uploading..." : "Upload enriched file"}
                  <input
                    type="file"
                    accept=".csv,.xlsx"
                    style={{ display: "none" }}
                    onChange={handleUploadEnriched}
                    disabled={uploadingEnriched}
                  />
                </label>
                <button className="btn sm" onClick={selectFirstFive}>Select first 5</button>
                <button className="btn sm" onClick={selectAllLeads}>Select all</button>
                <button className="btn sm" onClick={() => setSelectedLeadIds([])}>Clear</button>
                <button className="btn primary sm" onClick={handleGenerateDrafts} disabled={generating || selectedLeadIds.length === 0}>
                  <i className="ti ti-sparkles" aria-hidden="true" />
                  {generating ? "Generating..." : `Generate drafts (${selectedLeadIds.length})`}
                </button>
              </div>
            </div>
            <div className="banner blue" style={{ margin: "14px 18px 0" }}>
              <i className="ti ti-info-circle" aria-hidden="true" />
              <div className="banner-msg">
                Sales Navigator leads usually do not include email or phone. Export leads for ZoomInfo enrichment, enrich them manually in ZoomInfo Web UI, then upload the enriched file here.
              </div>
            </div>
            <div className="filter-row" style={{ padding: "14px 18px 0" }}>
              {[
                ["", "All"],
                ["WARM", "Warm"],
                ["COLD", "Cold"],
                ["NO_EMAIL", "No Email"],
              ].map(([value, label]) => (
                <button
                  type="button"
                  className={`seg-btn ${leadSegment === value ? "active" : ""}`}
                  key={label}
                  onClick={() => {
                    setLeadSegment(value)
                    setSelectedLeadIds([])
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th></th>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Title</th>
                    <th>Email</th>
                    <th>Segment</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.length === 0 && (
                    <tr>
                      <td colSpan="7" style={{ textAlign: "center", padding: 18, color: "var(--color-text-secondary)" }}>
                        No leads found for this campaign.
                      </td>
                    </tr>
                  )}
                  {leads.map(lead => (
                    <tr key={lead.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedLeadIds.includes(lead.id)}
                          disabled={!lead.email}
                          onChange={() => toggleLead(lead.id)}
                        />
                      </td>
                      <td style={{ fontWeight: 500 }}>{lead.full_name || "-"}</td>
                      <td>{lead.company || "-"}</td>
                      <td>{lead.title || "-"}</td>
                      <td style={{ color: lead.email ? "var(--blue)" : "var(--color-text-tertiary)" }}>{lead.email || "-"}</td>
                      <td><span className={`badge ${statusClass(lead.segment)}`}>{lead.segment || "-"}</span></td>
                      <td>{lead.email_sequence_status || "not_started"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && activeTab === "Drafts" && (
          <div className="card">
            <div className="card-head">
              <h2>Drafts</h2>
              <button className="btn primary sm" onClick={handleSendSelectedDrafts} disabled={sending || selectedDraftIds.length === 0}>
                <i className="ti ti-send" aria-hidden="true" />
                {sending ? "Sending..." : `Send selected (${selectedDraftIds.length})`}
              </button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th></th>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Email</th>
                    <th>Subject</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {drafts.length === 0 && (
                    <tr>
                      <td colSpan="7" style={{ textAlign: "center", padding: 18, color: "var(--color-text-secondary)" }}>
                        No drafts generated yet.
                      </td>
                    </tr>
                  )}
                  {drafts.map(draft => (
                    <tr key={draft.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedDraftIds.includes(draft.id)}
                          onChange={() => toggleDraft(draft.id)}
                        />
                      </td>
                      <td style={{ fontWeight: 500 }}>{draft.full_name || "-"}</td>
                      <td>{draft.company || "-"}</td>
                      <td style={{ color: draft.email ? "var(--blue)" : "var(--color-text-tertiary)" }}>{draft.email || "-"}</td>
                      <td className="truncate">{draft.email_subject || "-"}</td>
                      <td>{draft.email_sequence_status || "not_started"}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          <button className="btn xs" onClick={() => openDraft(draft)}>
                            <i className="ti ti-edit" aria-hidden="true" /> Edit/Send
                          </button>
                          <button className="btn xs" onClick={() => handleSendDraft(draft)} disabled={sending}>
                            <i className="ti ti-send" aria-hidden="true" /> Send
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!loading && activeTab === "Sequence" && (
          <div className="card">
            <div className="card-head">
              <h2>Sequence settings</h2>
              <button className="btn primary sm" onClick={saveSequence} disabled={savingSequence}>
                <i className="ti ti-device-floppy" aria-hidden="true" />
                {savingSequence ? "Saving..." : "Save settings"}
              </button>
            </div>
            <div className="card-body">
              <div className="banner blue" style={{ marginBottom: 16 }}>
                <i className="ti ti-info-circle" aria-hidden="true" />
                <div className="banner-msg">
                  These templates guide AI draft generation and follow-up emails for this campaign.
                </div>
              </div>
              <div className="sequence-template-list">
                {(sequence.touches || []).map((touch, idx) => (
                  <div className="sequence-touch" key={`${touch.number}-${idx}`}>
                    <div className="sequence-touch-head">
                      <h3>Touch {touch.number} - {touch.name || "Step"}</h3>
                      <div className="sequence-touch-controls">
                        <div className="form-group">
                          <div className="form-label">Touch number</div>
                          <input className="form-input" type="number" min="1"
                            value={touch.number}
                            onChange={e => updateTouch(idx, "number", e.target.value)} />
                        </div>
                        <div className="form-group">
                          <div className="form-label">Touch name</div>
                          <input className="form-input"
                            value={touch.name || ""}
                            onChange={e => updateTouch(idx, "name", e.target.value)} />
                        </div>
                        <div className="form-group">
                          <div className="form-label">Delay days</div>
                          <input className="form-input" type="number" min={Number(touch.number) === 1 ? "0" : "1"}
                            value={touch.delay_days}
                            onChange={e => updateTouch(idx, "delay_days", e.target.value)} />
                        </div>
                      </div>
                    </div>
                    <div className="form-group">
                      <div className="form-label">Subject template</div>
                      <input className="form-input"
                        value={touch.subject_template ?? touch.subject_prefix ?? ""}
                        onChange={e => updateTouch(idx, "subject_template", e.target.value)} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">Email body template</div>
                      <textarea
                        className="form-input textarea-lg"
                        rows="8"
                        value={touch.email_body_template || ""}
                        onChange={e => updateTouch(idx, "email_body_template", e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <div className="form-label">LinkedIn message template</div>
                      <textarea
                        className="form-input"
                        rows="3"
                        value={touch.linkedin_message_template || ""}
                        onChange={e => updateTouch(idx, "linkedin_message_template", e.target.value)}
                      />
                    </div>
                    <div className="template-vars">
                      Available variables: {"{{first_name}}"}, {"{{full_name}}"}, {"{{company}}"}, {"{{title}}"}, {"{{location}}"}, {"{{lead_context}}"}, {"{{campaign_value_prop}}"}, {"{{sender_name}}"}, {"{{touch1_subject}}"}
                    </div>
                  </div>
                ))}
              </div>
              <div className="banner blue" style={{ marginTop: 16, marginBottom: 0 }}>
                <i className="ti ti-info-circle" aria-hidden="true" />
                <div className="banner-msg">
                  Touch 1 is the intro. Touch 2 sends after its delay from Touch 1. Touch 3 sends after its delay from Touch 2.
                </div>
              </div>
            </div>
          </div>
        )}

        {!loading && activeTab === "Settings" && (
          <div className="card">
            <div className="card-head"><h2>Campaign settings</h2></div>
            <div className="card-body">
              <div className="grid2">
                <div>
                  <div className="form-label">Knowledge bases</div>
                  <div className="chips" style={{ marginTop: 8 }}>
                    {(campaign?.knowledge_bases || []).map(kb => (
                      <span className="chip purple" key={kb}>
                        <i className="ti ti-file-text" aria-hidden="true" />
                        {kb}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="form-label">Tone</div>
                  <div className="settings-value">{campaign?.tone || "-"}</div>
                </div>
                <div>
                  <div className="form-label">Target personas</div>
                  <div className="settings-value">{(campaign?.target_personas || []).join(", ") || "-"}</div>
                </div>
                <div>
                  <div className="form-label">Target industries</div>
                  <div className="settings-value">{(campaign?.target_industries || []).join(", ") || "-"}</div>
                </div>
              </div>
              <div className="banner purple" style={{ marginTop: 16, marginBottom: 0 }}>
                <i className="ti ti-file-settings" aria-hidden="true" />
                <div className="banner-msg">
                  Campaign metadata can be edited from the campaign JSON file for now.
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {selectedDraft && (
        <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && setSelectedDraft(null)}>
          <div className="modal modal-wide">
            <div className="modal-head">
              <div>
                <h2>Draft - {selectedDraft.full_name || "Lead"}</h2>
                <div style={{ fontSize: 11, color: "var(--color-text-secondary)" }}>
                  From: Configured Outlook sender via Microsoft Graph
                </div>
              </div>
              <button className="btn icon" onClick={() => setSelectedDraft(null)}>
                <i className="ti ti-x" aria-hidden="true" />
              </button>
            </div>
            <div className="modal-body">
              <div className="grid2">
                <div className="form-group">
                  <div className="form-label">To</div>
                  <input className="form-input" value={draftForm.email}
                    onChange={e => setDraftForm(f => ({ ...f, email: e.target.value }))} />
                </div>
                <div className="form-group">
                  <div className="form-label">Test copy recipient</div>
                  <input className="form-input" placeholder="you@example.com"
                    value={testToEmail}
                    onChange={e => setTestToEmail(e.target.value)} />
                </div>
              </div>
              <div className="form-group">
                <div className="form-label">Subject</div>
                <input className="form-input" value={draftForm.email_subject}
                  onChange={e => setDraftForm(f => ({ ...f, email_subject: e.target.value }))} />
              </div>
              <div className="form-group">
                <div className="form-label">Email body</div>
                <textarea className="form-input textarea-lg" value={draftForm.email_body}
                  onChange={e => setDraftForm(f => ({ ...f, email_body: e.target.value }))} />
              </div>
              <div className="form-group">
                <div className="form-label">LinkedIn message</div>
                <textarea className="form-input" rows="4" value={draftForm.linkedin_message}
                  onChange={e => setDraftForm(f => ({ ...f, linkedin_message: e.target.value }))} />
              </div>
              <div className="form-group">
                <div className="form-label">Research summary</div>
                <textarea className="form-input" rows="4" value={draftForm.research_summary} readOnly />
              </div>
              <div className="form-actions">
                <button className="btn" onClick={saveDraft} disabled={savingDraft}>
                  <i className="ti ti-device-floppy" aria-hidden="true" />
                  {savingDraft ? "Saving..." : "Save draft"}
                </button>
                <button className="btn" onClick={handleSendTestCopy} disabled={sending}>
                  <i className="ti ti-mail-forward" aria-hidden="true" />
                  Send test copy
                </button>
                <button className="btn primary" onClick={() => handleSendDraft()} disabled={sending}>
                  <i className="ti ti-send" aria-hidden="true" />
                  Send real email
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
