export default function PipelineBar({ overview }) {
  const pipeline = [
    ["scraped", "Scraped", overview.pipeline?.scraped ?? overview.total_leads],
    ["enriched", "Enriched", overview.pipeline?.enriched ?? overview.with_email],
    ["drafted", "Drafted", overview.pipeline?.drafted ?? overview.drafts_generated],
    ["approved", "Approved", overview.pipeline?.approved ?? overview.approved_drafts],
    ["sent", "Sent", overview.pipeline?.sent ?? overview.emails_sent],
    ["replied", "Replied", overview.pipeline?.replied ?? overview.replies],
    ["completed", "Completed", overview.pipeline?.completed ?? overview.completed],
  ]

  return (
    <div className="campaign-pipeline">
      {pipeline.map(([key, label, count], index) => (
        <div className="pipe-card" key={key}>
          <span className="pipe-step">{index + 1}</span>
          <strong>{count || 0}</strong>
          <span>{label}</span>
        </div>
      ))}
    </div>
  )
}
