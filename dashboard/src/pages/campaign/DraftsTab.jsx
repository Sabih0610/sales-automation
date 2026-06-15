import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { friendlyMessage } from "../../api"
import {
  useApproveScheduleDrafts,
  useCampaignDrafts,
  useCampaignQueue,
  useDeleteDraft,
  useUpdateDraft,
} from "../../queries"
import StatusPill from "./components/StatusPill.jsx"
import {
  defaultQueue,
  draftBody,
  draftSubject,
  getDraftId,
} from "./utils.jsx"

const VIEW_FILTERS = [
  ["all", "All"],
  ["action_needed", "Action needed"],
]

const FLAG_LABELS = {
  template_leak: "Template variable not filled",
  missing_first_name: "First name missing",
  too_long: "Over word limit",
  no_personalisation: "No personalisation detected",
  risky_email: "Risky email",
}

const DEFAULT_RATE_PER_MINUTE =
  Math.min(Math.max(Number(import.meta.env.VITE_BULK_SEND_RATE_PER_MINUTE || 20) || 20, 1), 20)

const emptySet = () => new Set()

const isRemovedDraft = (draft) =>
  String(draft?.error_message || "").toLowerCase() === "removed"

const canScheduleDraft = (draft) => ["draft", "approved"].includes(draft?.status)

