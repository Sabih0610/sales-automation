import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  ProductButton,
  ProductCard,
  ProductMoreMenuButton,
  ProductStatusBadge,
} from "../../components/product"
import { useToast } from "../../components/ToastProvider"
import { useSaveSequenceSettings, useSequenceSettings } from "../../queries"
import AddStepPopover from "./AddStepPopover.jsx"
import {
  backendSequenceToBuilderState,
  builderStepsToSequencePayload,
  createStepByType,
  defaultBuilderRules,
  templateToBuilderState,
} from "./sequenceAdapters"
import StepCard, { StartNode } from "./StepCard.jsx"
import StepEditorModal from "./StepEditorModal.jsx"
import "./sequenceBuilder.css"

function AddStepButton({ index, onAdd, open, setOpen }) {
  return (
    <div className="builder-add-step-wrap">
      <div className="builder-connector" />
      <button
        className="builder-add-step-button"
        onClick={() => setOpen(open ? null : index)}
        type="button"
      >
        <i className="ti ti-plus" aria-hidden="true" />
        Add step
      </button>

      {open && (
        <AddStepPopover
          onAdd={(type) => onAdd(index, type)}
          onClose={() => setOpen(null)}
        />
      )}

      <div className="builder-connector" />
    </div>
  )
}

function SummaryPanel({ steps }) {
  const emailCount = steps.filter((step) => step.type === "email").length
  const delayCount = steps.filter((step) => step.type === "delay").length
  const conditionCount = steps.filter((step) => step.type === "condition").length

  return (
    <ProductCard className="builder-side-panel">
      <h2>Sequence summary</h2>

      <div className="summary-grid">
        <div>
          <strong>{steps.length}</strong>
          <span>Total steps</span>
        </div>

        <div>
          <strong>{emailCount}</strong>
          <span>Email messages</span>
        </div>

        <div>
          <strong>{delayCount}</strong>
          <span>Delays</span>
        </div>

        <div>
          <strong>{conditionCount}</strong>
          <span>Conditions</span>
        </div>
      </div>
    </ProductCard>
  )
}

const renumberEmails = (items) => {
  let emailNumber = 0

  return items.map((step) => {
    if (step.type !== "email") return step

    emailNumber += 1

    return {
      ...step,
      number: emailNumber,
      title: `Email ${emailNumber}`,
    }
  })
}

