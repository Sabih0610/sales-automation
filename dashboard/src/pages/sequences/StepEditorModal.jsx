import { useEffect, useState } from "react"
import { ProductButton, ProductModal } from "../../components/product"

export default function StepEditorModal({
  onClose,
  onDelete,
  onSave,
  open,
  step,
}) {
  const [draft, setDraft] = useState(step || null)

  useEffect(() => {
    setDraft(step || null)
  }, [step])

  if (!step || !draft) return null

  const isEmail = step.type === "email"
  const isDelay = step.type === "delay"
  const isCondition = step.type === "condition"
  const title = isEmail ? "Edit AI email direction" : isDelay ? "Edit delay" : "Edit condition"

  return (
    <ProductModal
      className="step-editor-modal"
      footer={
        <>
          <ProductButton
            className="step-delete-button"
            icon="ti-trash"
            onClick={() => onDelete(step.id)}
            variant="ghost"
          >
            Delete {isDelay ? "Delay" : isCondition ? "Condition" : "Direction"}
          </ProductButton>
          <ProductButton onClick={onClose}>Cancel</ProductButton>
          <ProductButton
            icon="ti-device-floppy"
            onClick={() => onSave(draft)}
            variant="primary"
          >
            {isDelay ? "Save Delay" : isCondition ? "Save Condition" : "Save Direction"}
          </ProductButton>
        </>
      }
      onClose={onClose}
      open={open}
      subtitle={isEmail ? "Guide the AI. Do not write the final email copy here." : "Update this sequence step."}
      title={title}
    >
      {isEmail && (
        <div className="step-editor-form">
          <label>
            <span>Step name</span>
            <input
              value={draft.title || ""}
              onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
            />
          </label>
          <label>
            <span>Subject direction</span>
            <input
              value={draft.subject || ""}
              onChange={(event) => setDraft((current) => ({ ...current, subject: event.target.value }))}
            />
          </label>
          <label>
            <span>AI writing instructions</span>
            <textarea
              rows={8}
              value={draft.body || ""}
              onChange={(event) => setDraft((current) => ({ ...current, body: event.target.value }))}
            />
          </label>
        </div>
      )}

      {isDelay && (
        <div className="step-editor-form compact">
          <label>
            <span>Wait for</span>
            <div className="delay-input-row">
              <input
                min="1"
                type="number"
                value={draft.waitDays || 3}
                onChange={(event) => setDraft((current) => ({
                  ...current,
                  waitDays: Number(event.target.value) || 1,
                }))}
              />
              <strong>days</strong>
            </div>
          </label>
        </div>
      )}

      {isCondition && (
        <div className="step-editor-form">
          <p className="condition-editor-copy">
            Contacts exit this sequence when any selected rule is met.
          </p>
          <div className="condition-editor-grid">
            {(draft.conditions || []).map((condition) => (
              <label key={condition}>
                <input checked readOnly type="checkbox" />
                <span>{condition}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </ProductModal>
  )
}
