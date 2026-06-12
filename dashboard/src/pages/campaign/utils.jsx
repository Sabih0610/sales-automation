export const tabs = [
  ["overview", "Overview"],
  ["sources", "Sources"],
  ["leads", "Leads"],
  ["drafts", "Drafts"],
  ["queue", "Queue"],
  ["sequence", "Sequence"],
  ["reports", "Reports"],
  ["activity", "Activity"],
  ["settings", "Settings"],
]

export const tabLabels = Object.fromEntries(tabs)
export const tabSlugs = Object.fromEntries(tabs.map(([slug, label]) => [label, slug]))

export const defaultQueue = {
  due_today: [],
  scheduled: [],
  waiting: [],
  sent: [],
  failed: [],
  skipped: [],
}

export const emptyOverview = {
  total_leads: 0,
  needs_enrichment: 0,
  with_email: 0,
  drafts_generated: 0,
  approved_drafts: 0,
  scheduled: 0,
  emails_sent: 0,
  followups_due: 0,
  replies: 0,
  bounces: 0,
  unsubscribed: 0,
  completed: 0,
  active_sequence_steps: 0,
  pipeline: {
    scraped: 0,
    enriched: 0,
    drafted: 0,
    approved: 0,
    sent: 0,
    replied: 0,
    completed: 0,
  },
  lead_collection: {
    total_source_segments: 0,
    completed_segments: 0,
    running_segments: 0,
    total_scraped: 0,
    unique_leads: 0,
    duplicates_removed: 0,
    needs_enrichment: 0,
    with_email: 0,
  },
}

export const defaultRules = {
  mode: "manual",
  timezone: "Asia/Karachi",
  stop_on_reply: true,
  stop_on_bounce: true,
  stop_on_unsubscribe: true,
  skip_no_email: true,
  skip_weekends: true,
  send_window_start: "09:00",
  send_window_end: "17:00",
  daily_send_limit: 50,
  delay_between_sends_seconds: 60,
}

export const leadFilters = [
  ["all", "All"],
  ["needs_enrichment", "Needs enrichment"],
  ["with_email", "With email"],
  ["draft_not_generated", "Draft not generated"],
  ["draft_generated", "Draft generated"],
  ["approved", "Approved"],
  ["sent", "Sent"],
  ["replied", "Replied"],
  ["bounced", "Bounced"],
  ["unsubscribed", "Unsubscribed"],
]

export const queueViews = [
  ["due_today", "Due today"],
  ["scheduled", "Scheduled"],
  ["waiting", "Waiting"],
  ["failed", "Failed"],
  ["sent", "Sent"],
  ["skipped", "Skipped"],
]

export const activityFilters = [
  ["all", "All"],
  ["scraping", "Scraping"],
  ["enrichment", "Enrichment"],
  ["drafts", "Drafts"],
  ["sending", "Sending"],
  ["replies", "Replies"],
  ["errors", "Errors"],
]

export const emptyDraftForm = {
  subject: "",
  body: "",
}

export const terminalJobStatuses = new Set(["done", "failed", "cancelled"])

export const fmtDate = (value) => {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

export const statusClass = (value) =>
  (value || "pending").toLowerCase().replace(/_/g, "-")

export const statusText = (value) =>
  (value || "not_started").replace(/_/g, " ")

export const getDraftId = (draft) => draft?.draft_id || draft?.id || ""
export const getLeadId = (item) => item?.lead_id || item?.id || ""
export const draftSubject = (draft) => draft?.subject || draft?.email_subject || ""
export const draftBody = (draft) => draft?.body || draft?.email_body || ""

export const getDetectedTimezone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Karachi"
  } catch {
    return "Asia/Karachi"
  }
}

export const sequenceStepName = (number) => {
  if (Number(number) === 1) return "Intro"
  if (Number(number) === 2) return "Follow-up"
  if (Number(number) === 3) return "Final follow-up"
  return `Email ${number}`
}

export const sequenceStepLabel = (number) => `Email ${number} - ${sequenceStepName(number)}`

export const draftToForm = (draft) => ({
  subject: draftSubject(draft),
  body: draftBody(draft),
})

export const latestByLead = (drafts) => {
  const map = new Map()
  drafts.forEach((draft) => {
    const leadId = getLeadId(draft)
    if (!leadId) return
    const existing = map.get(leadId)
    if (!existing || String(draft.updated_at || "") > String(existing.updated_at || "")) {
      map.set(leadId, draft)
    }
  })
  return map
}

export const activityBucket = (type = "") => {
  if (["scraped", "exported_for_zoominfo"].includes(type)) return "scraping"
  if (["enriched", "uploaded_enriched"].includes(type)) return "enrichment"
  if (type.startsWith("draft_")) return "drafts"
  if (["email_sent", "followup_scheduled", "followup_due", "test_sent"].includes(type)) return "sending"
  if (["replied", "bounced", "unsubscribed", "do_not_contact"].includes(type)) return "replies"
  if (["failed", "skipped"].includes(type)) return "errors"
  return "all"
}

export const jobProgressMessage = (job, context) => {
  const total = Number(job.total || context.total || 0)
  const done = Number(job.done || 0)
  const failed = Number(job.failed || 0)
  const skipped = Number(job.skipped || 0)
  return `${context.progressLabel} ${done}/${total} (${failed} failed, ${skipped} skipped)...`
}

export const jobCompletionMessage = (job, context) => {
  if (job.status === "failed") {
    return job.error || `${context.doneLabel} failed`
  }
  if (job.status === "cancelled") {
    return `${context.doneLabel} cancelled`
  }
  const result = job.result || {}
  if (context.kind === "send") {
    return (
      result.message ||
      `Sent ${result.sent || 0}, skipped ${job.skipped || 0}, failed ${job.failed || 0}`
    )
  }
  return `${result.generated || 0} drafts generated. Review them in Drafts.`
}

export function MetricBox({ label, value }) {
  return (
    <div className="metric-card static">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

export function EmptyRow({ colSpan, text }) {
  return (
    <tr>
      <td colSpan={colSpan} className="empty-cell">{text}</td>
    </tr>
  )
}

export function LabeledValue({ label, value }) {
  return (
    <div className="labeled-value">
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  )
}

export function LabeledInput({ label, onChange, type = "text", value }) {
  return (
    <div className="form-group">
      <div className="form-label">{label}</div>
      <input className="form-input" type={type} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}
