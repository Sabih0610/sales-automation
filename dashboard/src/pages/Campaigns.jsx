import { useEffect, useState } from "react"
import { createCampaign, getCampaigns, getKnowledgeBases } from "../api"

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState([])
  const [kbFiles, setKbFiles] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({
    name: "", description: "", target_personas: "", target_industries: "",
    tone: "professional", email_goal: "book a 20-minute discovery call",
    max_email_words: 150, max_linkedin_chars: 280, knowledge_bases: []
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [uploadingKb, setUploadingKb] = useState(false)
  const [uploadKbResult, setUploadKbResult] = useState(null)

  useEffect(() => {
    getCampaigns().then(r => setCampaigns(r.data)).catch(() => {})
    getKnowledgeBases().then(r => setKbFiles(r.data)).catch(() => {})
  }, [])

  const toggleKb = (filename) => {
    setForm(f => ({
      ...f,
      knowledge_bases: f.knowledge_bases.includes(filename)
        ? f.knowledge_bases.filter(k => k !== filename)
        : [...f.knowledge_bases, filename]
    }))
  }

  const handleKbUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingKb(true)
    setUploadKbResult(null)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const res = await fetch(
        "http://localhost:8000/api/knowledge-bases/upload",
        { method: "POST", body: formData }
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || "Upload failed")
      setUploadKbResult({ success: true, msg: data.message })
      getKnowledgeBases().then(r => setKbFiles(r.data)).catch(() => {})
    } catch (err) {
      setUploadKbResult({ error: err.message })
    } finally {
      setUploadingKb(false)
      e.target.value = ""
    }
  }

  const handleSave = async () => {
    if (!form.name.trim()) { setError("Campaign name is required"); return }
    if (form.knowledge_bases.length === 0) { setError("Select at least one knowledge base"); return }
    setSaving(true); setError("")
    try {
      await createCampaign({
        ...form,
        target_personas: form.target_personas
          .split(",").map(s => s.trim()).filter(Boolean),
        target_industries: form.target_industries
          .split(",").map(s => s.trim()).filter(Boolean),
      })
      setShowCreate(false)
      setForm({ name: "", description: "", target_personas: "", target_industries: "",
        tone: "professional", email_goal: "book a 20-minute discovery call",
        max_email_words: 150, max_linkedin_chars: 280, knowledge_bases: [] })
      getCampaigns().then(r => setCampaigns(r.data)).catch(() => {})
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to save campaign")
    } finally { setSaving(false) }
  }

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Campaigns</div>
        <div className="topbar-actions">
          <label className="btn" style={{ cursor: "pointer" }}>
            <i className="ti ti-file-upload" aria-hidden="true" />
            {uploadingKb ? "Uploading..." : "Upload KB file"}
            <input type="file" accept=".txt,.pdf,.docx"
              style={{ display: "none" }}
              onChange={handleKbUpload}
              disabled={uploadingKb} />
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
        <div className="grid2">
          {campaigns.map(c => (
            <div className="card" key={c.filename}>
              <div className="card-head">
                <h2>{c.name}</h2>
                <span className="badge completed">Active</span>
              </div>
              <div className="card-body">
                {c.description && (
                  <p style={{ fontSize: 12, color: "var(--color-text-secondary)", marginBottom: 12 }}>{c.description}</p>
                )}
                <div style={{ marginBottom: 10 }}>
                  <div className="form-label" style={{ marginBottom: 6 }}>Knowledge bases</div>
                  <div className="chips">
                    {(c.knowledge_bases || []).map(kb => (
                      <div className="chip purple" key={kb}>
                        <i className="ti ti-file-text" aria-hidden="true" style={{ fontSize: 11 }} />{kb}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {campaigns.length === 0 && (
            <div style={{ gridColumn: "1/-1", textAlign: "center", padding: 40, color: "var(--color-text-secondary)" }}>
              No campaigns yet. Create your first one.
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
                        <div className={`kb-card${sel ? " selected" : ""}`} key={kb} onClick={() => toggleKb(kb)}>
                          <i className="ti ti-file-text" aria-hidden="true" />
                          <div>
                            <div className="kb-title">{kb}</div>
                          </div>
                          {sel && <div className="kb-check"><i className="ti ti-check" aria-hidden="true" /></div>}
                        </div>
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