const formatDateTimeLocal = (date = new Date()) => {
  const pad = (value) => String(value).padStart(2, "0")
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + `T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function summarizeQueue(queueData, drafts) {
  const queue = { ...defaultQueue, ...(queueData || {}) }
  const items = Array.isArray(queue.items)
    ? queue.items
    : [
        ...(queue.due_today || []),
        ...(queue.scheduled || []),
        ...(queue.waiting || []),
      ]
  const statusCount = (values) =>
    items.filter((item) =>
      values.includes(String(item.status || item.draft_status || "").toLowerCase()),
    ).length

  return {
    queued:
      (queue.due_today?.length || 0) +
      (queue.waiting?.length || 0) +
      statusCount(["queued", "pending"]),
    scheduled: Math.max(
      queue.scheduled?.length || 0,
      drafts.filter((draft) => draft.status === "scheduled").length,
    ),
    sending: statusCount(["sending", "running", "in_progress"]),
    failed:
      (queue.failed?.length || 0) +
      drafts.filter((draft) => draft.status === "failed").length,
  }
}

export default function DraftsTab({ filename, showNotice }) {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()

  const { data: drafts = [], isLoading } = useCampaignDrafts(filename, { limit: 1000 })
  const { data: queueData = defaultQueue } = useCampaignQueue(filename)
  const updateDraft = useUpdateDraft(filename)
  const approveSchedule = useApproveScheduleDrafts(filename)
  const removeDraft = useDeleteDraft(filename)

  const [viewFilter, setViewFilter] = useState("all")
  const [checkedIds, setCheckedIds] = useState(emptySet)
  const [editing, setEditing] = useState(false)
  const [editSubject, setEditSubject] = useState("")
  const [editBody, setEditBody] = useState("")
  const [scheduleModal, setScheduleModal] = useState(null)
  const [startMode, setStartMode] = useState("now")
  const [startAt, setStartAt] = useState(formatDateTimeLocal())
  const [ratePerMinute, setRatePerMinute] = useState(DEFAULT_RATE_PER_MINUTE)

  const visibleDrafts = useMemo(() => {
    const liveDrafts = drafts.filter((draft) => !isRemovedDraft(draft))
    if (viewFilter === "action_needed") {
      return liveDrafts.filter(canScheduleDraft)
    }
    return liveDrafts
  }, [drafts, viewFilter])

  const selectedIdFromUrl = params.get("draft") || ""
  const currentDraft =
    visibleDrafts.find((draft) => getDraftId(draft) === selectedIdFromUrl) ||
    visibleDrafts[0] ||
    null
  const currentDraftId = getDraftId(currentDraft)

  const visibleSchedulableIds = useMemo(
    () =>
      visibleDrafts
        .filter(canScheduleDraft)
        .map((draft) => getDraftId(draft))
        .filter(Boolean),
    [visibleDrafts],
  )
  const visibleSchedulableIdSet = useMemo(
    () => new Set(visibleSchedulableIds),
    [visibleSchedulableIds],
  )
  const visibleSelectedIds = useMemo(
    () => Array.from(checkedIds).filter((draftId) => visibleSchedulableIdSet.has(draftId)),
    [checkedIds, visibleSchedulableIdSet],
  )
  const allVisibleSelected =
    visibleSchedulableIds.length > 0 &&
    visibleSchedulableIds.every((draftId) => checkedIds.has(draftId))
  const someVisibleSelected = visibleSelectedIds.length > 0

  const actionBusy =
    updateDraft.isPending ||
    approveSchedule.isPending ||
    removeDraft.isPending

  const queueStats = useMemo(
    () => summarizeQueue(queueData, drafts.filter((draft) => !isRemovedDraft(draft))),
    [drafts, queueData],
  )
  const currentRiskFlags = Array.isArray(currentDraft?.risk_flags) ? currentDraft.risk_flags : []
  const currentKbSources = Array.isArray(currentDraft?.kb_sources) ? currentDraft.kb_sources : []

  useEffect(() => {
    if (!currentDraft) {
      setEditing(false)
      setEditSubject("")
      setEditBody("")
      return
    }

    if (!editing) {
      setEditSubject(draftSubject(currentDraft))
      setEditBody(draftBody(currentDraft))
    }
  }, [currentDraftId, currentDraft, editing])

  useEffect(() => {
    setCheckedIds((current) => {
      const next = new Set(
        Array.from(current).filter((draftId) => visibleSchedulableIdSet.has(draftId)),
      )
      return next.size === current.size ? current : next
    })
  }, [visibleSchedulableIdSet])

  const setSelectedDraft = (draftId) => {
    const next = new URLSearchParams(params)
    if (draftId) next.set("draft", draftId)
    else next.delete("draft")
    setParams(next, { replace: true })
    setEditing(false)
  }

  const toggleChecked = (draftId) => {
    if (!visibleSchedulableIdSet.has(draftId)) return
    setCheckedIds((current) => {
      const next = new Set(current)
      if (next.has(draftId)) next.delete(draftId)
      else next.add(draftId)
      return next
    })
  }

  const toggleSelectAllVisible = () => {
    setCheckedIds((current) => {
      const next = new Set(current)
      if (allVisibleSelected) {
        visibleSchedulableIds.forEach((draftId) => next.delete(draftId))
      } else {
        visibleSchedulableIds.forEach((draftId) => next.add(draftId))
      }
      return next
    })
  }

  const clearSelection = () => setCheckedIds(emptySet())

  const startEdit = () => {
    if (!currentDraft) return
    setEditSubject(draftSubject(currentDraft))
    setEditBody(draftBody(currentDraft))
    setEditing(true)
  }

  const saveEdit = async () => {
    if (!currentDraft) return

    try {
      await updateDraft.mutateAsync({
        draftId: currentDraftId,
        data: {
          subject: editSubject,
          body: editBody,
        },
      })
      setEditing(false)
      showNotice("Draft saved")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft save failed", true)
    }
  }

  const removeDraftById = async (draft) => {
    const draftId = getDraftId(draft)
    if (!draftId) return
    if (!window.confirm("Remove this draft from the review list?")) return

    try {
      await removeDraft.mutateAsync(draftId)
      setCheckedIds((current) => {
        const next = new Set(current)
        next.delete(draftId)
        return next
      })
      if (draftId === currentDraftId) setSelectedDraft("")
      showNotice("Draft removed")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft remove failed", true)
    }
  }

  const openApproveSchedule = () => {
    const draftIds = visibleSelectedIds
    if (!draftIds.length) {
      showNotice("Select drafts to schedule first.", true)
      return
    }
    setStartMode("now")
    setStartAt(formatDateTimeLocal())
    setRatePerMinute(DEFAULT_RATE_PER_MINUTE)
    setScheduleModal({ draftIds })
  }

  const submitApproveSchedule = async () => {
    if (!scheduleModal?.draftIds?.length) return
    const cleanRate = Math.min(Math.max(Number(ratePerMinute) || DEFAULT_RATE_PER_MINUTE, 1), 20)

    if (startMode === "later" && !startAt) {
      showNotice("Choose a start time.", true)
      return
    }

    try {
      if (editing && currentDraft && scheduleModal.draftIds.includes(currentDraftId)) {
        await updateDraft.mutateAsync({
          draftId: currentDraftId,
          data: {
            subject: editSubject,
            body: editBody,
          },
        })
        setEditing(false)
      }

      const res = await approveSchedule.mutateAsync({
        draft_ids: scheduleModal.draftIds,
        start_mode: startMode,
        start_at: startMode === "later" ? startAt : "",
        rate_per_minute: cleanRate,
      })
      const count = res.data?.scheduled || 0
      showNotice(`Scheduled ${count} emails. Sending will start automatically.`)
      queryClient.invalidateQueries({ queryKey: ["campaign", filename] })
      setCheckedIds(emptySet())
      setScheduleModal(null)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Scheduling failed", true)
    }
  }

  return (
    <>
      <div className="draft-triage-page">
        <div className="draft-triage-toolbar">
          <div className="topbar-actions">
            {VIEW_FILTERS.map(([value, label]) => (
              <button
                className={`filter-pill ${viewFilter === value ? "active" : ""}`}
                key={value}
                onClick={() => {
                  setViewFilter(value)
                  setSelectedDraft("")
                }}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>

          <button
            className="btn sm"
            onClick={() => queryClient.invalidateQueries({ queryKey: ["campaign", filename, "drafts"] })}
            type="button"
          >
            Refresh
          </button>
        </div>

        <div className="draft-queue-summary">
          {[
            ["Queued", queueStats.queued],
            ["Scheduled", queueStats.scheduled],
            ["Sending", queueStats.sending],
            ["Failed", queueStats.failed],
          ].map(([label, value]) => (
            <div className="draft-queue-stat" key={label}>
              <strong>{value}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>

        <div className="triage-layout">
          <aside className="triage-list card">
            <div className="triage-list-head">
              <div>
                <h2>Draft review</h2>
                <p>
                  {visibleDrafts.length} drafts
                  {someVisibleSelected ? ` - ${visibleSelectedIds.length} selected` : ""}
                </p>
              </div>
            </div>

            <div className="selection-bar">
              <label className="select-visible-control">
                <input
                  checked={allVisibleSelected}
                  disabled={!visibleSchedulableIds.length || actionBusy}
                  onChange={toggleSelectAllVisible}
                  type="checkbox"
                />
                <span>Select all visible</span>
              </label>

              {someVisibleSelected && (
                <button
                  className="btn sm"
                  disabled={actionBusy}
                  onClick={clearSelection}
                  type="button"
                >
                  Clear selection
                </button>
              )}
            </div>

            <div className="triage-rows">
              {isLoading && <p className="empty-line">Loading drafts...</p>}

              {!isLoading && visibleDrafts.length === 0 && (
                <div className="triage-empty">
                  <p>No drafts in this view.</p>
                  {viewFilter !== "all" && (
                    <button
                      className="btn sm"
                      onClick={() => setViewFilter("all")}
                      type="button"
                    >
                      Show all
                    </button>
                  )}
                </div>
              )}

              {visibleDrafts.map((draft) => {
                const draftId = getDraftId(draft)
                const flags = Array.isArray(draft.risk_flags) ? draft.risk_flags : []
                const selectable = canScheduleDraft(draft)

                return (
                  <div
                    className={`triage-row ${draftId === currentDraftId ? "selected" : ""}`}
                    key={draftId}
                    onClick={() => setSelectedDraft(draftId)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault()
                        setSelectedDraft(draftId)
                      }
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    <span
                      className="triage-check"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        checked={checkedIds.has(draftId)}
                        disabled={!selectable || actionBusy}
                        onChange={() => toggleChecked(draftId)}
                        type="checkbox"
                      />
                    </span>

                    <span className="triage-row-main">
                      <strong>{draft.full_name || draft.email || "Unknown lead"}</strong>
                      <small>{draft.company || "-"} - {draft.title || "-"}</small>
                      <span>{draftSubject(draft) || "No subject"}</span>
                    </span>

                    <span className="touch-badge">E{draft.touch_number || 1}</span>

                    {flags.length > 0 && (
                      <span
                        className="risk-dot"
                        title={flags.map((flag) => FLAG_LABELS[flag] || flag).join(", ")}
                      >
                        !
                      </span>
                    )}

                    <StatusPill value={draft.status} />

                    <button
                      aria-label="Remove draft"
                      className="draft-remove-button"
                      disabled={actionBusy}
                      onClick={(event) => {
                        event.stopPropagation()
                        removeDraftById(draft)
                      }}
                      type="button"
                    >
                      <i className="ti ti-x" aria-hidden="true" />
                    </button>
                  </div>
                )
              })}
            </div>

            <div className="bulk-bar simplified">
              <button
                className="btn primary"
                disabled={visibleSelectedIds.length === 0 || actionBusy}
                onClick={openApproveSchedule}
                type="button"
              >
                Approve &amp; Schedule ({visibleSelectedIds.length})
              </button>
            </div>
          </aside>

          <section className="triage-preview card">
            {!currentDraft && (
              <div className="triage-empty large">
                <h2>Select a draft</h2>
                <p>Choose a draft from the list to review or edit.</p>
              </div>
            )}

            {currentDraft && (
              <>
                <div className="email-meta">
                  <div>
                    <span>From</span>
                    <strong>Royal Cyber</strong>
                  </div>
                  <div>
                    <span>To</span>
                    <strong>{currentDraft.email || "No email"}</strong>
                  </div>
                  <div>
                    <span>Lead</span>
                    <strong>{currentDraft.full_name || "Unknown lead"} - {currentDraft.company || "-"}</strong>
                  </div>
                </div>

                <div className="email-subject-row">
                  {editing ? (
                    <input
                      className="form-input"
                      onChange={(event) => setEditSubject(event.target.value)}
                      value={editSubject}
                    />
                  ) : (
                    <h2>{draftSubject(currentDraft) || "No subject"}</h2>
                  )}
                  <StatusPill value={currentDraft.status} />
                </div>

                {currentRiskFlags.length > 0 && (
                  <div className="risk-row">
                    {currentRiskFlags.map((flag) => (
                      <span className="pill-amber" key={flag}>
                        {FLAG_LABELS[flag] || flag}
                      </span>
                    ))}
                  </div>
                )}

                <div className="email-body-card">
                  {editing ? (
                    <textarea
                      className="composer-textarea triage-textarea"
                      onChange={(event) => setEditBody(event.target.value)}
                      rows={18}
                      value={editBody}
                    />
                  ) : (
                    <pre className="email-body-preview">{draftBody(currentDraft) || "No body"}</pre>
                  )}
                </div>

                <div className="preview-actions">
                  {editing ? (
                    <>
                      <button
                        className="btn primary"
                        disabled={actionBusy}
                        onClick={saveEdit}
                        type="button"
                      >
                        Save
                      </button>
                      <button
                        className="btn"
                        disabled={actionBusy}
                        onClick={() => setEditing(false)}
                        type="button"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="btn"
                        disabled={actionBusy}
                        onClick={startEdit}
                        type="button"
                      >
                        Edit
                      </button>
                      <button
                        className="btn danger"
                        disabled={actionBusy}
                        onClick={() => removeDraftById(currentDraft)}
                        type="button"
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>

                <details className="sources-panel">
                  <summary>Personalisation sources</summary>
                  <p>{currentDraft.research_summary || "No research summary recorded."}</p>

                  {currentKbSources.length > 0 ? (
                    <div className="sources-chips">
                      {currentKbSources.map((source) => (
                        <span className="chip" key={source}>
                          {source}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="empty-line">No knowledge-base sources recorded.</p>
                  )}
                </details>
              </>
            )}
          </section>
        </div>
      </div>

      {scheduleModal && (
        <div className="modal-backdrop" onClick={() => setScheduleModal(null)}>
          <div className="modal-card approve-schedule-modal" onClick={(event) => event.stopPropagation()}>
            <h3>Approve &amp; schedule {scheduleModal.draftIds.length} emails</h3>
            <p>These emails will be queued and sent automatically through Microsoft Graph.</p>

            <div className="schedule-modal-form">
              <div className="form-group">
                <div className="form-label">Start time</div>
                <div className="segmented-radio-row">
                  <label>
                    <input
                      checked={startMode === "now"}
                      onChange={() => setStartMode("now")}
                      type="radio"
                    />
                    Now
                  </label>
                  <label>
                    <input
                      checked={startMode === "later"}
                      onChange={() => setStartMode("later")}
                      type="radio"
                    />
                    Later
                  </label>
                </div>
              </div>

              {startMode === "later" && (
                <div className="form-group">
                  <div className="form-label">Date and time</div>
                  <input
                    className="form-input"
                    onChange={(event) => setStartAt(event.target.value)}
                    type="datetime-local"
                    value={startAt}
                  />
                </div>
              )}

              <div className="form-group">
                <div className="form-label">Rate</div>
                <div className="rate-input-row">
                  <input
                    className="form-input"
                    max="20"
                    min="1"
                    onChange={(event) => setRatePerMinute(event.target.value)}
                    type="number"
                    value={ratePerMinute}
                  />
                  <span>emails per minute</span>
                </div>
              </div>
            </div>

            <div className="modal-actions">
              <button
                className="btn"
                disabled={actionBusy}
                onClick={() => setScheduleModal(null)}
                type="button"
              >
                Cancel
              </button>
              <button
                className="btn primary"
                disabled={actionBusy || (startMode === "later" && !startAt)}
                onClick={submitApproveSchedule}
                type="button"
              >
                Approve &amp; Schedule {scheduleModal.draftIds.length} emails
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
