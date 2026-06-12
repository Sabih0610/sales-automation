import { Link } from "react-router-dom"
import { useCampaignActivities, useCampaignOverview, useCampaignRuns } from "../../queries"
import ActivityTimeline from "./components/ActivityTimeline.jsx"
import PipelineBar from "./components/PipelineBar.jsx"
import StatusPill from "./components/StatusPill.jsx"
import { EmptyRow, emptyOverview } from "./utils.jsx"

const runPath = (filename, runId) =>
  `/campaigns/${encodeURIComponent(filename)}/runs/${encodeURIComponent(runId)}`

function RunLink({ filename, run }) {
  const label = run.label || `Run ${run.id.slice(0, 8)}`
  return (
    <Link className="run-link" to={runPath(filename, run.id)}>
      <span>{label}</span>
      <span className="run-id-muted">{run.id.slice(0, 8)}</span>
    </Link>
  )
}

function ActivityMini({ activities }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Recent activity</h2></div>
      <ActivityTimeline activities={activities} compact />
    </div>
  )
}

export default function OverviewTab({ filename, onSelectTab }) {
  const { data: overviewData = emptyOverview } = useCampaignOverview(filename)
  const { data: runs = [] } = useCampaignRuns(filename)
  const { data: activities = [] } = useCampaignActivities(filename, { limit: 100 })
  const overview = { ...emptyOverview, ...overviewData }
  const leadCollection = overview.lead_collection || emptyOverview.lead_collection
  const cards = [
    ["total_leads", "Total leads", "ti-users", "leads"],
    ["with_email", "With email", "ti-at", "leads"],
    ["needs_enrichment", "Needs enrichment", "ti-database-search", "leads"],
    ["drafts_generated", "Drafts generated", "ti-mail-edit", "drafts"],
    ["approved_drafts", "Approved", "ti-circle-check", "drafts"],
    ["emails_sent", "Emails sent", "ti-send", "queue"],
    ["followups_due", "Follow-ups due", "ti-clock", "queue"],
    ["replies", "Replies", "ti-message-reply", "activity"],
  ]

  return (
    <>
      <div className="metric-grid">
        {cards.map(([key, label, icon, tab]) => (
          <button className="metric-card" key={key} onClick={() => onSelectTab(tab)}>
            <span className="metric-icon"><i className={`ti ${icon}`} aria-hidden="true" /></span>
            <strong>{overview[key] ?? 0}</strong>
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-head"><h2>Pipeline</h2></div>
        <div className="card-body">
          <PipelineBar overview={overview} />
        </div>
      </div>

      <div className="workspace-two-col">
        <div className="card">
          <div className="card-head"><h2>Recent source runs</h2></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Source type</th>
                  <th>Status</th>
                  <th>Scraped</th>
                  <th>Unique</th>
                  <th>Duplicates</th>
                  <th>Stop reason</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && <EmptyRow colSpan={8} text="No campaign runs yet." />}
                {runs.slice(0, 8).map((run) => (
                  <tr key={run.id}>
                    <td><RunLink filename={filename} run={run} /></td>
                    <td>Sales Navigator</td>
                    <td><StatusPill value={run.status} /></td>
                    <td>{run.total_scraped || 0}</td>
                    <td>{leadCollection.unique_leads || "-"}</td>
                    <td>{leadCollection.duplicates_removed || "-"}</td>
                    <td>{run.stop_reason || "-"}</td>
                    <td><Link className="btn xs" to={runPath(filename, run.id)}>View logs</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <ActivityMini activities={activities.slice(0, 10)} />
      </div>
    </>
  )
}
