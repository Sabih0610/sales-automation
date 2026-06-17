import { useEffect, useMemo, useState } from "react"
import { ProductButton, ProductModal } from "../../components/product"
import { useSequenceSampleLeads, useSequencePreview } from "../../queries"

export default function SampleEmailModal({ open, onClose, campaignFilename, emailSteps = [] }) {
  const [search, setSearch] = useState("")
  const [q, setQ] = useState("")
  const [touchNumber, setTouchNumber] = useState(emailSteps[0]?.number || 1)
  const [selectedLead, setSelectedLead] = useState(null)
  const [preview, setPreview] = useState(null)

  const previewMutation = useSequencePreview(campaignFilename)
  const { data: leads = [], isLoading } = useSequenceSampleLeads(
    campaignFilename,
    { q },
    open,
  )

  useEffect(() => {
    const timer = setTimeout(() => setQ(search), 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (!open) {
      setSearch("")
      setQ("")
      setSelectedLead(null)
      setPreview(null)
      setTouchNumber(emailSteps[0]?.number || 1)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const activeStep = useMemo(
    () => emailSteps.find((step) => step.number === touchNumber) || emailSteps[0] || null,
    [emailSteps, touchNumber],
  )

  const runPreview = async (lead) => {
    setSelectedLead(lead)
    setPreview(null)
    try {
      const res = await previewMutation.mutateAsync({
        sample_lead_id: lead.id,
        touch_number: touchNumber,
        subject_template: activeStep?.subject || "",
        email_body_template: activeStep?.body || "",
      })
      setPreview(res?.data || res)
    } catch {
      setPreview({ error: "Could not generate a sample for this lead." })
    }
  }

  if (!open) return null

  return (
    <ProductModal
      className="sample-email-modal"
      footer={<ProductButton onClick={onClose}>Close</ProductButton>}
      onClose={onClose}
      open={open}
      subtitle="Pick a scraped lead to see how this email would read."
      title="Sample email"
    >
      <div className="sample-email-controls">
        {emailSteps.length > 1 && (
          <label className="sample-email-step">
            <span>Email</span>
            <select
              onChange={(event) => {
                setTouchNumber(Number(event.target.value))
                setPreview(null)
                setSelectedLead(null)
              }}
              value={touchNumber}
            >
              {emailSteps.map((step) => (
                <option key={step.number} value={step.number}>
                  Email {step.number}
                </option>
              ))}
            </select>
          </label>
        )}

        <input
          className="sample-email-search"
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search a lead by name..."
          value={search}
        />
      </div>

      <div className="sample-email-columns">
        <div className="sample-lead-list">
          {isLoading ? (
            <p className="sample-muted">Loading leads...</p>
          ) : leads.length === 0 ? (
            <p className="sample-muted">No scraped leads found for this campaign yet.</p>
          ) : (
            leads.map((lead) => (
              <button
                className={`sample-lead-item${selectedLead?.id === lead.id ? " active" : ""}`}
                key={lead.id}
                onClick={() => runPreview(lead)}
                type="button"
              >
                {lead.full_name}
              </button>
            ))
          )}
        </div>

        <div className="sample-preview-pane">
          {previewMutation.isPending ? (
            <p className="sample-muted">Generating sample for {selectedLead?.full_name}...</p>
          ) : !preview ? (
            <p className="sample-muted">Select a lead on the left to generate a sample email.</p>
          ) : preview.error ? (
            <p className="sample-error">{preview.error}</p>
          ) : (
            <div className="sample-preview-card">
              <div className="sample-preview-subject">
                <span>Subject</span>
                <strong>{preview.subject || "(no subject)"}</strong>
              </div>
              <pre className="sample-preview-text">{preview.body || "(no body)"}</pre>
              {!preview.used_ai && (
                <p className="sample-muted">Showing a template preview. AI personalisation was not available.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </ProductModal>
  )
}
