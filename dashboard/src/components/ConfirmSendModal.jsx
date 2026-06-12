import { useState } from "react"

export default function ConfirmSendModal({ count, campaignName, onConfirm, onClose }) {
  const [typed, setTyped] = useState("")
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <h3>Send {count} emails?</h3>
        <p>You are about to send {count} emails to real prospects from the Royal Cyber domain{campaignName ? ` (campaign: ${campaignName})` : ""}.</p>
        <p>Type <strong>SEND</strong> to confirm.</p>
        <input autoFocus value={typed} onChange={(event) => setTyped(event.target.value)} placeholder="SEND" />
        <div className="modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className="btn-danger" disabled={typed !== "SEND"} onClick={() => { onConfirm(); onClose() }}>Send {count} emails</button>
        </div>
      </div>
    </div>
  )
}
