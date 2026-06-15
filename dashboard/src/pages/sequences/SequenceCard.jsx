import { useEffect, useRef, useState } from "react"
import { ProductBadge, ProductStatusBadge } from "../../components/product"

const formatMetric = (value) =>
  typeof value === "number" ? new Intl.NumberFormat().format(value) : value

function SequenceActionMenu({ actions, label }) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) return

    const close = (event) => {
      if (!menuRef.current?.contains(event.target)) setOpen(false)
    }

    const closeOnEscape = (event) => {
      if (event.key === "Escape") setOpen(false)
    }

    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", closeOnEscape)

    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  return (
    <div
      className="sequence-action-menu"
      onClick={(event) => event.stopPropagation()}
      ref={menuRef}
    >
      <button
        aria-expanded={open}
        aria-label={label}
        className="sequence-action-trigger"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          setOpen((current) => !current)
        }}
        type="button"
      >
        <i className="ti ti-dots-vertical" aria-hidden="true" />
      </button>

      {open && (
        <div className="sequence-action-dropdown" role="menu">
          {actions.map((action) => (
            <button
              className={action.danger ? "danger" : ""}
              key={action.label}
              onClick={(event) => {
                event.preventDefault()
                event.stopPropagation()
                setOpen(false)
                action.onSelect?.()
              }}
              role="menuitem"
              type="button"
            >
              <i className={`ti ${action.icon}`} aria-hidden="true" />
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SequenceCard({ sequence, onArchive, onDuplicate, onOpen }) {
  const sequenceMetrics = sequence.metrics || {}

  const metrics = [
    ["Enrolled", sequenceMetrics.enrolled ?? 0],
    ["Active", sequenceMetrics.active ?? 0],
    ["Scheduled", sequenceMetrics.scheduled ?? 0],
    ["Sent", sequenceMetrics.sent ?? 0],
    ["Reply rate", sequenceMetrics.replyRate ?? "0%"],
  ]

  const handleKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onOpen?.(sequence)
    }
  }

  return (
    <article
      className="sequence-card"
      onClick={() => onOpen?.(sequence)}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
    >
      <div className={`sequence-card-icon ${sequence.iconTone || "primary"}`}>
        <i className={`ti ${sequence.icon}`} aria-hidden="true" />
      </div>

      <div className="sequence-card-main">
        <div className="sequence-card-title-row">
          <div className="sequence-title-block">
            <div className="sequence-name-row">
              <h2>{sequence.name}</h2>
              <button
                aria-label={sequence.favorite ? "Remove from favorites" : "Add to favorites"}
                className={`sequence-favorite${sequence.favorite ? " active" : ""}`}
                onClick={(event) => event.stopPropagation()}
                type="button"
              >
                <i className="ti ti-star-filled" aria-hidden="true" />
              </button>
            </div>
            <p>{sequence.description}</p>
          </div>
          <ProductBadge tone="info">Multi-step</ProductBadge>
        </div>

        <div className="sequence-metric-row">
          {metrics.map(([label, value]) => (
            <div className="sequence-metric" key={label}>
              <strong>{formatMetric(value)}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="sequence-card-side">
        <div className="sequence-status-row">
          <ProductStatusBadge status={sequence.status.toLowerCase()}>
            {sequence.status}
          </ProductStatusBadge>

          <SequenceActionMenu
            actions={[
              {
                icon: "ti-pencil",
                label: "Edit sequence",
                onSelect: () => onOpen?.(sequence),
              },
              {
                icon: "ti-copy",
                label: "Duplicate sequence",
                onSelect: () => onDuplicate?.(sequence),
              },
              {
                danger: !sequence.archived,
                icon: sequence.archived ? "ti-archive-off" : "ti-archive",
                label: sequence.archived ? "Restore sequence" : "Archive sequence",
                onSelect: () => onArchive?.(sequence),
              },
            ]}
            label={`${sequence.name} actions`}
          />
        </div>

        <div className="sequence-edit-meta">
          <span>Last edited {sequence.lastEdited}</span>
          <strong>{sequence.editedBy}</strong>
        </div>
      </div>
    </article>
  )
}
