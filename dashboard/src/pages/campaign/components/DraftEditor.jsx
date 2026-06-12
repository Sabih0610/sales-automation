import StatusPill from "./StatusPill.jsx"
import {
  LabeledValue,
  draftBody,
  draftSubject,
  fmtDate,
  getDraftId,
} from "../utils.jsx"

export function PreviewModal({ draft, draftForm, onClose }) {
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide preview-modal">
        <div className="modal-head">
          <h2>Email preview</h2>
          <button className="btn icon" onClick={onClose}><i className="ti ti-x" aria-hidden="true" /></button>
        </div>
        <div className="modal-body">
          <div className="preview-meta">
            <LabeledValue label="Recipient" value={draft.email || "-"} />
            <LabeledValue label="Sender" value={import.meta.env.VITE_SENDER_EMAIL || "Configured Microsoft Graph sender"} />
            <LabeledValue label="Plan email" value={`Email ${draft.touch_number || 1}`} />
            <LabeledValue label="Status" value={draft.status || "draft"} />
          </div>
          <div className="preview-subject">{draftForm.subject || "No subject"}</div>
          <pre className="preview-body">{draftForm.body || "No body"}</pre>
        </div>
      </div>
    </div>
  )
}

export default function DraftEditor(props) {
  const {
    actionBusy,
    draftForm,
    handleApproveDraft,
    handlePreviewDraft,
    handleSaveDraft,
    handleSendSelectedApproved,
    handleSendTest,
    handleSkipDraft,
    selectedDraft,
    setDraftForm,
    setTestEmail,
    testEmail,
  } = props
  const readOnly = ["sent", "skipped"].includes(selectedDraft?.status)

  return (
    <div className="card composer-card">
      <div className="card-head">
        <h2>Email composer</h2>
        {selectedDraft && (
          <div className="topbar-actions">
            <StatusPill value={selectedDraft.status} />
          </div>
        )}
      </div>
      {!selectedDraft ? (
        <div className="empty-state">Select a draft to review and approve.</div>
      ) : (
        <div className="composer-body">
          <div className="composer-line">
            <span>To</span>
            <div className="email-chip">{selectedDraft.email || "missing email"}</div>
          </div>
          <div className="composer-line">
            <span>From</span>
            <div className="muted">Configured Microsoft Graph sender</div>
          </div>
          <div className="composer-line">
            <span>Context</span>
            <div className="muted">{selectedDraft.title || "Lead"} at {selectedDraft.company || "their company"}</div>
          </div>
          {Number(selectedDraft.touch_number || 1) > 1 && (
            <div className="previous-context">
              <div className="previous-context-title">Previous email context</div>
              <LabeledValue label="Previous email subject" value={selectedDraft.previous_subject || "-"} />
              <LabeledValue label="Previous sent time" value={fmtDate(selectedDraft.previous_sent_at)} />
              <div className="previous-body-preview">
                {(selectedDraft.previous_body || "").slice(0, 700) || "No previous email body found."}
              </div>
            </div>
          )}
          <div className="composer-line">
            <span>Subject</span>
            <input
              disabled={readOnly}
              value={draftForm.subject}
              onChange={(e) => setDraftForm((form) => ({ ...form, subject: e.target.value }))}
            />
          </div>
          <textarea
            className="composer-textarea"
            disabled={readOnly}
            value={draftForm.body}
            onChange={(e) => setDraftForm((form) => ({ ...form, body: e.target.value }))}
          />
          <div className="composer-actions">
            <button className="btn" onClick={handleSaveDraft} disabled={actionBusy || readOnly}>Save</button>
            <button className="btn" onClick={handlePreviewDraft} disabled={!selectedDraft}>Preview</button>
            <button className="btn" onClick={() => handleApproveDraft()} disabled={actionBusy || selectedDraft.status === "sent"}>Approve</button>
            <input className="form-input test-email" placeholder="test@company.com" value={testEmail} onChange={(e) => setTestEmail(e.target.value)} />
            <button className="btn" onClick={handleSendTest} disabled={actionBusy}>Send test</button>
            <button className="btn primary" onClick={() => handleSendSelectedApproved([getDraftId(selectedDraft)], { direct: true })} disabled={selectedDraft.status !== "approved"}>Send approved</button>
            <button className="btn danger" onClick={handleSkipDraft} disabled={actionBusy || readOnly}>Skip</button>
          </div>
        </div>
      )}
    </div>
  )
}

export function MiniDraftCard({ draft }) {
  return (
    <div className="mini-draft-card" key={getDraftId(draft)}>
      <div>
        <span className="touch-badge">Email {draft.touch_number}</span>
        <StatusPill value={draft.status} />
      </div>
      <strong>{draftSubject(draft) || "No subject"}</strong>
      <p>{draftBody(draft).slice(0, 180)}</p>
    </div>
  )
}
