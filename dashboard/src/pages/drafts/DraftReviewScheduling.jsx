import { useEffect, useMemo, useState } from "react"
import { useParams } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { friendlyMessage } from "../../api"
import { ProductCard } from "../../components/product"
import { useToast } from "../../components/ToastProvider"
import {
  useApproveScheduleDrafts,
  useCampaignDrafts,
  useCampaigns,
  useDeleteDraft,
  useJob,
  useJobs,
  useUpdateDraft,
} from "../../queries"
import ProductButton from "../../components/product/ProductButton.jsx"
import ApproveScheduleModal from "./ApproveScheduleModal.jsx"
import DraftListRow from "./DraftListRow.jsx"
import DraftPreview from "./DraftPreview.jsx"
import "./draftScheduling.css"

const emptySet = () => new Set()

const activeJobStatuses = new Set(["queued", "running"])

function jobPayload(job) {
  const raw = job?.payload || job?.payload_json || {}
  if (typeof raw !== "string") return raw || {}
  try {
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

const selectableStatuses = new Set(["draft", "approved"])

const decodeFilename = (value = "") => {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

const draftId = (draft) => draft?.draft_id || draft?.id || ""
const draftSubject = (draft) => draft?.subject || draft?.email_subject || ""
const draftBody = (draft) => draft?.body || draft?.email_body || ""
const draftStatus = (draft) => String(draft?.status || "draft").toLowerCase()

const cleanDraftReason = (value = "") =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\s+/g, " ")
    .trim()

const draftReason = (draft) =>
  cleanDraftReason(
    draft?.error_message ||
      draft?.error ||
      draft?.failure_reason ||
      draft?.status_reason ||
      draft?.skip_reason ||
      draft?.reason ||
      "",
  )

const draftNeedsReason = (draft) =>
  ["failed", "skipped", "deferred"].includes(draftStatus(draft))

const canApproveSchedule = (draft) => selectableStatuses.has(draftStatus(draft))

const isRemovedDraft = (draft) =>
  String(draft?.error_message || "").toLowerCase() === "removed" ||
  draftStatus(draft) === "deleted"

const countDrafts = (drafts) => {
  const counts = {
    draft: 0,
    scheduled: 0,
    sending: 0,
    sent: 0,
    failed: 0,
    total: drafts.length,
  }

  drafts.forEach((draft) => {
    const status = draftStatus(draft)

    if (status === "approved") {
      counts.draft += 1
    } else if (Object.prototype.hasOwnProperty.call(counts, status)) {
      counts[status] += 1
    }
  })

  return counts
}

export default function DraftReviewScheduling() {
  const { filename: encodedFilename } = useParams()
  const filename = decodeFilename(encodedFilename || "")
  const queryClient = useQueryClient()
  const toast = useToast()
  const [draftJobContext, setDraftJobContext] = useState(null)

  const { data: campaigns = [] } = useCampaigns()
  const { data: drafts = [], isLoading } = useCampaignDrafts(filename, { limit: 1000 })
  const { data: recentJobs = [] } = useJobs(50)

  const trackedDraftJobId = draftJobContext?.id || ""
  const { data: trackedDraftJob } = useJob(trackedDraftJobId)

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(`draftJobContext:${filename}`)
      setDraftJobContext(raw ? JSON.parse(raw) : null)
    } catch {
      setDraftJobContext(null)
    }
  }, [filename])
  const approveSchedule = useApproveScheduleDrafts(filename)
  const removeDraft = useDeleteDraft(filename)
  const updateDraft = useUpdateDraft(filename)

  const [search, setSearch] = useState("")
  const [selectedIds, setSelectedIds] = useState(emptySet)
  const [previewId, setPreviewId] = useState("")
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editSubject, setEditSubject] = useState("")
  const [editBody, setEditBody] = useState("")

  const campaign = useMemo(
    () => campaigns.find((item) => item.filename === filename) || null,
    [campaigns, filename],
  )

  const campaignName = campaign?.name || "SAP Migration for Enterprise"

  const liveDrafts = useMemo(
    () => drafts.filter((draft) => !isRemovedDraft(draft)),
    [drafts],
  )

  const visibleDrafts = useMemo(() => {
    const term = search.trim().toLowerCase()

    if (!term) return liveDrafts

    return liveDrafts.filter((draft) =>
      [
        draft.full_name,
        draft.email,
        draft.title,
        draft.company,
        draftSubject(draft),
        draftStatus(draft),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(term),
    )
  }, [liveDrafts, search])

  const selectableVisibleIds = useMemo(
    () => visibleDrafts.filter(canApproveSchedule).map(draftId).filter(Boolean),
    [visibleDrafts],
  )

  const selectableVisibleKey = selectableVisibleIds.join("|")

  const selectedVisibleIds = useMemo(
    () => selectableVisibleIds.filter((id) => selectedIds.has(id)),
    [selectableVisibleIds, selectedIds],
  )

  const allVisibleSelected =
    selectableVisibleIds.length > 0 &&
    selectableVisibleIds.every((id) => selectedIds.has(id))

  const activeGenerateJob = useMemo(
    () =>
      recentJobs.find((job) => {
        const status = String(job?.status || "").toLowerCase()
        if (!activeJobStatuses.has(status)) return false

        const payload = jobPayload(job)
        const campaignFilename =
          payload.campaign_filename || payload.campaign || payload.campaign_key || ""

        return job.type === "generate_drafts" && campaignFilename === filename
      }),
    [recentJobs, filename],
  )

  const trackedDraftJobStatus = String(trackedDraftJob?.status || "").toLowerCase()
  const draftGenerationActive =
    Boolean(draftJobContext?.id && !trackedDraftJob) ||
    ["queued", "running"].includes(trackedDraftJobStatus) ||
    Boolean(activeGenerateJob)
  const draftGenerationDone = Number(trackedDraftJob?.done ?? activeGenerateJob?.done ?? 0)
  const draftGenerationTotal = Number(
    trackedDraftJob?.total ||
      draftJobContext?.total ||
      activeGenerateJob?.total ||
      jobPayload(activeGenerateJob)?.lead_ids?.length ||
      0,
  )

  useEffect(() => {
    if (!trackedDraftJob || ["queued", "running"].includes(trackedDraftJobStatus)) {
      return
    }

    try {
      window.sessionStorage.removeItem(`draftJobContext:${filename}`)
    } catch {
      // Ignore storage failures.
    }

    setDraftJobContext(null)
    queryClient.invalidateQueries({ queryKey: ["campaign", filename, "drafts"] })
    queryClient.invalidateQueries({ queryKey: ["campaign", filename, "overview"] })
  }, [trackedDraftJob, trackedDraftJobStatus, filename, queryClient])

  useEffect(() => {
    if (!draftGenerationActive) return undefined

    const timer = window.setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ["campaign", filename, "drafts"] })
      queryClient.invalidateQueries({ queryKey: ["campaign", filename, "overview"] })
    }, 2500)

    return () => window.clearInterval(timer)
  }, [draftGenerationActive, filename, queryClient])

  const busy =
    draftGenerationActive ||
    approveSchedule.isPending ||
    removeDraft.isPending ||
    updateDraft.isPending

  const currentDraft = useMemo(
    () =>
      visibleDrafts.find((draft) => draftId(draft) === previewId) ||
      visibleDrafts[0] ||
      null,
    [previewId, visibleDrafts],
  )

  const currentDraftId = draftId(currentDraft)
  const counts = useMemo(() => countDrafts(liveDrafts), [liveDrafts])

  const currentDraftReason =
    currentDraft && draftNeedsReason(currentDraft) ? draftReason(currentDraft) : ""

  useEffect(() => {
    setSelectedIds((current) => {
      const allowed = new Set(selectableVisibleIds)
      const next = new Set(Array.from(current).filter((id) => allowed.has(id)))

      if (
        next.size === current.size &&
        Array.from(next).every((id) => current.has(id))
      ) {
        return current
      }

      return next
    })
  }, [selectableVisibleKey])

  useEffect(() => {
    if (!currentDraft) {
      setPreviewId("")
      setEditing(false)
      setEditSubject("")
      setEditBody("")
      return
    }

    if (previewId !== currentDraftId) {
      setPreviewId(currentDraftId)
    }
  }, [currentDraft, currentDraftId, previewId])

  useEffect(() => {
    if (!currentDraft || editing) return

    setEditSubject(draftSubject(currentDraft))
    setEditBody(draftBody(currentDraft))
  }, [currentDraft, currentDraftId, editing])

  const notify = (type, title, detail) => {
    toast?.({ type, title, detail })
  }

  const toggleSelectAll = () => {
    setSelectedIds((current) => {
      const next = new Set(current)

      if (allVisibleSelected) {
        selectableVisibleIds.forEach((id) => next.delete(id))
      } else {
        selectableVisibleIds.forEach((id) => next.add(id))
      }

      return next
    })
  }

  const toggleDraft = (id) => {
    if (!selectableVisibleIds.includes(id)) return

    setSelectedIds((current) => {
      const next = new Set(current)

      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }

      return next
    })
  }

  const removeDraftById = async (draft) => {
    const id = draftId(draft)

    if (!id) return
    if (!window.confirm("Remove this draft?")) return

    try {
      await removeDraft.mutateAsync(id)

      setSelectedIds((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })

      if (id === previewId) {
        setPreviewId("")
      }

      notify("success", "Draft removed", "The draft was removed from review.")
    } catch (err) {
      notify("error", "Remove failed", friendlyMessage(err) || "Could not remove draft.")
    }
  }

  const removeSelectedDrafts = async () => {
    const ids = selectedVisibleIds.filter(Boolean)

    if (!ids.length) {
      notify("error", "Select drafts first", "Choose at least one draft to remove.")
      return
    }

    const confirmed = window.confirm(
      `Remove ${ids.length} selected draft${ids.length === 1 ? "" : "s"}? This cannot be undone.`,
    )
    if (!confirmed) return

    try {
      await Promise.all(ids.map((id) => removeDraft.mutateAsync(id)))

      setSelectedIds(emptySet())

      if (ids.includes(previewId)) {
        setPreviewId("")
      }

      queryClient.invalidateQueries({ queryKey: ["campaign", filename] })

      notify(
        "success",
        "Drafts removed",
        `Removed ${ids.length} draft${ids.length === 1 ? "" : "s"} from review.`,
      )
    } catch (err) {
      queryClient.invalidateQueries({ queryKey: ["campaign", filename] })
      notify("error", "Remove failed", friendlyMessage(err) || "Could not remove selected drafts.")
    }
  }

  const saveCurrentDraft = async ({ quiet = false } = {}) => {
    if (!currentDraftId) return false

    try {
      await updateDraft.mutateAsync({
        data: {
          body: editBody,
          subject: editSubject,
        },
        draftId: currentDraftId,
      })

      setEditing(false)

      if (!quiet) {
        notify("success", "Draft saved", "The email draft has been updated.")
      }

      return true
    } catch (err) {
      notify("error", "Save failed", friendlyMessage(err) || "Could not save draft.")
      return false
    }
  }

  const openScheduleModal = () => {
    if (!selectedVisibleIds.length) {
      notify("error", "Select drafts first", "Choose at least one draft to approve and schedule.")
      return
    }

    setModalOpen(true)
  }

  const submitApproveSchedule = async (settings) => {
    if (!selectedVisibleIds.length) return

    try {
      if (editing && selectedVisibleIds.includes(currentDraftId)) {
        const saved = await saveCurrentDraft({ quiet: true })
        if (!saved) return
      }

      const response = await approveSchedule.mutateAsync({
        draft_ids: selectedVisibleIds,
        rate_per_minute: settings.rate_per_minute,
        start_at: settings.start_at || "",
        start_mode: settings.start_mode,
      })

      const result = response?.data || {}
      const scheduled = Number(result.scheduled ?? selectedVisibleIds.length)
      const skippedInvalid = Number(result.skipped_invalid ?? 0)
      const skippedNotEligible = Number(result.skipped_not_eligible ?? 0)
      const jobStarted = Boolean(result.job_id)

      const messageParts = [
        `Scheduled ${scheduled} email${scheduled === 1 ? "" : "s"}.`,
      ]

      if (jobStarted) {
        messageParts.push("Sending started for the due batch.")
      } else if (settings.start_mode === "later") {
        messageParts.push("Sending will start at the scheduled time.")
      } else {
        messageParts.push("Sending will start automatically.")
      }

      if (skippedInvalid > 0) {
        messageParts.push(`${skippedInvalid} invalid email${skippedInvalid === 1 ? "" : "s"} skipped.`)
      }

      if (skippedNotEligible > 0) {
        messageParts.push(`${skippedNotEligible} not eligible skipped.`)
      }

      setModalOpen(false)
      setSelectedIds(emptySet())
      queryClient.invalidateQueries({ queryKey: ["campaign", filename] })

      notify(
        scheduled > 0 ? "success" : "error",
        scheduled > 0 ? "Scheduled" : "Nothing scheduled",
        messageParts.join(" "),
      )
    } catch (err) {
      notify("error", "Scheduling failed", friendlyMessage(err) || "Could not schedule drafts.")
    }
  }

  const summaryCards = [
    ["Draft", counts.draft],
    ["Scheduled", counts.scheduled],
    ["Sending", counts.sending],
    ["Sent", counts.sent],
    ["Failed", counts.failed],
    ["Total", counts.total],
  ]

  return (
    <>
      <div className="draft-scheduling-page">
        <header className="draft-scheduling-title-row">
          <div>
            <h1>Draft Review &amp; Scheduling</h1>
            <p>Review AI-generated drafts before scheduling for {campaignName}.</p>
          </div>

          <input
            className="search-input"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search drafts, contacts, or companies..."
            value={search}
          />
          {draftGenerationActive && (
            <div
              aria-label="Draft generation in progress"
              aria-live="polite"
              className="draft-generation-compact"
              title="Generating drafts"
            >
              <span className="draft-generation-spinner" aria-hidden="true" />
              <span className="draft-generation-track" aria-hidden="true">
                <span
                  style={{
                    width: `${
                      draftGenerationTotal > 0
                        ? Math.min(100, Math.round((draftGenerationDone / draftGenerationTotal) * 100))
                        : 18
                    }%`,
                  }}
                />
              </span>
              <span className="draft-generation-count">
                {draftGenerationTotal > 0
                  ? `${draftGenerationDone}/${draftGenerationTotal}`
                  : "..."}
              </span>
            </div>
          )}
        </header>



        <div className="draft-review-layout">
          <ProductCard className="draft-list-panel" padding="md">
            <div className="draft-list-head">
              <label className="draft-select-all">
                <input
                  checked={allVisibleSelected}
                  disabled={selectableVisibleIds.length === 0 || busy}
                  onChange={toggleSelectAll}
                  type="checkbox"
                />
                <span>Select all</span>
              </label>

              <span className="draft-selected-count">
                {selectedVisibleIds.length} selected
              </span>

              <ProductButton
                disabled={selectedVisibleIds.length === 0 || busy}
                onClick={removeSelectedDrafts}
                size="sm"
                variant="ghost"
              >
                Remove Selected ({selectedVisibleIds.length})
              </ProductButton>

              <ProductButton
                disabled={selectedVisibleIds.length === 0 || busy}
                onClick={openScheduleModal}
                size="sm"
                variant="primary"
              >
                Approve &amp; Schedule ({selectedVisibleIds.length})
              </ProductButton>
            </div>

            <div className="draft-list-status-line">
              <span>{visibleDrafts.length} visible</span>
              <span>{selectableVisibleIds.length} needs action</span>
            </div>

            <div className="draft-review-list" aria-label="Drafts">
              {isLoading && <div className="draft-list-empty">Loading drafts...</div>}

              {!isLoading && visibleDrafts.length === 0 && (
                <div className="draft-list-empty">
                  <strong>No drafts found</strong>
                  <span>Generate drafts from the campaign leads page to start review.</span>
                </div>
              )}

              {!isLoading &&
                visibleDrafts.map((draft) => {
                  const id = draftId(draft)
                  const selectable = canApproveSchedule(draft)
                  const reason = draftNeedsReason(draft) ? draftReason(draft) : ""

                  return (
                  <div className="draft-row-wrapper" key={id}>
                  <DraftListRow
                    checked={selectedIds.has(id)}
                    disabled={busy}
                    draft={draft}
                    onRemove={() => removeDraftById(draft)}
                    onSelect={() => {
                      setPreviewId(id)
                      setEditing(false)
                    }}
                    onToggle={() => toggleDraft(id)}
                    selectable={selectable}
                    selected={id === currentDraftId}
                  />

                  {reason && (
                    <div className="draft-row-reason" title={reason}>
                      Reason: {reason}
                    </div>
                  )}
                  </div>
                  )
                })}
            </div>
          </ProductCard>

          <div className="draft-preview-column">
            {currentDraftReason && (
              <div className="draft-preview-reason">
                <strong>Failure reason</strong>
                <span>{currentDraftReason}</span>
              </div>
            )}

          <DraftPreview
            draft={currentDraft}
            editBody={editBody}
            editing={editing}
            editSubject={editSubject}
            onCancelEdit={() => {
              setEditing(false)
              setEditSubject(draftSubject(currentDraft))
              setEditBody(draftBody(currentDraft))
            }}
            onEdit={() => {
              setEditSubject(draftSubject(currentDraft))
              setEditBody(draftBody(currentDraft))
              setEditing(true)
            }}
            onEditBody={setEditBody}
            onEditSubject={setEditSubject}
            onSave={saveCurrentDraft}
            saving={updateDraft.isPending}
            senderEmail={campaign?.sender_email || ""}
            senderName={campaign?.sender_name || "RC Sales"}
          />
          </div>
        </div>

        <section className="draft-summary-strip" aria-label="Draft status counts">
          {summaryCards.map(([label, value]) => (
            <ProductCard className="draft-summary-card" key={label} padding="sm">
              <span>{label}</span>
              <strong>{value}</strong>
            </ProductCard>
          ))}
        </section>
      </div>

      <ApproveScheduleModal
        count={selectedVisibleIds.length}
        loading={approveSchedule.isPending}
        onClose={() => setModalOpen(false)}
        onSubmit={submitApproveSchedule}
        open={modalOpen}
      />
    </>
  )
}