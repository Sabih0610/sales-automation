import { useMemo, useState } from "react"

const SECTIONS = [
  ["updated", "Updated"],
  ["unchanged", "Unchanged"],
  ["unmatched", "Unmatched"],
  ["ambiguous", "Ambiguous"],
  ["errors", "Errors"],
]

function safeItems(result, key) {
  return result?.report?.[key] || []
}

function FieldDiffs({ diffs = [] }) {
  if (!diffs.length) {
    return <span className="muted">No field changes</span>
  }

  return (
    <div className="recon-diffs">
      {diffs.map((diff, index) => (
        <div className="recon-diff" key={`${diff.field}-${index}`}>
          <strong>{diff.field}</strong>
          <span className="old-value">{diff.old || "—"}</span>
          <span>→</span>
          <span className="new-value">{diff.new || "—"}</span>
        </div>
      ))}
    </div>
  )
}

function VerificationStatus({ verification }) {
  if (!verification) return null

  const status = verification.status || ""
  const reason = verification.reason || ""

  return (
    <span className={`email-verify-badge ${status || "unknown"}`}>
      {status || "not checked"}
      {reason ? ` · ${reason}` : ""}
    </span>
  )
}

function ReportRow({ item, type }) {
  const lead = item.lead || {}
  const candidates = item.candidates || []

  return (
    <div className="recon-row">
      <div className="recon-row-main">
        <div>
          <strong>{item.label || `Row ${item.row}`}</strong>
          <p>
            Row {item.row}
            {item.match_method ? ` · matched by ${item.match_method}` : ""}
            {item.reason ? ` · ${item.reason}` : ""}
          </p>
        </div>

        <VerificationStatus verification={item.email_verification} />
      </div>

      {lead.id && (
        <div className="recon-lead">
          <span>{lead.full_name || "Unnamed lead"}</span>
          <span>{lead.company || "No company"}</span>
          <span>{lead.email || "No email"}</span>
        </div>
      )}

      {type === "updated" && <FieldDiffs diffs={item.diffs || []} />}

      {type === "ambiguous" && candidates.length > 0 && (
        <div className="recon-candidates">
          <strong>Possible matches</strong>
          {candidates.map((candidate) => (
            <div className="recon-candidate" key={candidate.id}>
              <span>{candidate.full_name || "Unnamed"}</span>
              <span>{candidate.company || "No company"}</span>
              <span>{candidate.email || "No email"}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function ReconciliationReportModal({ result, onClose }) {
  const [active, setActive] = useState("updated")

  const counts = useMemo(
    () => ({
      updated: result?.updated || 0,
      unchanged: result?.unchanged || 0,
      unmatched: result?.unmatched || 0,
      ambiguous: result?.ambiguous || 0,
      errors: result?.errors?.length || safeItems(result, "errors").length || 0,
    }),
    [result],
  )

  const activeItems = safeItems(result, active)

  return (
    <div className="recon-backdrop" role="presentation">
      <div className="recon-modal" role="dialog" aria-modal="true">
        <div className="recon-head">
          <div>
            <span className="eyebrow">Upload reconciliation</span>
            <h2>Enriched upload report</h2>
            <p>
              {result?.total_rows || 0} rows processed · {result?.matched || 0} matched
            </p>
          </div>

          <button className="btn sm" onClick={onClose} type="button">
            Close
          </button>
        </div>

        <div className="recon-summary">
          <div>
            <strong>{result?.total_rows || 0}</strong>
            <span>Total rows</span>
          </div>
          <div>
            <strong>{result?.matched || 0}</strong>
            <span>Matched</span>
          </div>
          <div>
            <strong>{counts.updated}</strong>
            <span>Updated</span>
          </div>
          <div>
            <strong>{counts.unmatched}</strong>
            <span>Unmatched</span>
          </div>
          <div>
            <strong>{counts.ambiguous}</strong>
            <span>Ambiguous</span>
          </div>
        </div>

        <div className="recon-tabs">
          {SECTIONS.map(([key, label]) => (
            <button
              className={active === key ? "active" : ""}
              key={key}
              onClick={() => setActive(key)}
              type="button"
            >
              {label}
              <span>{counts[key] || 0}</span>
            </button>
          ))}
        </div>

        <div className="recon-body">
          {activeItems.length === 0 ? (
            <div className="recon-empty">
              No {active} rows.
            </div>
          ) : (
            activeItems.map((item, index) => (
              <ReportRow
                item={item}
                key={`${active}-${item.row || index}`}
                type={active}
              />
            ))
          )}
        </div>
      </div>
    </div>
  )
}