import { ProductStatusBadge } from "../../components/product"

const statusLabel = (status = "draft") =>
  String(status || "draft")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())

const displayStatus = (status = "draft") => {
  const normalized = String(status || "draft").toLowerCase()
  return normalized === "approved" ? "draft" : normalized
}

const initialsFor = (name = "", fallback = "") => {
  const parts = String(name || fallback || "RC")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
  return (parts[0] || "RC").slice(0, 2).toUpperCase()
}

export default function DraftListRow({
  checked,
  disabled = false,
  draft,
  reason = "",
  onRemove,
  onSelect,
  onToggle,
  selectable = true,
  selected = false,
}) {
  const leadName = draft.full_name || draft.email || "Unknown lead"
  const title = draft.title || "Lead"
  const company = draft.company || "Company unknown"

  const visibleStatus = displayStatus(draft.status)

  return (
    <div
      className={`draft-review-row${selected ? " selected" : ""}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onSelect?.()
        }
      }}
      role="button"
      tabIndex={0}
    >
      <span className="draft-review-check" onClick={(event) => event.stopPropagation()}>
        <input
          aria-label={`Select ${leadName}`}
          checked={checked}
          disabled={!selectable || disabled}
          onChange={onToggle}
          type="checkbox"
        />
      </span>

      <span className="draft-review-avatar">{initialsFor(leadName, draft.company)}</span>

      <span className="draft-review-row-main">
        <strong>{leadName}</strong>
        <small>
          {title} <span aria-hidden="true">&middot;</span> {company}
        </small>
      </span>

      <ProductStatusBadge status={visibleStatus}>
        {statusLabel(visibleStatus)}
      </ProductStatusBadge>

      <span
        className="draft-review-remove"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onRemove?.()
        }}
        role="button"
        tabIndex={-1}
        title="Remove draft"
      >
        <i className="ti ti-x" aria-hidden="true" />
      </span>
    </div>
  )
}

export { displayStatus, initialsFor, statusLabel }
