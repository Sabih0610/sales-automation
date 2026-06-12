import { useMemo, useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { useCampaignReport } from "../../queries"

const STATUS_LABELS = {
  active: "Active",
  not_started: "Not started",
  draft_generated: "Draft generated",
  enriched: "Enriched",
  waiting_followup: "Waiting follow-up",
  completed: "Completed",
  replied: "Replied",
  bounced: "Bounced",
  unsubscribed: "Unsubscribed",
}

function num(value) {
  return Number(value || 0)
}

function Metric({ label, value, suffix = "" }) {
  return (
    <div className="report-metric">
      <strong>
        {value}
        {suffix}
      </strong>
      <span>{label}</span>
    </div>
  )
}

function EmptyChart({ message }) {
  return (
    <div className="report-empty-chart">
      {message}
    </div>
  )
}

function formatDate(value) {
  if (!value) return ""
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null

  return (
    <div className="report-tooltip">
      <strong>{formatDate(label) || label}</strong>
      {payload.map((item) => (
        <div key={item.dataKey}>
          {item.name}: {item.value}
        </div>
      ))}
    </div>
  )
}

export default function ReportsTab({ filename }) {
  const [days, setDays] = useState(30)
  const { data: report, isLoading, isFetching } = useCampaignReport(filename, days)

  const totals = report?.totals || {
    sent: 0,
    replies: 0,
    bounces: 0,
    unsubscribes: 0,
    reply_rate: 0,
    bounce_rate: 0,
  }

  const daily = report?.daily || []
  const perTouch = report?.per_touch || []
  const statusBreakdown = report?.status_breakdown || {}

  const statusRows = useMemo(
    () =>
      Object.entries(statusBreakdown)
        .filter(([key, value]) => key !== "active" && num(value) > 0)
        .map(([key, value]) => ({
          status: STATUS_LABELS[key] || key,
          total: num(value),
        })),
    [statusBreakdown],
  )

  const hasDailyActivity = daily.some((item) => num(item.sent) || num(item.replies))
  const hasTouchData = perTouch.some((item) => num(item.sent) || num(item.replies_attributed))

  return (
    <div className="reports-page">
      <section className="card reports-hero">
        <div>
          <span className="eyebrow">Campaign reporting</span>
          <h2>Performance report</h2>
          <p>
            Track sent volume, replies, bounces, sequence touch performance, and campaign status.
          </p>
        </div>

        <div className="reports-controls">
          {[7, 30, 90].map((option) => (
            <button
              className={`btn sm ${days === option ? "primary" : ""}`}
              key={option}
              onClick={() => setDays(option)}
              type="button"
            >
              {option} days
            </button>
          ))}
        </div>
      </section>

      {isLoading ? (
        <div className="card">
          <div className="card-body muted">Loading report...</div>
        </div>
      ) : (
        <>
          <div className="report-metric-grid">
            <Metric label="Sent" value={totals.sent || 0} />
            <Metric label="Replies" value={totals.replies || 0} />
            <Metric label="Reply rate" value={totals.reply_rate || 0} suffix="%" />
            <Metric label="Bounces" value={totals.bounces || 0} />
            <Metric label="Bounce rate" value={totals.bounce_rate || 0} suffix="%" />
            <Metric label="Unsubscribes" value={totals.unsubscribes || 0} />
          </div>

          {isFetching && (
            <div className="report-refresh-note">
              Refreshing report…
            </div>
          )}

          <section className="card report-card">
            <div className="card-head">
              <div>
                <h2>Daily activity</h2>
                <p>Sent emails and replies over the selected period.</p>
              </div>
            </div>

            <div className="report-chart">
              {!hasDailyActivity ? (
                <EmptyChart message="No sent or reply activity in this period yet." />
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={daily}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={22} />
                    <YAxis allowDecimals={false} />
                    <Tooltip content={<CustomTooltip />} />
                    <Line
                      type="monotone"
                      dataKey="sent"
                      name="Sent"
                      stroke="var(--rc-purple, #5b4fc7)"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="replies"
                      name="Replies"
                      stroke="#2e7d4f"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>

          <div className="reports-grid">
            <section className="card report-card">
              <div className="card-head">
                <div>
                  <h2>Touch performance</h2>
                  <p>Reply rate by sequence touch.</p>
                </div>
              </div>

              <div className="table-wrap">
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Touch</th>
                      <th>Sent</th>
                      <th>Replies</th>
                      <th>Bounces</th>
                      <th>Reply rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {perTouch.length === 0 && (
                      <tr>
                        <td colSpan="5" className="empty-cell">
                          No touch data yet.
                        </td>
                      </tr>
                    )}

                    {perTouch.map((touch) => (
                      <tr key={touch.touch_number}>
                        <td>
                          <strong>{touch.name || `Touch ${touch.touch_number}`}</strong>
                          <div className="muted">Touch {touch.touch_number}</div>
                        </td>
                        <td>{touch.sent || 0}</td>
                        <td>{touch.replies_attributed || 0}</td>
                        <td>{touch.bounces || 0}</td>
                        <td>{touch.reply_rate || 0}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="card report-card">
              <div className="card-head">
                <div>
                  <h2>Status breakdown</h2>
                  <p>Current lead sequence states.</p>
                </div>
              </div>

              <div className="report-chart compact">
                {statusRows.length === 0 ? (
                  <EmptyChart message="No sequence status data yet." />
                ) : (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={statusRows} layout="vertical" margin={{ left: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" allowDecimals={false} />
                      <YAxis dataKey="status" type="category" width={110} />
                      <Tooltip />
                      <Bar
                        dataKey="total"
                        name="Leads"
                        fill="var(--rc-purple, #5b4fc7)"
                        radius={[0, 8, 8, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>
          </div>

          <section className="card report-card">
            <div className="card-head">
              <div>
                <h2>Touch chart</h2>
                <p>Sent and replies by sequence touch.</p>
              </div>
            </div>

            <div className="report-chart">
              {!hasTouchData ? (
                <EmptyChart message="No touch chart data yet." />
              ) : (
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={perTouch}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Bar
                      dataKey="sent"
                      name="Sent"
                      fill="var(--rc-purple, #5b4fc7)"
                      radius={[8, 8, 0, 0]}
                    />
                    <Bar
                      dataKey="replies_attributed"
                      name="Replies"
                      fill="#2e7d4f"
                      radius={[8, 8, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}