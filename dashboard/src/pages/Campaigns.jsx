import { useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  useCampaignOverview,
  useCampaigns,
  useCreateCampaign,
  useDeleteCampaign,
  useKnowledgeBases,
  useUploadKnowledgeBase,
} from "../queries"

const emptyStats = {
  total_leads: 0,
  with_email: 0,
  drafts_generated: 0,
  emails_sent: 0,
  followups_due: 0,
  replies: 0,
}

const statItems = [
  ["total_leads", "Leads"],
  ["with_email", "With email"],
  ["no_email", "Needs enrichment"],
  ["drafts_generated", "Drafted"],
  ["emails_sent", "Sent"],
  ["followups_due", "Due"],
]

function CampaignCard({ campaign, deleting, onDelete, onOpen }) {
  const { data: stats = emptyStats } = useCampaignOverview(campaign.filename)

  const handleKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onOpen()
    }
  }

  return (
    <article
      className="campaign-card"
      onClick={onOpen}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
    >
      <div className="campaign-card-head">
        <div>
          <h2>{campaign.name}</h2>
          <p>{campaign.description || "Campaign workspace"}</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="badge completed">Active</span>
          <button
            aria-label={`Delete campaign ${campaign.name}`}
            className="btn icon"
            disabled={deleting}
            onClick={(event) => {
              event.stopPropagation()
              onDelete(campaign)
            }}
            title="Delete campaign"
            type="button"
          >
            <i className="ti ti-trash" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="campaign-stat-grid">
        {statItems.map(([key, label]) => (
          <div className="campaign-stat" key={key}>
            <strong>{stats[key] ?? 0}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>

      <div className="campaign-kbs">
        {(campaign.knowledge_bases || []).length > 0 ? (
          (campaign.knowledge_bases || []).map(kb => (
            <span className="chip" key={kb}>
              <i className="ti ti-file-text" aria-hidden="true" />
              {kb}
            </span>
          ))
        ) : (
          <span className="campaign-muted">No KB files linked</span>
        )}
      </div>

      <div className="campaign-card-footer">
        <span>Open workspace</span>
        <i className="ti ti-arrow-right" aria-hidden="true" />
      </div>
    </article>
  )
}

export default function Campaigns() {
  const navigate = useNavigate()
  const { data: campaigns = [] } = useCampaigns()
  const { data: kbFiles = [] } = useKnowledgeBases()
  const createCampaignMutation = useCreateCampaign()
  const deleteCampaignMutation = useDeleteCampaign()
  const uploadKnowledgeBaseMutation = useUploadKnowledgeBase()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    name: "",
    description: "",
    target_personas: "",
    target_industries: "",
    tone: "professional",
    email_goal: "book a 20-minute discovery call",
    max_email_words: 150,
    max_linkedin_chars: 280,
    knowledge_bases: [],
  })
  const [error, setError] = useState("")
  const [uploadKbResult, setUploadKbResult] = useState(null)
  const saving = createCampaignMutation.isPending
  const uploadingKb = uploadKnowledgeBaseMutation.isPending

  const handleDeleteCampaign = async (campaign) => {
    const confirmed = window.confirm(
      `Delete campaign "${campaign.name}" and all related leads, drafts, sequences, reports, scrape history, and jobs? This cannot be undone.`,
    )
    if (!confirmed) return

    setError("")
    try {
      await deleteCampaignMutation.mutateAsync(campaign.filename)
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to delete campaign")
    }
  }

  const toggleKb = (filename) => {
    setForm(f => ({
      ...f,
      knowledge_bases: f.knowledge_bases.includes(filename)
        ? f.knowledge_bases.filter(k => k !== filename)
        : [...f.knowledge_bases, filename],
    }))
  }

  const resetForm = () => {
    setForm({
      name: "",
      description: "",
      target_personas: "",
      target_industries: "",
      tone: "professional",
      email_goal: "book a 20-minute discovery call",
      max_email_words: 150,
      max_linkedin_chars: 280,
      knowledge_bases: [],
    })
  }

  const handleKbUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadKbResult(null)
    try {
      const res = await uploadKnowledgeBaseMutation.mutateAsync(file)
      setUploadKbResult({ success: true, msg: res.data.message })
    } catch (err) {
      setUploadKbResult({
        error: err.response?.data?.detail || err.message || "Upload failed",
      })
    } finally {
      e.target.value = ""
    }
  }

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError("Campaign name is required")
      return
    }
    if (form.knowledge_bases.length === 0) {
      setError("Select at least one knowledge base")
      return
    }
    setError("")
    try {
      await createCampaignMutation.mutateAsync({
        ...form,
        target_personas: form.target_personas
          .split(",").map(s => s.trim()).filter(Boolean),
        target_industries: form.target_industries
          .split(",").map(s => s.trim()).filter(Boolean),
      })
      setShowCreate(false)
      resetForm()
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to save campaign")
    }
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Campaigns</div>
        <div className="topbar-actions">
          <label className="btn" style={{ cursor: "pointer" }}>
            <i className="ti ti-file-upload" aria-hidden="true" />
            {uploadingKb ? "Uploading..." : "Upload KB file"}
            <input
              type="file"
              accept=".txt,.pdf,.docx"
              style={{ display: "none" }}
              onChange={handleKbUpload}
              disabled={uploadingKb}
            />
          </label>
          <button className="btn primary" onClick={() => setShowCreate(true)}>
            <i className="ti ti-plus" aria-hidden="true" /> New campaign
          </button>
        </div>
      </div>

      {uploadKbResult && (
        <div style={{ padding: "0 24px 0" }}>
          <div className={`banner ${uploadKbResult.error ? "red" : "green"}`}
            style={{ marginTop: 12 }}>
            <i className={`ti ti-${uploadKbResult.error
              ? "alert-circle" : "check"}`} aria-hidden="true" />
            <div className="banner-msg">
              {uploadKbResult.error || uploadKbResult.msg}
            </div>
          </div>
        </div>
      )}

      <div className="page-content">
        <div className="campaign-grid">
          {campaigns.map(c => (
            <CampaignCard
              campaign={c}
              deleting={deleteCampaignMutation.isPending}
              key={c.filename}
              onDelete={handleDeleteCampaign}
              onOpen={() => navigate(`/campaigns/${encodeURIComponent(c.filename)}`)}
            />
          ))}
          {campaigns.length === 0 && (
            <div className="card" style={{ gridColumn: "1/-1" }}>
              <div className="card-body" style={{ textAlign: "center", color: "var(--color-text-secondary)" }}>
                Create campaign from JSON config.
              </div>
            </div>
          )}
        </div>
      </div>

      {showCreate && (
        <div className="modal-backdrop" onClick={e => e.target === e.currentTarget && setShowCreate(false)}>
          <div className="modal">
            <div className="modal-head">
              <h2>New campaign</h2>
              <button className="btn icon" onClick={() => setShowCreate(false)}>
                <i className="ti ti-x" aria-hidden="true" />
              </button>
            </div>
            <div className="modal-body">
              {error && <div className="form-error" style={{ marginBottom: 14 }}>{error}</div>}
              <div className="grid2">
                <div>
                  <div className="form-group">
                    <div className="form-label">Campaign name *</div>
                    <input className="form-input" placeholder="e.g. Fabric for Logistics CTOs"
                      value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <div className="form-label">Description</div>
                    <input className="form-input" placeholder="Brief description"
                      value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <div className="form-label">Target personas</div>
                    <input className="form-input" placeholder="CTO, CIO, Head of Data"
                      value={form.target_personas} onChange={e => setForm(f => ({ ...f, target_personas: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <div className="form-label">Target industries</div>
                    <input className="form-input" placeholder="Retail, Finance, Manufacturing"
                      value={form.target_industries} onChange={e => setForm(f => ({ ...f, target_industries: e.target.value }))} />
                  </div>
                  <div className="form-group">
                    <div className="form-label">Tone</div>
                    <select className="form-input" value={form.tone}
                      onChange={e => setForm(f => ({ ...f, tone: e.target.value }))}>
                      <option value="professional">Professional</option>
                      <option value="conversational">Conversational</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <div className="form-label">Email goal</div>
                    <input className="form-input" value={form.email_goal}
                      onChange={e => setForm(f => ({ ...f, email_goal: e.target.value }))} />
                  </div>
                </div>
                <div>
                  <div className="form-label" style={{ marginBottom: 8 }}>Select knowledge bases *</div>
                  <div className="kb-grid">
                    {kbFiles.map(kb => {
                      const sel = form.knowledge_bases.includes(kb)
                      return (
                        <button
                          type="button"
                          className={`kb-card${sel ? " selected" : ""}`}
                          key={kb}
                          onClick={() => toggleKb(kb)}
                        >
                          <i className="ti ti-file-text" aria-hidden="true" />
                          <div>
                            <div className="kb-title">{kb}</div>
                          </div>
                          {sel && <div className="kb-check"><i className="ti ti-check" aria-hidden="true" /></div>}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
              <div className="form-actions">
                <button className="btn" onClick={() => setShowCreate(false)}>Cancel</button>
                <button className="btn primary" onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Create campaign"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
