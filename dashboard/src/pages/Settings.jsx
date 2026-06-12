import { useEffect, useState } from "react"
import { useSaveSettings, useSettings, useTestSettingsEmail } from "../queries"

const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

export default function Settings() {
  const { data: settings } = useSettings()
  const saveSettings = useSaveSettings()
  const testSettingsEmail = useTestSettingsEmail()
  const [form, setForm] = useState({
    sender_email: "",
    openai_model: "gpt-4o-mini",
    zoominfo_enabled: false,
    max_emails_per_day: 150, send_delay_seconds: 3,
    send_days: ["Mon","Tue","Wed","Thu"],
    send_window_start: "08:00", send_window_end: "16:00",
  })
  const [saved, setSaved] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const configured = {
    azure_configured: Boolean(settings?.azure_configured),
    openai_configured: Boolean(settings?.openai_configured),
    zoominfo_configured: Boolean(settings?.zoominfo_configured),
  }
  const saving = saveSettings.isPending
  const testing = testSettingsEmail.isPending

  useEffect(() => {
    if (!settings) return
    setForm((current) => ({
      ...current,
      sender_email: settings.sender_email || "",
      openai_model: settings.openai_model || "gpt-4o-mini",
      zoominfo_enabled: Boolean(settings.zoominfo_enabled),
      max_emails_per_day: settings.max_emails_per_day ?? current.max_emails_per_day,
      send_delay_seconds: settings.send_delay_seconds ?? current.send_delay_seconds,
    }))
  }, [settings])

  const toggleDay = (d) => setForm(f => ({
    ...f,
    send_days: f.send_days.includes(d) ? f.send_days.filter(x => x !== d) : [...f.send_days, d]
  }))

  const handleSave = async () => {
    setSaved(false)
    try {
      await saveSettings.mutateAsync(form)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { /* fallback */ }
  }

  const handleTest = async () => {
    setTestResult(null)
    try {
      await testSettingsEmail.mutateAsync()
      setTestResult("ok")
    } catch {
      setTestResult("err")
    }
  }

  const F = (key) => ({
    value: form[key],
    onChange: e => setForm(f => ({ ...f, [key]: e.target.value }))
  })

  const StatusRow = ({ label, configured }) => (
    <div className="settings-status-row">
      <span>{label}</span>
      <strong className={configured ? "ok" : "missing"}>
        {configured ? "Configured ✓" : "Missing ✗ (set in backend .env)"}
      </strong>
    </div>
  )

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
                <StatusRow label="Azure credentials" configured={configured.azure_configured} />
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
                <StatusRow label="OpenAI credentials" configured={configured.openai_configured} />
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
                <StatusRow label="ZoomInfo credentials" configured={configured.zoominfo_configured} />
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
