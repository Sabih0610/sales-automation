import { useState } from "react"
import ActivityTimeline from "./ActivityTimeline.jsx"
import StatusPill from "./StatusPill.jsx"
import { LabeledValue, draftBody, draftSubject, fmtDate, getDraftId } from "../utils.jsx"

export default function LeadDrawer(props) {
  const {
    draftByLead,
    drafts,
    handleGenerateDrafts,
    handleMarkLead,
    lead,
    leadActivities,
    onClose,
  } = props
  const [leadDrawerTab, setLeadDrawerTab] = useState("Overview")
  const latestDraft = draftByLead.get(lead.id)

  return (
    <div className="drawer-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="lead-drawer">
        <div className="drawer-head">
          <div>
            <h2>{lead.full_name || "Lead"}</h2>
            <p>{lead.title || "-"} at {lead.company || "-"}</p>
          </div>
          <button className="btn icon" onClick={onClose}><i className="ti ti-x" aria-hidden="true" /></button>
        </div>
        <div className="drawer-tabs">
          {["Overview", "Drafts", "Activity"].map((tab) => (
            <button className={`workspace-tab ${leadDrawerTab === tab ? "active" : ""}`} key={tab} onClick={() => setLeadDrawerTab(tab)}>{tab}</button>
          ))}
        </div>
        {leadDrawerTab === "Overview" && (
          <div className="drawer-body">
            <LabeledValue label="Email" value={lead.email || "-"} />
            <LabeledValue label="Phone" value={lead.phone || "-"} />
            <LabeledValue label="Location" value={lead.location || "-"} />
            <LabeledValue label="LinkedIn URL" value={lead.linkedin_url || "-"} />
            <LabeledValue label="Segment" value={lead.segment || "-"} />
            <LabeledValue label="Sequence status" value={latestDraft?.status || lead.email_sequence_status || "not_started"} />
            <LabeledValue label="Last email sent" value={fmtDate(latestDraft?.sent_at)} />
            <LabeledValue label="Next follow-up due" value={fmtDate(lead.next_touch_due_at)} />
            <LabeledValue label="Stop reason" value={lead.stop_reason || "-"} />
            <div className="drawer-actions">
              <button className="btn primary" onClick={handleGenerateDrafts} disabled={!lead.email}>Generate draft</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "replied")}>Mark replied</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "bounced")}>Mark bounced</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "unsubscribed")}>Mark unsubscribed</button>
              <button className="btn danger" onClick={() => handleMarkLead(lead.id, "do_not_contact")}>Do not contact</button>
            </div>
          </div>
        )}
        {leadDrawerTab === "Drafts" && (
          <div className="drawer-body">
            {drafts.length === 0 && <div className="empty-state">No drafts generated for this lead.</div>}
            {drafts.map((draft) => (
              <div className="mini-draft-card" key={getDraftId(draft)}>
                <div>
                  <span className="touch-badge">Email {draft.touch_number}</span>
                  <StatusPill value={draft.status} />
                </div>
                <strong>{draftSubject(draft) || "No subject"}</strong>
                <p>{draftBody(draft).slice(0, 180)}</p>
              </div>
            ))}
          </div>
        )}
        {leadDrawerTab === "Activity" && (
          <ActivityTimeline activities={leadActivities} compact />
        )}
      </aside>
    </div>
  )
}
