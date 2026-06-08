import { useState } from "react"
import api from "../api"

const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

export default function Settings() {
  const [form, setForm] = useState({
    azure_tenant_id: "", azure_client_id: "",
    azure_client_secret: "", sender_email: "",
    openai_api_key: "", openai_model: "gpt-4o-mini",
    zoominfo_enabled: false, zoominfo_client_id: "", zoominfo_private_key: "",
    max_emails_per_day: 150, send_delay_seconds: 3,
    send_days: ["Mon","Tue","Wed","Thu"],
    send_window_start: "08:00", send_window_end: "16:00",
  })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const toggleDay = (d) => setForm(f => ({
    ...f,
    send_days: f.send_days.includes(d) ? f.send_days.filter(x => x !== d) : [...f.send_days, d]
  }))

  const handleSave = async () => {
    setSaving(true); setSaved(false)
    try {
      await api.post("/settings", form)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { /* fallback */ }
    finally { setSaving(false) }
  }

  const handleTest = async () => {
    setTesting(true); setTestResult(null)
    try {
      await api.post("/settings/test-email")
      setTestResult("ok")
    } catch {
      setTestResult("err")
    } finally { setTesting(false) }
  }

  const F = (key) => ({
    value: form[key],
    onChange: e => setForm(f => ({ ...f, [key]: e.target.value }))
  })

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Settings</div>
        <div className="topbar-actions">
          {saved && <span style={{ fontSize: 12, color: "var(--green)" }}><i className="ti ti-check" /> Saved</span>}
          <button className="btn primary" onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save all"}
          </button>
        </div>
      </div>
      <div className="page-content">
        <div className="grid2">
          <div>
            <div className="card">
              <div className="card-head"><h2>Microsoft Graph — email sending</h2></div>
              <div className="card-body">
                <div className="form-group">
                  <div className="form-label">Tenant ID</div>
                  <input className="form-input" type="password" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" {...F("azure_tenant_id")} />
                </div>
                <div className="form-group">
                  <div className="form-label">Client ID</div>
                  <input className="form-input" type="password" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" {...F("azure_client_id")} />
                </div>
                <div className="form-group">
                  <div className="form-label">Client secret</div>
                  <input className="form-input" type="password" placeholder="Client secret value" {...F("azure_client_secret")} />
                </div>
                <div className="form-group">
                  <div className="form-label">Sender email</div>
                  <input className="form-input" placeholder="you@royalcyber.com" {...F("sender_email")} />
                </div>
                {testResult && (
                  <div className={`banner ${testResult === "ok" ? "green" : "red"}`} style={{ marginBottom: 12 }}>
                    <i className={`ti ti-${testResult === "ok" ? "check" : "alert-circle"}`} aria-hidden="true" />
                    <div className="banner-msg">{testResult === "ok" ? "Connection successful — test email sent" : "Connection failed — check credentials"}</div>
                  </div>
                )}
                <button className="btn" style={{ width: "100%" }} onClick={handleTest} disabled={testing}>
                  {testing ? "Testing..." : "Test connection"}
                </button>
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>OpenAI</h2></div>
              <div className="card-body">
                <div className="form-group">
                  <div className="form-label">API key</div>
                  <input className="form-input" type="password" placeholder="sk-proj-..." {...F("openai_api_key")} />
                </div>
                <div className="form-group">
                  <div className="form-label">Model</div>
                  <select className="form-input" {...F("openai_model")}>
                    <option value="gpt-4o-mini">gpt-4o-mini (faster, cheaper)</option>
                    <option value="gpt-4o">gpt-4o (more accurate)</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>Enrichment</h2></div>
              <div className="card-body">
                <div className="form-group">
                  <div className="form-label">Provider</div>
                  <select className="form-input" value={form.zoominfo_enabled ? "zoominfo" : "free"}
                    onChange={e => setForm(f => ({ ...f, zoominfo_enabled: e.target.value === "zoominfo" }))}>
                    <option value="free">Free (Clearbit + SMTP)</option>
                    <option value="zoominfo">ZoomInfo API</option>
                  </select>
                </div>
                {form.zoominfo_enabled && (
                  <>
                    <div className="form-group">
                      <div className="form-label">ZoomInfo client ID</div>
                      <input className="form-input" {...F("zoominfo_client_id")} />
                    </div>
                    <div className="form-group">
                      <div className="form-label">ZoomInfo private key</div>
                      <input className="form-input" type="password" {...F("zoominfo_private_key")} />
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
          <div>
            <div className="card">
              <div className="card-head"><h2>Sending limits</h2></div>
              <div className="card-body">
                <div className="form-group">
                  <div className="form-label">Max emails per day</div>
                  <input className="form-input" type="number" {...F("max_emails_per_day")} />
                  <div className="form-hint">Microsoft 365 allows up to 10,000/day. Keep under 150 for safe deliverability.</div>
                </div>
                <div className="form-group">
                  <div className="form-label">Delay between sends (seconds)</div>
                  <input className="form-input" type="number" min="2" {...F("send_delay_seconds")} />
                </div>
                <div className="form-group">
                  <div className="form-label">Send days</div>
                  <div className="chips" style={{ marginTop: 6 }}>
                    {DAYS.map(d => (
                      <div key={d}
                        className={`chip${form.send_days.includes(d) ? " purple" : ""}`}
                        style={{ cursor: "pointer" }}
                        onClick={() => toggleDay(d)}>{d}</div>
                    ))}
                  </div>
                </div>
                <div className="form-group">
                  <div className="form-label">Send window (recipient local time)</div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input className="form-input" style={{ width: 90 }} {...F("send_window_start")} />
                    <span style={{ color: "var(--color-text-secondary)" }}>to</span>
                    <input className="form-input" style={{ width: 90 }} {...F("send_window_end")} />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
