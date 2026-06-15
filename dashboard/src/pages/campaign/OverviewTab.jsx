import { useCampaignOverview, useCampaignQueue } from "../../queries"
import { defaultQueue, emptyOverview } from "./utils.jsx"

function activeQueueItems(queue) {
  if (Array.isArray(queue.items)) return queue.items
  return [
    ...(queue.due_today || []),
    ...(queue.scheduled || []),
    ...(queue.waiting || []),
  ]
}

function sendingStatusSummary(queueData, overview) {
  const queue = { ...defaultQueue, ...(queueData || {}) }
  const items = activeQueueItems(queue)
  const statusCount = (values) =>
    items.filter((item) =>
      values.includes(String(item.status || item.draft_status || "").toLowerCase()),
    ).length

  return {
    scheduled:
      (queue.due_today?.length || 0) +
      (queue.waiting?.length || 0) +
      Math.max(queue.scheduled?.length || 0, overview.scheduled || 0) +
      statusCount(["queued", "pending"]),
    sending: statusCount(["sending", "running", "in_progress"]),
    failed: (queue.failed?.length || 0) + statusCount(["failed", "error"]),
  }
}

export default function OverviewTab({ filename, onSelectTab }) {
  const { data: overviewData = emptyOverview } = useCampaignOverview(filename)
  const { data: queueData = defaultQueue } = useCampaignQueue(filename)
  const overview = { ...emptyOverview, ...overviewData }
  const sendingStats = sendingStatusSummary(queueData, overview)

  const detailCards = [
    {
      icon: "ti-mail-edit",
      label: "Drafts generated",
      tab: "drafts",
      value: overview.drafts_generated ?? 0,
    },
    {
      icon: "ti-message-reply",
      label: "Replies",
      tab: "reports",
      value: overview.replies ?? 0,
    },
    {
      icon: "ti-alert-circle",
      label: "Bounces",
      tab: "reports",
      value: overview.bounces ?? 0,
    },
    {
      icon: "ti-user-off",
      label: "Unsubscribes",
      tab: "reports",
      value: overview.unsubscribed ?? 0,
    },
  ]

  return (
    <>
      <div className="overview-command-grid">
        <div className="card overview-command-card">
          <div className="card-head">
            <h2>Next actions</h2>
          </div>
          <div className="overview-cta-row">
            <button className="btn primary" onClick={() => onSelectTab("leads")} type="button">
              <i className="ti ti-user-plus" aria-hidden="true" />
              Add leads
            </button>
            <button className="btn" onClick={() => onSelectTab("leads")} type="button">
              <i className="ti ti-sparkles" aria-hidden="true" />
              Generate drafts
            </button>
            <button className="btn" onClick={() => onSelectTab("drafts")} type="button">
              <i className="ti ti-mail-check" aria-hidden="true" />
              Review drafts
            </button>
            <button className="btn" onClick={() => onSelectTab("drafts")} type="button">
              <i className="ti ti-calendar-check" aria-hidden="true" />
              Approve &amp; Schedule
            </button>
          </div>
        </div>

        <div className="card overview-queue-card">
          <div className="card-head">
            <h2>Sending status</h2>
            <button className="btn sm" onClick={() => onSelectTab("drafts")} type="button">
              Open Drafts
            </button>
          </div>
          <div className="overview-queue-stats">
            {[
              ["Scheduled", sendingStats.scheduled],
              ["Sending", sendingStats.sending],
              ["Failed", sendingStats.failed],
            ].map(([label, value]) => (
              <div className="overview-queue-stat" key={label}>
                <strong>{value}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="metric-grid">
        {detailCards.map(({ icon, label, tab, value }) => (
          <button className="metric-card" key={label} onClick={() => onSelectTab(tab)}>
            <span className="metric-icon"><i className={`ti ${icon}`} aria-hidden="true" /></span>
            <strong>{value}</strong>
            <span>{label}</span>
          </button>
        ))}
      </div>
    </>
  )
}
