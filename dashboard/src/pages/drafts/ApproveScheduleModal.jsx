import { useEffect, useMemo, useState } from "react"
import { ProductButton, ProductModal } from "../../components/product"

const clampRate = (value) => Math.min(Math.max(Number(value) || 20, 1), 20)

const today = () => {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, "0")
  return {
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
  }
}

export default function ApproveScheduleModal({
  count = 0,
  loading = false,
  onClose,
  onSubmit,
  open,
}) {
  const [startMode, setStartMode] = useState("now")
  const [startDate, setStartDate] = useState(today().date)
  const [startTime, setStartTime] = useState(today().time)
  const [ratePerMinute, setRatePerMinute] = useState(20)

  useEffect(() => {
    if (!open) return
    const next = today()
    setStartMode("now")
    setStartDate(next.date)
    setStartTime(next.time)
    setRatePerMinute(20)
  }, [open])

  const cleanRate = clampRate(ratePerMinute)
  const estimatedMinutes = useMemo(
    () => Math.max(1, Math.ceil((Number(count) || 0) / cleanRate)),
    [cleanRate, count],
  )
  const laterInvalid = startMode === "later" && (!startDate || !startTime)

  const submit = () => {
    if (laterInvalid || loading) return
    onSubmit?.({
      rate_per_minute: cleanRate,
      start_at: startMode === "later" ? `${startDate}T${startTime}` : undefined,
      start_mode: startMode,
    })
  }

  return (
    <ProductModal
      className="approve-schedule-modal"
      footer={(
        <>
          <ProductButton disabled={loading} onClick={onClose} variant="secondary">
            Cancel
          </ProductButton>
          <ProductButton disabled={loading || laterInvalid || count === 0} onClick={submit} variant="primary">
            Approve &amp; Schedule
          </ProductButton>
        </>
      )}
      onClose={loading ? undefined : onClose}
      open={open}
      subtitle="Choose when the approved emails should enter the sending queue."
      title={`Approve & Schedule ${count} email${count === 1 ? "" : "s"}`}
    >
      <div className="approve-schedule-form">
        <fieldset>
          <legend>When would you like to start?</legend>
          <label className={`draft-radio-card${startMode === "now" ? " active" : ""}`}>
            <input
              checked={startMode === "now"}
              onChange={() => setStartMode("now")}
              type="radio"
            />
            <span>
              <strong>Start now</strong>
              <small>Queue the first batch immediately.</small>
            </span>
          </label>
          <label className={`draft-radio-card${startMode === "later" ? " active" : ""}`}>
            <input
              checked={startMode === "later"}
              onChange={() => setStartMode("later")}
              type="radio"
            />
            <span>
              <strong>Start later</strong>
              <small>Choose a date and time for the first batch.</small>
            </span>
          </label>
        </fieldset>

        {startMode === "later" && (
          <div className="draft-date-grid">
            <label>
              <span>Date</span>
              <input
                onChange={(event) => setStartDate(event.target.value)}
                type="date"
                value={startDate}
              />
            </label>
            <label>
              <span>Time</span>
              <input
                onChange={(event) => setStartTime(event.target.value)}
                type="time"
                value={startTime}
              />
            </label>
          </div>
        )}

        <label className="draft-pace-field">
          <span>Send pace</span>
          <select
            onChange={(event) => setRatePerMinute(Number(event.target.value))}
            value={cleanRate}
          >
            {[5, 10, 15, 20].map((rate) => (
              <option key={rate} value={rate}>{rate} emails per minute</option>
            ))}
          </select>
        </label>

        <div className="draft-modal-info">
          <i className="ti ti-info-circle" aria-hidden="true" />
          <span>Emails will be queued and sent automatically through Microsoft Graph.</span>
        </div>

        <div className="draft-estimate">
          <span>Estimated completion</span>
          <strong>about {estimatedMinutes} minute{estimatedMinutes === 1 ? "" : "s"}</strong>
        </div>
      </div>
    </ProductModal>
  )
}
