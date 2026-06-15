import { useEffect, useState } from "react"
import { friendlyMessage } from "../../api"
import { useSaveSequenceSettings, useSequenceSettings } from "../../queries"
import {
  defaultRules,
  getDetectedTimezone,
  sequenceStepLabel,
  sequenceStepName,
} from "./utils.jsx"

export default function SequenceTab({ filename, showNotice }) {
  const { data: sequenceData } = useSequenceSettings(filename)
  const saveSequence = useSaveSequenceSettings(filename)
  const [sequence, setSequence] = useState({ steps: [], touches: [], rules: defaultRules })

  useEffect(() => {
    if (!sequenceData) return
    setSequence({
      ...sequenceData,
      rules: { ...defaultRules, ...(sequenceData.rules || {}), skip_weekends: false },
      steps: sequenceData.steps || sequenceData.touches || [],
      touches: sequenceData.touches || sequenceData.steps || [],
    })
  }, [sequenceData])

  const steps = sequence.steps || sequence.touches || []
  const rules = { ...defaultRules, ...(sequence.rules || {}), skip_weekends: false }
  const mode = rules.mode === "auto" || rules.mode === "autopilot" ? "auto" : "manual"
  const savingSequence = saveSequence.isPending

  const updateStep = (idx, key, value) => {
    setSequence((current) => {
      const currentSteps = current.steps || current.touches || []
      const nextSteps = currentSteps.map((step, index) =>
        index === idx ? { ...step, [key]: value } : step,
      )
      return { ...current, steps: nextSteps, touches: nextSteps }
    })
  }

  const updateRule = (key, value) => {
    setSequence((current) => ({
      ...current,
      rules: { ...defaultRules, ...(current.rules || {}), skip_weekends: false, [key]: value },
    }))
  }

  const setSendingMode = (nextMode) => {
    updateRule("mode", nextMode)
    updateRule("require_approval_for_followups", nextMode !== "auto")
  }

  const handleSaveSequence = async () => {
    try {
      const cleanedSteps = steps.map((step) => {
        const touchNumber = Number(step.touch_number || step.number) || 1
        const delayValue = Number(step.delay_value ?? step.delay_days ?? 0) || 0
        return {
          touch_number: touchNumber,
          number: touchNumber,
          touch_name: sequenceStepName(touchNumber),
          name: sequenceStepName(touchNumber),
          is_active: step.is_active !== false,
          delay_days: delayValue,
          delay_value: delayValue,
          delay_unit: "days",
          delay_type: "calendar_days",
          send_time_mode: "same_as_previous",
          fixed_send_time: "",
          subject_template: step.subject_template || "",
          email_body_template: step.email_body_template || "",
        }
      })
      const cleanedRules = {
        ...defaultRules,
        ...rules,
        mode: rules.mode === "auto" || rules.mode === "autopilot" ? "auto" : "manual",
        timezone: rules.timezone || getDetectedTimezone(),
        skip_weekends: false,
      }
      await saveSequence.mutateAsync({ steps: cleanedSteps, touches: cleanedSteps, rules: cleanedRules })
      showNotice("Sequence settings saved")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Sequence save failed", true)
    }
  }

  return (
    <div className="sequence-layout">
      <div className="sequence-header-actions">
        <div>
          <h2>Email sequence</h2>
          <p className="muted">Set the follow-up emails for this campaign.</p>
        </div>
        <button className="btn primary" onClick={handleSaveSequence} disabled={savingSequence}>
          <i className="ti ti-device-floppy" aria-hidden="true" />
          Save settings
        </button>
      </div>

      <div className="card">
        <div className="card-head"><h2>Mode</h2></div>
        <div className="card-body">
          <div className="form-group advanced-setting-row">
            <div className="form-label">Sending mode</div>
            <select
              className="form-input"
              value={mode}
              onChange={(event) => setSendingMode(event.target.value)}
            >
              <option value="manual">Manual</option>
              <option value="auto">Auto</option>
            </select>
          </div>
        </div>
      </div>

      <div className="sequence-card-grid">
        {steps.map((step, idx) => {
          const emailNumber = Number(step.touch_number || step.number) || idx + 1
          const isFirstEmail = emailNumber === 1
          const delayValue = step.delay_value ?? step.delay_days ?? 0

          return (
            <div className="sequence-step-card" key={`${emailNumber}-${idx}`}>
              <div className="sequence-step-title">
                <h3>{sequenceStepLabel(emailNumber)}</h3>
                <label className="switch-row">
                  <input
                    type="checkbox"
                    checked={step.is_active !== false}
                    onChange={(event) => updateStep(idx, "is_active", event.target.checked)}
                  />
                  Active
                </label>
              </div>

              {!isFirstEmail && (
                <div className="simple-delay-row">
                  <span>Send after</span>
                  <input
                    className="form-input"
                    min="0"
                    onChange={(event) => updateStep(idx, "delay_value", event.target.value)}
                    type="number"
                    value={delayValue}
                  />
                  <span>days after Email {emailNumber - 1}</span>
                </div>
              )}

              <div className="form-group">
                <div className="form-label">Subject</div>
                <input
                  className="form-input"
                  value={step.subject_template || ""}
                  onChange={(event) => updateStep(idx, "subject_template", event.target.value)}
                />
              </div>
              <div className="form-group">
                <div className="form-label">Email body</div>
                <textarea
                  className="form-input textarea-lg"
                  value={step.email_body_template || ""}
                  onChange={(event) => updateStep(idx, "email_body_template", event.target.value)}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
