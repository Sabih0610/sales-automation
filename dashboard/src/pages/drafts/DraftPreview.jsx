import {
  ProductButton,
  ProductCard,
  ProductIconBox,
  ProductStatusBadge,
} from "../../components/product"
import { initialsFor, statusLabel } from "./DraftListRow.jsx"
import { displayStatus } from "./DraftListRow.jsx"

const cleanList = (value) => (Array.isArray(value) ? value.filter(Boolean) : [])
const sourceLabel = (source) => {
  if (!source || typeof source !== "object") return String(source || "")
  return source.title || source.name || source.filename || source.source || JSON.stringify(source)
}

export default function DraftPreview({
  draft,
  editBody,
  editing,
  editSubject,
  onCancelEdit,
  onEdit,
  onEditBody,
  onEditSubject,
  onSave,
  saving = false,
  senderEmail = "",
  senderName = "RC Sales",
}) {
  if (!draft) {
    return (
      <ProductCard className="draft-preview-empty">
        <ProductIconBox icon="ti-mail-opened" tone="primary" />
        <h2>Select a draft</h2>
        <p>Choose a draft from the list to review the generated email.</p>
      </ProductCard>
    )
  }

  const leadName = draft.full_name || draft.email || "Unknown lead"
  const title = draft.title || "Lead"
  const company = draft.company || "Company unknown"
  const subject = draft.subject || draft.email_subject || ""
  const body = draft.body || draft.email_body || ""
  const kbSources = cleanList(draft.kb_sources)
  const riskFlags = cleanList(draft.risk_flags)
  const visibleStatus = displayStatus(draft.status)

  return (
    <section className="draft-preview-panel">
      <ProductCard className="draft-preview-card" padding="lg">
        <div className="draft-preview-head">
          <div className="draft-preview-person">
            <span className="draft-review-avatar large">{initialsFor(leadName, company)}</span>
            <div>
              <h2>{leadName}</h2>
              <p>
                {title} <span aria-hidden="true">&middot;</span> {company}
              </p>
            </div>
          </div>

          <div className="draft-preview-head-actions">
            <ProductStatusBadge status={visibleStatus}>
              {statusLabel(visibleStatus)}
            </ProductStatusBadge>
            {editing ? (
              <>
                <ProductButton disabled={saving} onClick={onSave} size="sm" variant="primary">
                  Save
                </ProductButton>
                <ProductButton disabled={saving} onClick={onCancelEdit} size="sm" variant="secondary">
                  Cancel
                </ProductButton>
              </>
            ) : (
              <ProductButton icon="ti-pencil" onClick={onEdit} size="sm" variant="secondary">
                Edit
              </ProductButton>
            )}
          </div>
        </div>

        <div className="draft-email-meta">
          <div>
            <span>From</span>
            <strong>{senderName}{senderEmail ? ` <${senderEmail}>` : ""}</strong>
          </div>
          <div>
            <span>To</span>
            <strong>{leadName}{draft.email ? ` <${draft.email}>` : ""}</strong>
          </div>
        </div>

        <div className="draft-email-preview">
          <div className="draft-email-subject">
            <span>Subject</span>
            {editing ? (
              <input
                className="draft-review-input"
                onChange={(event) => onEditSubject?.(event.target.value)}
                value={editSubject}
              />
            ) : (
              <h3>{subject || "No subject"}</h3>
            )}
          </div>

          <div className="draft-email-body">
            <span>Body</span>
            {editing ? (
              <textarea
                className="draft-review-textarea"
                onChange={(event) => onEditBody?.(event.target.value)}
                rows={18}
                value={editBody}
              />
            ) : (
              <pre>{body || "No body generated yet."}</pre>
            )}
          </div>
        </div>
      </ProductCard>

      <ProductCard className="draft-sources-card" padding="lg">
        <details open>
          <summary>
            <span>Personalization sources</span>
            <i className="ti ti-chevron-down" aria-hidden="true" />
          </summary>
          <div className="draft-source-grid">
            <div>
              <span>Contact</span>
              <p>{leadName}</p>
              <small>{title}</small>
            </div>
            <div>
              <span>Company</span>
              <p>{company}</p>
              <small>{draft.location || "Company context"}</small>
            </div>
            <div>
              <span>Recent news / intent / research summary</span>
              <p>{draft.research_summary || "No research summary recorded for this draft."}</p>
            </div>
          </div>

          {kbSources.length > 0 && (
            <div className="draft-source-tags">
              {kbSources.slice(0, 6).map((source, index) => (
                <span key={`${sourceLabel(source)}-${index}`}>{sourceLabel(source)}</span>
              ))}
            </div>
          )}

          {riskFlags.length > 0 && (
            <div className="draft-risk-flags">
              {riskFlags.map((flag) => (
                <span key={flag}>{String(flag).replace(/_/g, " ")}</span>
              ))}
            </div>
          )}
        </details>
      </ProductCard>
    </section>
  )
}
