import { useMemo, useState } from "react"
import { useCampaignActivities } from "../../queries"
import ActivityTimeline from "./components/ActivityTimeline.jsx"
import { activityBucket, activityFilters } from "./utils.jsx"

export default function ActivityTab({ filename }) {
  const [activityFilter, setActivityFilter] = useState("all")
  const { data: activities = [] } = useCampaignActivities(filename, { limit: 100 })
  const filteredActivities = useMemo(() => {
    if (activityFilter === "all") return activities
    return activities.filter((activity) => activityBucket(activity.activity_type) === activityFilter)
  }, [activities, activityFilter])

  return (
    <div className="card">
      <div className="card-head">
        <h2>Campaign activity</h2>
        <div className="filter-row no-margin">
          {activityFilters.map(([value, label]) => (
            <button className={`seg-btn ${activityFilter === value ? "active" : ""}`} key={value} onClick={() => setActivityFilter(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <ActivityTimeline activities={filteredActivities} />
    </div>
  )
}
