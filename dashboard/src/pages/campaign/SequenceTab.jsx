import { useEffect, useState } from "react"
import { friendlyMessage } from "../../api"
import { useSaveSequenceSettings, useSequenceSettings } from "../../queries"
import {
  LabeledInput,
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
      rules: { ...defaultRules, ...(sequenceData.rules || {}) },
      steps: sequenceData.steps || sequenceData.touches || [],
      touches: sequenceData.touches || sequenceData.steps || [],
    })
  }, [sequenceData])

  const steps = sequence.steps || sequence.touches || []
  const rules = { ...defaultRules, ...(sequence.rules || {}) }
  const mode = rules.mode === "auto" || rules.mode === "autopilot" ? "auto" : "manual"
  const detectedTimezone = getDetectedTimezone()
  const selectedTimezone = rules.timezone || detectedTimezone
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
      rules: { ...defaultRules, ...(current.rules || {}), [key]: value },
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
        const delayUnit = step.delay_unit || "days"
        return {
          touch_number: touchNumber,
          number: touchNumber,
          touch_name: sequenceStepName(touchNumber),
          name: sequenceStepName(touchNumber),
          is_active: step.is_active !== false,
          delay_days: delayUnit === "days" ? delayValue : 0,
          delay_value: delayValue,
          delay_unit: delayUnit,
          delay_type: step.delay_type || "calendar_days",
          send_time_mode: step.send_time_mode || "same_as_previous",
          fixed_send_time: step.fixed_send_time || "",
          subject_template: step.subject_template || "",
          email_body_template: step.email_body_template || "",
        }
      })
      const cleanedRules = {
        ...defaultRules,
        ...rules,
        mode: rules.mode === "auto" || rules.mode === "autopilot" ? "auto" : "manual",
        timezone: rules.timezone || getDetectedTimezone(),
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
          <h2>Email follow-up plan</h2>
          <p className="muted">
            Build the follow-up plan for this campaign. Follow-ups are scheduled from the exact time the previous email was sent.
          </p>
        </div>
        <button className="btn primary" onClick={handleSaveSequence} disabled={savingSequence}>
          <i className="ti ti-device-floppy" aria-hidden="true" />
          Save settings
        </button>
      </div>

      <div className="banner blue">
        <i className="ti ti-info-circle" aria-hidden="true" />
        <div>
          <div className="banner-title">How follow-ups are timed</div>
          <div className="banner-msg">
            If Email 1 is sent Thursday at 2:06 PM and Email 2 is set to 2 days later, Email 2 will be due Saturday at 2:06 PM. If weekend skipping is enabled, it moves to the next working day.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Sending choice</h2></div>
        <div className="card-body">
          <div className="form-group advanced-setting-row">
            <div className="form-label">Mode</div>
            <select
              className="form-input"
              value={mode}
              onChange={(e) => setSendingMode(e.target.value)}
            >
              <option value="manual">Manual</option>
              <option value="auto">Auto</option>
            </select>
            <div className="form-hint">
              Manual keeps follow-ups in Queue. Auto sends only drafts that were already approved.
            </div>
          </div>
          <div className="form-hint timezone-note">Timezone detected automatically: {selectedTimezone}</div>
          <details className="composer-details">
            <summary>Advanced settings</summary>
            <div className="form-group advanced-setting-row">
              <div className="form-label">Timezone override</div>
              <input
                className="form-input"
                value={rules.timezone || ""}
                onChange={(e) => updateRule("timezone", e.target.value)}
                placeholder={detectedTimezone}
              />
              <div className="form-hint">Leave blank to use the automatically detected value.</div>
            </div>
          </details>
        </div>
      </div>

      <div className="sequence-card-grid">
        {steps.map((step, idx) => {
          const emailNumber = Number(step.touch_number || step.number) || idx + 1
          const isFirstEmail = emailNumber === 1
          const sendTimeMode = step.send_time_mode || "same_as_previous"
          const delayValue = step.delay_value ?? step.delay_days ?? 0
          const timingText = sendTimeMode === "same_as_previous"
            ? "Same time as previous email"
            : "Advanced timing is applied"
          return (
            <div className="sequence-step-card" key={`${emailNumber}-${idx}`}>
              <div className="sequence-step-title">
                <h3>{sequenceStepLabel(emailNumber)}</h3>
                <label className="switch-row">
                  <input
                    type="checkbox"
                    checked={step.is_active !== false}
                    onChange={(e) => updateStep(idx, "is_active", e.target.checked)}
                  />
                  Active
                </label>
              </div>

              {isFirstEmail ? (
                <div className="banner green compact-banner">
                  <i className="ti ti-circle-check" aria-hidden="true" />
                  <div className="banner-msg">Sent when you approve and send the first draft.</div>
                </div>
              ) : (
                <>
                  <div className="simple-delay-row">
                    <span>Send after</span>
                    <input
                      className="form-input"
                      type="number"
                      min="0"
                      value={delayValue}
                      onChange={(e) => updateStep(idx, "delay_value", e.target.value)}
                    />
                    <span>days after Email {emailNumber - 1}</span>
                  </div>
                  <div className="form-hint">{timingText}</div>
                  <details className="composer-details sequence-advanced">
                    <summary>Advanced timing</summary>
                    <div className="grid2">
                      <div className="form-group">
                        <div className="form-label">Delay unit</div>
                        <select
                          className="form-input"
                          value={step.delay_unit || "days"}
                          onChange={(e) => updateStep(idx, "delay_unit", e.target.value)}
                        >
                          <option value="minutes">Minutes</option>
                          <option value="hours">Hours</option>
                          <option value="days">Days</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <div className="form-label">Weekend handling</div>
                        <select
                          className="form-input"
                          value={step.delay_type || "calendar_days"}
                          onChange={(e) => updateStep(idx, "delay_type", e.target.value)}
                        >
                          <option value="calendar_days">Count weekends</option>
                          <option value="business_days">Use weekdays only</option>
                        </select>
                      </div>
                      <div className="form-group">
                        <div className="form-label">Timing</div>
                        <select
                          className="form-input"
                          value={sendTimeMode}
                          onChange={(e) => updateStep(idx, "send_time_mode", e.target.value)}
                        >
                          <option value="same_as_previous">Same time as previous email</option>
                          <option value="fixed_time">Fixed time</option>
                          <option value="next_available_in_window">Next available in send window</option>
                        </select>
                      </div>
                      {sendTimeMode === "fixed_time" && (
                        <div className="form-group">
                          <div className="form-label">Fixed time</div>
                          <input
                            className="form-input"
                            type="time"
                            value={step.fixed_send_time || ""}
                            onChange={(e) => updateStep(idx, "fixed_send_time", e.target.value)}
                          />
                        </div>
                      )}
                    </div>
                  </details>
                </>
              )}

              <div className="form-group">
                <div className="form-label">Subject</div>
                <input
                  className="form-input"
                  value={step.subject_template || ""}
                  onChange={(e) => updateStep(idx, "subject_template", e.target.value)}
                />
              </div>
              <div className="form-group">
                <div className="form-label">Email body</div>
                <textarea
                  className="form-input textarea-lg"
                  value={step.email_body_template || ""}
                  onChange={(e) => updateStep(idx, "email_body_template", e.target.value)}
                />
              </div>
            </div>
          )
        })}
      </div>

      <div className="card">
        <div className="card-head"><h2>Sending safety</h2></div>
        <div className="card-body">
          <div className="rules-grid">
            {[
              ["stop_on_reply", "Stop follow-ups if lead replied"],
              ["stop_on_bounce", "Stop follow-ups if email bounced"],
              ["stop_on_unsubscribe", "Stop follow-ups if lead unsubscribed"],
              ["skip_no_email", "Skip leads without email"],
              ["skip_weekends", "Skip weekends"],
            ].map(([key, label]) => (
              <label className="check-row" key={key}>
                <input type="checkbox" checked={Boolean(rules[key])} onChange={(e) => updateRule(key, e.target.checked)} />
                {label}
              </label>
            ))}
            <LabeledInput label="Daily send limit" type="number" value={rules.daily_send_limit} onChange={(value) => updateRule("daily_send_limit", Number(value) || 1)} />
            <LabeledInput label="Send window start" value={rules.send_window_start} onChange={(value) => updateRule("send_window_start", value)} />
            <LabeledInput label="Send window end" value={rules.send_window_end} onChange={(value) => updateRule("send_window_end", value)} />
            <LabeledInput label="Delay between emails" type="number" value={rules.delay_between_sends_seconds} onChange={(value) => updateRule("delay_between_sends_seconds", Number(value) || 0)} />
          </div>
        </div>
      </div>
    </div>
  )
}
