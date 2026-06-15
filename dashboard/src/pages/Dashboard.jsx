import { Link } from "react-router-dom"
import { useDashboardSummary } from "../queries"
import { relativeTime } from "../utils/relativeTime"

const emptySummary = {
  totals: {
    leads: 0,
    sent_today: 0,
    todays_cap: 0,
    replies_total: 0,
    active_campaigns: 0,
  },
  recent_activities: [],
  due_today_total: 0,
}

export default function Dashboard() {
  const { data = emptySummary, isLoading, error } = useDashboardSummary()
  const summary = { ...emptySummary, ...data, totals: { ...emptySummary.totals, ...(data?.totals || {}) } }
  const totals = summary.totals

  const cards = [
    {
      label: "Leads",
      value: totals.leads?.toLocaleString?.() || "0",
      to: "/campaigns",
    },
    {
      label: "Sent today",
      value: `${totals.sent_today || 0}/${totals.todays_cap || 0}`,
      to: "/campaigns",
    },
    {
      label: "Replies",
      value: totals.replies_total?.toLocaleString?.() || "0",
      to: "/campaigns",
    },
    {
      label: "Follow-ups due today",
      value: summary.due_today_total?.toLocaleString?.() || "0",
      to: "/campaigns",
    },
  ]

  return (
    <>
      <div className="topbar">
        <div className="topbar-title">Dashboard</div>
        <div className="topbar-actions">
          <Link to="/campaigns" className="btn primary">
            <i className="ti ti-speakerphone" aria-hidden="true" /> Campaigns
          </Link>
        </div>
      </div>
      <div className="page-content dashboard-summary">
        {error && (
          <div className="banner red">
            <i className="ti ti-alert-circle" aria-hidden="true" />
            <div>
              <div className="banner-title">Dashboard unavailable</div>
              <div className="banner-msg">{error.message || "Could not load summary."}</div>
            </div>
          </div>
        )}

        <div className="kpi-row">
          {cards.map((card) => (
            <Link className="kpi-card" to={card.to} key={card.label}>
              <span className="kpi-label">{card.label}</span>
              <strong className="kpi-value">{isLoading ? "..." : card.value}</strong>
            </Link>
          ))}
        </div>

        <div className="card">
          <div className="card-head"><h2>Recent activity</h2></div>
          <div className="activity-list">
            {summary.recent_activities.length === 0 && (
              <div className="empty-state">
                No activity yet — open a campaign and add leads.
              </div>
            )}
            {summary.recent_activities.map((activity, index) => (
              <div className="activity-row" key={`${activity.created_at}-${activity.activity_type}-${index}`}>
                <div>
                  <strong>{activity.lead_name || "Unknown lead"}</strong>
                  <span> · {activity.title || activity.activity_type}</span>
                </div>
                <div>
                  <span>{activity.campaign_filename || "Campaign"}</span>
                  <span> · {relativeTime(activity.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
