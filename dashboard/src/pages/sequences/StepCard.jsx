import { useEffect, useRef, useState } from "react"
import { ProductMoreMenuButton } from "../../components/product"

const previewLines = (body = "") =>
  body
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(" ")

function CardActions({ onDelete, onDuplicate, onEdit }) {
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

  const run = (event, action) => {
    event.preventDefault()
    event.stopPropagation()
    setOpen(false)
    action?.()
  }

  return (
    <div className="sequence-action-menu step-action-menu" ref={menuRef}>
      <button aria-label="Edit direction" onClick={(event) => run(event, onEdit)} type="button">
        <i className="ti ti-pencil" aria-hidden="true" />
      </button>

      <button
        aria-expanded={open}
        aria-label="Step actions"
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
          <button onClick={(event) => run(event, onEdit)} role="menuitem" type="button">
            <i className="ti ti-pencil" aria-hidden="true" />
            Edit direction
          </button>

          <button onClick={(event) => run(event, onDuplicate)} role="menuitem" type="button">
            <i className="ti ti-copy" aria-hidden="true" />
            Duplicate step
          </button>

          <button
            className="danger"
            onClick={(event) => run(event, onDelete)}
            role="menuitem"
            type="button"
          >
            <i className="ti ti-trash" aria-hidden="true" />
            Delete step
          </button>
        </div>
      )}
    </div>
  )
}


export function StartNode() {
  return (
    <div className="sequence-start-node">
      <span className="sequence-start-icon" aria-hidden="true" />
      <div>
        <strong>Start</strong>
        <span>Sequence start</span>
      </div>
    </div>
  )
}

export default function StepCard({ step, onDelete, onDuplicate, onEdit }) {
  if (step.type === "delay") {
    return (
      <article className="builder-step-card delay">
        <div className="builder-step-icon">
          <i className="ti ti-clock" aria-hidden="true" />
        </div>
        <div className="builder-step-copy">
          <h3>Delay</h3>
          <p>Wait for {step.waitDays || 3} days</p>
        </div>
        <CardActions onDelete={onDelete} onDuplicate={onDuplicate} onEdit={onEdit} />
      </article>
    )
  }

  if (step.type === "condition") {
    return (
      <article className="builder-step-card condition">
        <div className="builder-step-icon">
          <i className="ti ti-git-branch" aria-hidden="true" />
        </div>
        <div className="builder-step-copy">
          <h3>Condition</h3>
          <p>Contact exits if any of these happen:</p>
          <div className="condition-chip-row">
            {(step.conditions || ["Replied", "Bounced", "Unsubscribed"]).map((condition) => (
              <span key={condition}>{condition}</span>
            ))}
          </div>
        </div>
        <CardActions onDelete={onDelete} onDuplicate={onDuplicate} onEdit={onEdit} />
      </article>
    )
  }

  return (
    <article className="builder-step-card email">
      <div className="builder-email-number">{step.number}</div>
      <div className="builder-step-icon">
        <i className="ti ti-mail" aria-hidden="true" />
      </div>
      <div className="builder-step-copy">
        <h3>Email {step.number} <span>•</span> {step.timingLabel}</h3>
        <strong>{step.subject || "No subject direction yet"}</strong>
        <p>{previewLines(step.body) || "No AI writing instructions yet."}</p>
      </div>
      <CardActions onDelete={onDelete} onDuplicate={onDuplicate} onEdit={onEdit} />
    </article>
  )
}
