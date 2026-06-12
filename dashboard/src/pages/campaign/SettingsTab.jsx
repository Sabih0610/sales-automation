import { useEffect, useMemo, useState } from "react"
import { friendlyMessage } from "../../api"
import { useCampaigns, useUpdateCampaign } from "../../queries"

const EMPTY_FORM = {
  sender_name: "",
  sender_title: "",
  sender_email: "",
  reply_to_email: "",
}

function normalizeFilename(value = "") {
  return value.replace(/\.json$/, "")
}

export default function SettingsTab({ filename, showNotice }) {
  const { data: campaigns = [], isLoading } = useCampaigns()
  const updateCampaign = useUpdateCampaign(filename)
  const [form, setForm] = useState(EMPTY_FORM)

  const campaign = useMemo(
    () =>
      campaigns.find(
        (item) =>
          item.filename === filename ||
          item.filename === `${filename}.json` ||
          normalizeFilename(item.filename || "") === normalizeFilename(filename || ""),
      ),
    [campaigns, filename],
  )

  useEffect(() => {
    if (!campaign) return

    setForm({
      sender_name: campaign.sender_name || campaign.config?.sender_name || "",
      sender_title: campaign.sender_title || campaign.config?.sender_title || "",
      sender_email: campaign.sender_email || campaign.config?.sender_email || "",
      reply_to_email: campaign.reply_to_email || campaign.config?.reply_to_email || "",
    })
  }, [campaign])

  const notify = (message, error = false) => {
    if (showNotice) {
      showNotice(message, error)
    } else if (error) {
      console.error(message)
    } else {
      console.log(message)
    }
  }

  const updateField = (field, value) => {
    setForm((current) => ({
      ...current,
      [field]: value,
    }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()

    try {
      const payload = {
        sender_name: form.sender_name.trim(),
        sender_title: form.sender_title.trim(),
        sender_email: form.sender_email.trim(),
        reply_to_email: form.reply_to_email.trim(),
      }

      await updateCampaign.mutateAsync(payload)
      notify("Campaign sender identity saved")
    } catch (err) {
      notify(friendlyMessage(err) || "Failed to save sender identity", true)
    }
  }

  return (
    <div className="campaign-settings-page">
      <section className="card settings-hero">
        <div>
          <span className="eyebrow">Campaign settings</span>
          <h2>Sender identity</h2>
          <p>
            Control who this campaign sends from, who replies go to, and which
            sender variables are used inside email templates.
          </p>
        </div>
      </section>

      <section className="card sender-settings-card">
        <div className="card-head">
          <div>
            <h2>Email sender</h2>
            <p>
              These values override the global .env sender for this campaign only.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="card-body muted">Loading campaign settings...</div>
        ) : (
          <form className="sender-settings-form" onSubmit={handleSubmit}>
            <label>
              <span>Sender name</span>
              <input
                value={form.sender_name}
                onChange={(event) => updateField("sender_name", event.target.value)}
                placeholder="Royal Cyber Team"
              />
            </label>

            <label>
              <span>Sender title</span>
              <input
                value={form.sender_title}
                onChange={(event) => updateField("sender_title", event.target.value)}
                placeholder="Enterprise Solutions"
              />
            </label>

            <label>
              <span>Sender email</span>
              <input
                value={form.sender_email}
                onChange={(event) => updateField("sender_email", event.target.value)}
                placeholder="name@company.com"
                type="email"
              />
            </label>

            <label>
              <span>Reply-to email</span>
              <input
                value={form.reply_to_email}
                onChange={(event) => updateField("reply_to_email", event.target.value)}
                placeholder="reply@company.com"
                type="email"
              />
            </label>

            <div className="sender-preview">
              <span className="eyebrow">Signature preview</span>
              <div>
                Best,
                <br />
                {form.sender_name || "Royal Cyber Team"}
                {form.sender_title ? (
                  <>
                    <br />
                    {form.sender_title}
                  </>
                ) : null}
              </div>
            </div>

            <div className="sender-template-vars">
              <span className="eyebrow">Available template variables</span>
              <div>
                <code>{"{{sender_name}}"}</code>
                <code>{"{{sender_title}}"}</code>
                <code>{"{{sender_email}}"}</code>
                <code>{"{{reply_to_email}}"}</code>
                <code>{"{{sender_signature}}"}</code>
              </div>
            </div>

            <div className="settings-actions">
              <button
                className="btn primary"
                disabled={updateCampaign.isPending}
                type="submit"
              >
                {updateCampaign.isPending ? "Saving..." : "Save sender identity"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  )
}