import { useState } from "react"

export default function ConfirmSendModal({
  body,
  campaignName,
  confirmClassName = "btn-danger",
  confirmLabel,
  count,
  onConfirm,
  onClose,
  requireSend = true,
  title,
}) {
  const [typed, setTyped] = useState("")
  const canConfirm = !requireSend || typed === "SEND"
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <h3>{title || `Send ${count} emails?`}</h3>
        <p>
          {body ||
            `You are about to send ${count} emails to real prospects from the Royal Cyber domain${
              campaignName ? ` (campaign: ${campaignName})` : ""
            }.`}
        </p>
        {requireSend && (
          <>
            <p>Type <strong>SEND</strong> to confirm.</p>
            <input autoFocus value={typed} onChange={(event) => setTyped(event.target.value)} placeholder="SEND" />
          </>
        )}
        <div className="modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className={confirmClassName} disabled={!canConfirm} onClick={() => { onConfirm(); onClose() }}>
            {confirmLabel || `Send ${count} emails`}
          </button>
        </div>
      </div>
    </div>
  )
}