export default function SequenceBuilder({
  campaignFilename = "",
  initialSequence,
  onBack,
}) {
  const navigate = useNavigate()
  const toast = useToast()
  const { data: sequenceData } = useSequenceSettings(campaignFilename)
  const saveSequence = useSaveSequenceSettings(campaignFilename)

  const initialBuilderState = useMemo(() => {
    if (campaignFilename && sequenceData) {
      return backendSequenceToBuilderState(sequenceData, initialSequence?.name)
    }

    return templateToBuilderState(initialSequence)
  }, [campaignFilename, initialSequence, sequenceData])

  const [sequenceName, setSequenceName] = useState(initialBuilderState.name)
  const [status, setStatus] = useState(initialBuilderState.status || "Draft")
  const [steps, setSteps] = useState(initialBuilderState.steps)
  const [rules, setRules] = useState(initialBuilderState.rules || defaultBuilderRules)
  const [openAddIndex, setOpenAddIndex] = useState(null)
  const [editingStepId, setEditingStepId] = useState("")
  const [sequenceMenuOpen, setSequenceMenuOpen] = useState(false)

  useEffect(() => {
    setSequenceName(initialBuilderState.name)
    setStatus(initialBuilderState.status || "Draft")
    setSteps(initialBuilderState.steps)
    setRules(initialBuilderState.rules || defaultBuilderRules)
  }, [initialBuilderState])

  const editingStep = steps.find((step) => step.id === editingStepId) || null
  const nextEmailNumber = steps.filter((step) => step.type === "email").length + 1
  const workingHoursLabel = rules.send_window_enabled
    ? `${rules.send_window_start || "09:00"} - ${rules.send_window_end || "17:00"}`
    : "Any time"
  const timezoneLabel = rules.timezone || "Asia/Karachi"
  const sendPaceLabel = `${Number(
    rules.rate_per_minute || rules.send_rate_per_minute || 30,
  )} emails/minute`

  const showToast = (title, detail = "", type = "success") => {
    if (toast) toast({ type, title, detail })
  }

  const buildSequencePayload = (mode) => {
    const payload = builderStepsToSequencePayload(steps, rules)

    return {
      ...payload,
      name: sequenceName,
      sequence_name: sequenceName,
      rules: {
        ...(payload.rules || {}),
        mode,
        skip_weekends: false,
      },
    }
  }

  const addStep = (afterIndex, type) => {
    const newStep = createStepByType(type, nextEmailNumber)

    setSteps((current) => {
      const insertAt = afterIndex + 1

      return renumberEmails([
        ...current.slice(0, insertAt),
        newStep,
        ...current.slice(insertAt),
      ])
    })

    setOpenAddIndex(null)
  }

  const saveStep = (updatedStep) => {
    setSteps((current) =>
      current.map((step) => (step.id === updatedStep.id ? updatedStep : step)),
    )

    setEditingStepId("")
    showToast("Step saved")
  }

  const deleteStep = (stepId) => {
    if (!window.confirm("Delete this step?")) return

    setSteps((current) => renumberEmails(current.filter((step) => step.id !== stepId)))
    setEditingStepId("")
    showToast("Step deleted", "", "info")
  }

  const duplicateStep = (stepId) => {
    setSteps((current) => {
      const index = current.findIndex((step) => step.id === stepId)
      if (index === -1) return current

      const original = current[index]
      const copy = {
        ...original,
        id: `${original.id}-copy-${Date.now()}`,
        title: original.type === "email" ? original.title : `${original.title || "Step"} copy`,
      }

      return renumberEmails([
        ...current.slice(0, index + 1),
        copy,
        ...current.slice(index + 1),
      ])
    })

    showToast("Step duplicated")
  }

  const renameSequence = () => {
    const nextName = window.prompt("Sequence name", sequenceName)
    if (nextName?.trim()) {
      setSequenceName(nextName.trim())
      showToast("Sequence renamed", "Save draft or publish to keep the change.")
    }
  }

  const resetSequence = () => {
    if (!window.confirm("Reset unsaved sequence changes?")) return

    setSequenceName(initialBuilderState.name)
    setStatus(initialBuilderState.status || "Draft")
    setSteps(initialBuilderState.steps)
    setRules(initialBuilderState.rules || defaultBuilderRules)
    setSequenceMenuOpen(false)
    showToast("Sequence reset", "", "info")
  }

  const editDeliverySetting = (field) => {
    if (field === "working_hours") {
      const useWindow = window.confirm(
        "Enable working-hours restriction? Press Cancel to keep sending any time.",
      )

      if (!useWindow) {
        setRules((current) => ({
          ...current,
          send_window_enabled: false,
          skip_weekends: false,
        }))
        showToast("Working hours disabled", "Emails can send any time.")
        return
      }

      const start = window.prompt("Start time, 24-hour format", rules.send_window_start || "09:00")
      if (!start) return

      const end = window.prompt("End time, 24-hour format", rules.send_window_end || "17:00")
      if (!end) return

      setRules((current) => ({
        ...current,
        send_window_enabled: true,
        send_window_start: start.trim(),
        send_window_end: end.trim(),
      }))
      showToast("Working hours updated", "Save draft or publish to apply.")
      return
    }

    if (field === "timezone") {
      const timezone = window.prompt("Timezone", rules.timezone || "Asia/Karachi")
      if (!timezone?.trim()) return

      setRules((current) => ({ ...current, timezone: timezone.trim() }))
      showToast("Timezone updated", "Save draft or publish to apply.")
      return
    }

    if (field === "send_pace") {
      const pace = window.prompt(
        "Emails per minute",
        String(rules.rate_per_minute || rules.send_rate_per_minute || 30),
      )
      const numericPace = Number(pace)

      if (!Number.isFinite(numericPace) || numericPace < 1) return

      setRules((current) => ({
        ...current,
        rate_per_minute: Math.min(Math.round(numericPace), 30),
        send_rate_per_minute: Math.min(Math.round(numericPace), 30),
      }))
      showToast("Send pace updated", "Save draft or publish to apply.")
    }
  }

  const saveDraft = async () => {
    const payload = buildSequencePayload("manual")

    if (!campaignFilename) {
      showToast(
        "Draft saved locally",
        "Connect a campaign filename to save this sequence to the backend.",
      )
      return
    }

    try {
      await saveSequence.mutateAsync(payload)
      setStatus("Draft")
      setRules(payload.rules)
      showToast("Draft saved")
    } catch (err) {
      showToast(
        "Save failed",
        err.response?.data?.detail || err.message || "Could not save sequence.",
        "error",
      )
    }
  }

  const publish = async () => {
    const payload = buildSequencePayload("auto")

    if (!campaignFilename) {
      showToast(
        "Publish unavailable",
        "Connect a campaign filename to publish this sequence.",
        "error",
      )
      return
    }

    try {
      await saveSequence.mutateAsync(payload)
      setStatus("Active")
      setRules(payload.rules)
      showToast(
        "Sequence published",
        "This campaign sequence is now active for approved scheduled sends.",
      )
    } catch (err) {
      showToast(
        "Publish failed",
        err.response?.data?.detail || err.message || "Could not publish sequence.",
        "error",
      )
    }
  }

  return (
    <>
      <section className="sequence-builder-page">
        <div className="sequence-builder-topbar">
          <ProductButton
            icon="ti-arrow-left"
            onClick={() => (onBack ? onBack() : navigate("/sequences"))}
          >
            Back
          </ProductButton>

          <div className="builder-title-group">
            <div className="builder-title-row">
              <h1>{sequenceName || "Enterprise SAP Intro Sequence"}</h1>

              <button
                aria-label="Edit sequence name"
                className="builder-title-edit"
                onClick={() => {
                  const nextName = window.prompt("Sequence name", sequenceName)
                  if (nextName) setSequenceName(nextName)
                }}
                type="button"
              >
                <i className="ti ti-pencil" aria-hidden="true" />
              </button>
            </div>

            <ProductStatusBadge status={status.toLowerCase()}>
              {status}
            </ProductStatusBadge>
          </div>

          <div className="builder-top-actions">
            <ProductButton
              disabled={saveSequence.isPending}
              icon="ti-device-floppy"
              onClick={saveDraft}
            >
              Save Draft
            </ProductButton>

            <ProductButton
              disabled={saveSequence.isPending}
              icon="ti-rocket"
              onClick={publish}
              variant="primary"
            >
              Publish
            </ProductButton>

            <div className="sequence-action-menu builder-sequence-menu">
              <button
                aria-expanded={sequenceMenuOpen}
                aria-label="Sequence actions"
                className="sequence-action-trigger"
                onClick={() => setSequenceMenuOpen((current) => !current)}
                type="button"
              >
                <i className="ti ti-dots-vertical" aria-hidden="true" />
              </button>

              {sequenceMenuOpen && (
                <div className="sequence-action-dropdown" role="menu">
                  <button
                    onClick={() => {
                      setSequenceMenuOpen(false)
                      renameSequence()
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <i className="ti ti-pencil" aria-hidden="true" />
                    Rename sequence
                  </button>

                  <button
                    onClick={() => {
                      setSequenceMenuOpen(false)
                      saveDraft()
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <i className="ti ti-device-floppy" aria-hidden="true" />
                    Save draft
                  </button>

                  <button
                    onClick={() => {
                      setSequenceMenuOpen(false)
                      publish()
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <i className="ti ti-rocket" aria-hidden="true" />
                    Publish sequence
                  </button>

                  <button
                    className="danger"
                    onClick={resetSequence}
                    role="menuitem"
                    type="button"
                  >
                    <i className="ti ti-rotate-clockwise" aria-hidden="true" />
                    Reset unsaved changes
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="sequence-builder-layout">
          <main className="sequence-flow-canvas">
            <div className="sequence-flow">
              <StartNode />

              <AddStepButton
                index={-1}
                onAdd={addStep}
                open={openAddIndex === -1}
                setOpen={setOpenAddIndex}
              />

              {steps.map((step, index) => (
                <div className="sequence-flow-item" key={step.id}>
                  <StepCard
                    onDelete={() => deleteStep(step.id)}
                    onDuplicate={() => duplicateStep(step.id)}
                    onEdit={() => setEditingStepId(step.id)}
                    step={step}
                  />

                  <AddStepButton
                    index={index}
                    onAdd={addStep}
                    open={openAddIndex === index}
                    setOpen={setOpenAddIndex}
                  />
                </div>
              ))}
            </div>
          </main>

          <aside className="builder-right-sidebar">
            <ProductCard className="builder-side-panel">
              <h2>Global exit rules</h2>
              <p>Contacts who meet any of these rules will exit this sequence.</p>

              <div className="side-rule-list">
                <div>
                  <strong>Replied</strong>
                  <span>Exits immediately</span>
                </div>

                <div>
                  <strong>Bounced</strong>
                  <span>Exits immediately</span>
                </div>

                <div>
                  <strong>Unsubscribed</strong>
                  <span>Exits immediately</span>
                </div>
              </div>
            </ProductCard>

            <ProductCard className="builder-side-panel">
              <h2>Delivery settings</h2>

              <div className="delivery-row">
                <span>Working hours</span>
                <strong>{workingHoursLabel}</strong>
                <button onClick={() => editDeliverySetting("working_hours")} type="button">
                  Edit
                </button>
              </div>

              <div className="delivery-row">
                <span>Timezone</span>
                <strong>{timezoneLabel}</strong>
                <button onClick={() => editDeliverySetting("timezone")} type="button">
                  Edit
                </button>
              </div>

              <div className="delivery-row">
                <span>Send pace</span>
                <strong>{sendPaceLabel}</strong>
                <button onClick={() => editDeliverySetting("send_pace")} type="button">
                  Edit
                </button>
              </div>
            </ProductCard>

            <SummaryPanel steps={steps} />
          </aside>
        </div>
      </section>

      <StepEditorModal
        onClose={() => setEditingStepId("")}
        onDelete={deleteStep}
        onSave={saveStep}
        open={Boolean(editingStep)}
        step={editingStep}
      />
    </>
  )
}