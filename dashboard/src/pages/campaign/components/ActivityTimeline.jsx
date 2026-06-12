import { activityBucket, fmtDate } from "../utils.jsx"
import StatusPill from "./StatusPill.jsx"

export default function ActivityTimeline({ activities, compact = false }) {
  return (
    <div className={`activity-timeline ${compact ? "compact" : ""}`}>
      {activities.length === 0 && <div className="empty-state">No activity yet.</div>}
      {activities.map((activity, idx) => (
        <div className="activity-row" key={activity.id || `${activity.created_at}-${idx}`}>
          <div className={`activity-icon ${activityBucket(activity.activity_type)}`}>
            <i className="ti ti-point" aria-hidden="true" />
          </div>
          <div>
            <div className="activity-title">
              <strong>{activity.full_name || activity.lead_name || activity.title || activity.activity_type}</strong>
              <StatusPill value={activity.activity_type} />
            </div>
            <p>{activity.description || activity.title || "-"}</p>
            <time>{fmtDate(activity.created_at)}</time>
          </div>
        </div>
      ))}
    </div>
  )
}
