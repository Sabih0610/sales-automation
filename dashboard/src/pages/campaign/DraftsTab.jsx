import { useEffect, useMemo, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { friendlyMessage } from "../../api"
import ConfirmSendModal from "../../components/ConfirmSendModal"
import useJobPolling from "../../hooks/useJobPolling"
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts"
import {
  useApproveDraft,
  useApproveSelected,
  useCampaignDrafts,
  useSendSelected,
  useSkipDraft,
  useUpdateDraft,
} from "../../queries"
import StatusPill from "./components/StatusPill.jsx"
import {
  draftBody,
  draftSubject,
  getDraftId,
  jobCompletionMessage,
  jobProgressMessage,
  terminalJobStatuses,
} from "./utils.jsx"

const STATUS_FILTERS = ["all", "draft", "approved", "scheduled", "sent", "failed", "skipped"]

const FLAG_LABELS = {
  template_leak: "Template variable not filled",
  missing_first_name: "First name missing",
  too_long: "Over word limit",
  no_personalisation: "No personalisation detected",
  risky_email: "Risky email",
}

const emptySet = () => new Set()

export default function DraftsTab({
  campaignName,
  filename,
  initialJobContext,
  onSelectTab,
  showNotice,
}) {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()

  const { data: drafts = [], isLoading } = useCampaignDrafts(filename, { limit: 1000 })
  const updateDraft = useUpdateDraft(filename)
  const approveDraft = useApproveDraft(filename)
  const approveSelected = useApproveSelected(filename)
  const skipDraft = useSkipDraft(filename)
  const sendSelected = useSendSelected(filename)

  const [statusFilter, setStatusFilter] = useState("all")
  const [touchFilter, setTouchFilter] = useState("")
  const [checkedIds, setCheckedIds] = useState(emptySet)
  const [editing, setEditing] = useState(false)
  const [editSubject, setEditSubject] = useState("")
  const [editBody, setEditBody] = useState("")
  const [pendingSendDraftIds, setPendingSendDraftIds] = useState(null)
  const [activeJobContext, setActiveJobContext] = useState(null)

  const viewedIdsRef = useRef(new Set())
  const progressToastIdRef = useRef(null)
  const initialJobIdRef = useRef("")
  const { job: activeJob, error: activeJobError } = useJobPolling(activeJobContext?.id || "")

  const filteredDrafts = useMemo(() => {
    return drafts.filter((draft) => {
      if (statusFilter !== "all" && draft.status !== statusFilter) return false
      if (touchFilter && String(draft.touch_number) !== String(touchFilter)) return false
      return true
    })
  }, [drafts, statusFilter, touchFilter])

  const selectedIdFromUrl = params.get("draft") || ""
  const currentDraft =
    filteredDrafts.find((draft) => getDraftId(draft) === selectedIdFromUrl) ||
    filteredDrafts[0] ||
    null

  const currentDraftId = getDraftId(currentDraft)

  const selectedApprovedIds = Array.from(checkedIds).filter((draftId) =>
    filteredDrafts.some((draft) => getDraftId(draft) === draftId && draft.status === "approved"),
  )

  const actionBusy =
    updateDraft.isPending ||
    approveDraft.isPending ||
    approveSelected.isPending ||
    skipDraft.isPending ||
    sendSelected.isPending ||
    Boolean(activeJobContext)

  useEffect(() => {
    if (!currentDraftId) return
    viewedIdsRef.current.add(currentDraftId)
  }, [currentDraftId])

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
    if (!initialJobContext?.id || initialJobIdRef.current === initialJobContext.id) return
    initialJobIdRef.current = initialJobContext.id
    progressToastIdRef.current = showNotice("Sending started", false, {
      title: "Sending started",
      detail: jobProgressMessage(
        { total: initialJobContext.total, done: 0, failed: 0, skipped: 0 },
        initialJobContext,
      ),
      type: "info",
      persist: true,
    })
    setActiveJobContext(initialJobContext)
  }, [initialJobContext, showNotice])

  useEffect(() => {
    if (activeJobError && activeJobContext) {
      const timer = window.setTimeout(() => showNotice(activeJobError, true), 0)
      return () => window.clearTimeout(timer)
    }
    return undefined
  }, [activeJobContext, activeJobError, showNotice])

  useEffect(() => {
    if (!activeJob || !activeJobContext || activeJob.id !== activeJobContext.id) return undefined

    if (!terminalJobStatuses.has(activeJob.status)) {
      const timer = window.setTimeout(() => {
        showNotice(jobProgressMessage(activeJob, activeJobContext), false, {
          progressId: progressToastIdRef.current,
          title: "Sending started",
          detail: jobProgressMessage(activeJob, activeJobContext),
          type: "info",
          persist: true,
        })
      }, 0)
      return () => window.clearTimeout(timer)
    }

    const isError = activeJob.status !== "done"
    showNotice(jobCompletionMessage(activeJob, activeJobContext), isError, {
      progressId: progressToastIdRef.current,
      actionLabel: "View drafts",
      onAction: () => onSelectTab("drafts"),
    })

    progressToastIdRef.current = null
    queryClient.invalidateQueries({ queryKey: ["campaign", filename] })

    if (activeJob.status === "done" && activeJobContext.clearDrafts) {
      setCheckedIds(emptySet())
    }

    setActiveJobContext(null)
    return undefined
  }, [activeJob, activeJobContext, filename, onSelectTab, queryClient, showNotice])

  const setSelectedDraft = (draftId) => {
    const next = new URLSearchParams(params)
    if (draftId) next.set("draft", draftId)
    else next.delete("draft")
    setParams(next, { replace: true })
    setEditing(false)
  }

  const moveSelection = (delta) => {
    if (!filteredDrafts.length) return

    const currentIndex = Math.max(
      0,
      filteredDrafts.findIndex((draft) => getDraftId(draft) === currentDraftId),
    )
    const nextIndex = Math.min(
      filteredDrafts.length - 1,
      Math.max(0, currentIndex + delta),
    )
    const nextDraft = filteredDrafts[nextIndex]

    if (nextDraft) setSelectedDraft(getDraftId(nextDraft))
  }

  const toggleChecked = (draftId) => {
    setCheckedIds((current) => {
      const next = new Set(current)
      if (next.has(draftId)) next.delete(draftId)
      else next.add(draftId)
      return next
    })
  }

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

  const approveCurrent = async () => {
    if (!currentDraft || currentDraft.status !== "draft") return

    try {
      if (editing) {
        await updateDraft.mutateAsync({
          draftId: currentDraftId,
          data: {
            subject: editSubject,
            body: editBody,
          },
        })
        setEditing(false)
      }

      await approveDraft.mutateAsync(currentDraftId)
      showNotice("Draft approved")
      moveSelection(1)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft approval failed", true)
    }
  }

  const skipCurrent = async () => {
    if (!currentDraft) return

    try {
      await skipDraft.mutateAsync({
        draftId: currentDraftId,
        reasonOrBody: { reason: "Skipped from triage review" },
      })
      showNotice("Draft skipped")
      moveSelection(1)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft skip failed", true)
    }
  }

  const approveChecked = async () => {
    const draftIds = Array.from(checkedIds)

    if (!draftIds.length) {
      showNotice("Select drafts first.", true)
      return
    }

    try {
      const res = await approveSelected.mutateAsync({ draft_ids: draftIds })
      showNotice(`${res.data.approved || 0} drafts approved`)
      setCheckedIds(emptySet())
    } catch (err) {
      showNotice(friendlyMessage(err) || "Bulk approval failed", true)
    }
  }

  const approveAllFiltered = async () => {
    const draftIds = filteredDrafts
      .filter((draft) => draft.status === "draft")
      .map((draft) => getDraftId(draft))

    if (!draftIds.length) {
      showNotice("No draft items to approve.", true)
      return
    }

    try {
      const res = await approveSelected.mutateAsync({ draft_ids: draftIds })
      showNotice(`${res.data.approved || 0} drafts approved`)
      setCheckedIds(emptySet())
    } catch (err) {
      showNotice(friendlyMessage(err) || "Bulk approval failed", true)
    }
  }

  const startJob = (res, context) => {
    const jobId = res.data?.job_id

    if (!jobId) {
      showNotice("Job was not created", true)
      return false
    }

    setActiveJobContext({ ...context, id: jobId })
    progressToastIdRef.current = showNotice("Sending started", false, {
      title: "Sending started",
      detail: jobProgressMessage(
        { total: context.total, done: 0, failed: 0, skipped: 0 },
        context,
      ),
      type: "info",
      persist: true,
    })
    return true
  }

  const sendApprovedDrafts = async (draftIds = selectedApprovedIds) => {
    if (!draftIds.length) {
      showNotice("Approve drafts before sending.", true)
      return
    }

    try {
      if (editing && currentDraft && draftIds.includes(currentDraftId)) {
        await updateDraft.mutateAsync({
          draftId: currentDraftId,
          data: {
            subject: editSubject,
            body: editBody,
          },
        })
        setEditing(false)
      }

      const res = await sendSelected.mutateAsync({ draft_ids: draftIds })
      startJob(res, {
        kind: "send",
        total: draftIds.length,
        progressLabel: "Sending",
        doneLabel: "Send",
        clearDrafts: true,
      })
    } catch (err) {
      showNotice(friendlyMessage(err) || "Send failed", true)
    }
  }

  const requestSendApproved = async () => {
    if (!selectedApprovedIds.length) {
      showNotice("Select approved drafts before sending.", true)
      return
    }

    if (selectedApprovedIds.length >= 5) {
      setPendingSendDraftIds(selectedApprovedIds)
      return
    }

    await sendApprovedDrafts(selectedApprovedIds)
  }

  const viewedTarget = Math.min(10, filteredDrafts.length)
  const bulkApproveDisabled = viewedIdsRef.current.size < viewedTarget
  const currentRiskFlags = Array.isArray(currentDraft?.risk_flags) ? currentDraft.risk_flags : []
  const currentKbSources = Array.isArray(currentDraft?.kb_sources) ? currentDraft.kb_sources : []

  useKeyboardShortcuts(
    {
      j: () => moveSelection(1),
      arrowdown: () => moveSelection(1),
      k: () => moveSelection(-1),
      arrowup: () => moveSelection(-1),
      a: approveCurrent,
      s: skipCurrent,
      e: startEdit,
      escape: () => setEditing(false),
    },
    !editing && !actionBusy,
  )

  return (
    <>
      <div className="draft-triage-page">
        <div className="draft-triage-toolbar">
          <div className="topbar-actions">
            {STATUS_FILTERS.map((status) => (
              <button
                className={`filter-pill ${statusFilter === status ? "active" : ""}`}
                key={status}
                onClick={() => {
                  setStatusFilter(status)
                  setSelectedDraft("")
                }}
                type="button"
              >
                {status}
              </button>
            ))}

            <select
              className="form-input compact"
              value={touchFilter}
              onChange={(event) => {
                setTouchFilter(event.target.value)
                setSelectedDraft("")
              }}
            >
              <option value="">All emails</option>
              {[1, 2, 3].map((touch) => (
                <option key={touch} value={touch}>
                  Email {touch}
                </option>
              ))}
            </select>
          </div>

          <div className="shortcut-legend">
            J/K move · A approve · S skip · E edit
          </div>
        </div>

        <div className="triage-layout">
          <aside className="triage-list card">
            <div className="triage-list-head">
              <div>
                <h2>Draft review</h2>
                <p>{filteredDrafts.length} drafts in this view</p>
              </div>
              <button
                className="btn sm"
                onClick={() => queryClient.invalidateQueries({ queryKey: ["campaign", filename, "drafts"] })}
                type="button"
              >
                Refresh
              </button>
            </div>

            <div className="triage-rows">
              {isLoading && <p className="empty-line">Loading drafts…</p>}

              {!isLoading && filteredDrafts.length === 0 && (
                <div className="triage-empty">
                  <p>No drafts match this view.</p>
                  <button
                    className="btn sm"
                    onClick={() => {
                      setStatusFilter("all")
                      setTouchFilter("")
                    }}
                    type="button"
                  >
                    Clear filters
                  </button>
                </div>
              )}

              {filteredDrafts.map((draft) => {
                const draftId = getDraftId(draft)
                const flags = Array.isArray(draft.risk_flags) ? draft.risk_flags : []

                return (
                  <button
                    className={`triage-row ${draftId === currentDraftId ? "selected" : ""}`}
                    key={draftId}
                    onClick={() => setSelectedDraft(draftId)}
                    type="button"
                  >
                    <span
                      className="triage-check"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        checked={checkedIds.has(draftId)}
                        onChange={() => toggleChecked(draftId)}
                        type="checkbox"
                      />
                    </span>

                    <span className="triage-row-main">
                      <strong>{draft.full_name || draft.email || "Unknown lead"}</strong>
                      <small>{draft.company || "—"} · {draft.title || "—"}</small>
                      <span>{draftSubject(draft) || "No subject"}</span>
                    </span>

                    <span className="touch-badge">E{draft.touch_number || 1}</span>

                    {flags.length > 0 && (
                      <span
                        className="risk-dot"
                        title={flags.map((flag) => FLAG_LABELS[flag] || flag).join(", ")}
                      >
                        ⚠
                      </span>
                    )}

                    <StatusPill value={draft.status} />
                  </button>
                )
              })}
            </div>

            <div className="bulk-bar">
              <button
                className="btn sm"
                disabled={checkedIds.size === 0 || actionBusy}
                onClick={approveChecked}
                type="button"
              >
                Approve selected ({checkedIds.size})
              </button>

              <button
                className="btn primary sm"
                disabled={selectedApprovedIds.length === 0 || actionBusy}
                onClick={requestSendApproved}
                type="button"
              >
                Send approved ({selectedApprovedIds.length})
              </button>

              <button
                className="btn sm"
                disabled={bulkApproveDisabled || actionBusy}
                onClick={approveAllFiltered}
                title={
                  bulkApproveDisabled
                    ? `View at least ${viewedTarget} drafts before approving all filtered`
                    : ""
                }
                type="button"
              >
                Approve all filtered
              </button>
            </div>
          </aside>

          <section className="triage-preview card">
            {!currentDraft && (
              <div className="triage-empty large">
                <h2>Select a draft</h2>
                <p>Choose a draft from the left to review, edit, approve, or skip.</p>
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
                    <strong>{currentDraft.full_name || "Unknown lead"} · {currentDraft.company || "—"}</strong>
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
                      {currentDraft.status === "draft" && (
                        <button
                          className="btn primary"
                          disabled={actionBusy}
                          onClick={approveCurrent}
                          type="button"
                        >
                          Approve (A)
                        </button>
                      )}
                      <button
                        className="btn"
                        disabled={actionBusy}
                        onClick={startEdit}
                        type="button"
                      >
                        Edit (E)
                      </button>
                      <button
                        className="btn danger"
                        disabled={actionBusy}
                        onClick={skipCurrent}
                        type="button"
                      >
                        Skip (S)
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

      {pendingSendDraftIds && (
        <ConfirmSendModal
          campaignName={campaignName}
          count={pendingSendDraftIds.length}
          onClose={() => setPendingSendDraftIds(null)}
          onConfirm={() => sendApprovedDrafts(pendingSendDraftIds)}
        />
      )}
    </>
  )
}