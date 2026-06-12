import { useEffect, useMemo, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { friendlyMessage } from "../../api"
import ConfirmSendModal from "../../components/ConfirmSendModal"
import useJobPolling from "../../hooks/useJobPolling"
import { useCampaignQueue, useGenerateDue, useSendCampaignQueueSelected, useSendPolicyStatus } from "../../queries"
import { relativeTime } from "../../utils/relativeTime"
import SequenceDots from "./components/SequenceDots.jsx"
import StatusPill from "./components/StatusPill.jsx"
import {
  defaultQueue,
  fmtDate,
  getDraftId,
  jobCompletionMessage,
  jobProgressMessage,
  terminalJobStatuses,
} from "./utils.jsx"

const SECTIONS = ["Due now", "Today", "Tomorrow", "This week", "Later"]

function sectionOf(iso) {
  if (!iso) return "Later"

  const due = new Date(iso)
  if (Number.isNaN(due.getTime())) return "Later"

  const now = new Date()
  if (due <= now) return "Due now"

  const endToday = new Date(now)
  endToday.setHours(23, 59, 59, 999)
  if (due <= endToday) return "Today"

  const endTomorrow = new Date(endToday)
  endTomorrow.setDate(endTomorrow.getDate() + 1)
  if (due <= endTomorrow) return "Tomorrow"

  const endWeek = new Date(endToday)
  endWeek.setDate(endWeek.getDate() + 6)
  if (due <= endWeek) return "This week"

  return "Later"
}

function flattenQueue(queue) {
  if (Array.isArray(queue.items)) return queue.items

  return [
    ...(queue.due_today || []),
    ...(queue.scheduled || []),
    ...(queue.waiting || []),
  ]
}

function flattenHistory(queue) {
  if (Array.isArray(queue.history)) return queue.history

  return [
    ...(queue.sent || []),
    ...(queue.failed || []),
    ...(queue.skipped || []),
  ]
}

function queueLeadName(item) {
  return item.lead_name || item.full_name || item.name || "Unknown lead"
}

function queueCompanyLine(item) {
  const company = item.company || "—"
  const email = item.email || item.lead_email || "No email"
  return `${company} · ${email}`
}

function getQueueDraftStatus(item) {
  return item.draft_status || item.status || "none"
}

function QueueAction({
  actionBusy,
  filename,
  item,
  onGenerate,
  onSendToggle,
  selectedDraftIds,
}) {
  const navigate = useNavigate()
  const draftStatus = getQueueDraftStatus(item)
  const draftId = getDraftId(item)
  const section = sectionOf(item.next_due_at || item.next_touch_due_at)

  if (draftStatus === "none") {
    if (section !== "Due now") {
      return <span className="queue-action-muted">Waiting</span>
    }

    return (
      <button
        className="btn sm"
        disabled={actionBusy}
        onClick={() => onGenerate(item)}
        type="button"
      >
        Generate
      </button>
    )
  }

  if (draftStatus === "draft") {
    return (
      <button
        className="btn sm"
        onClick={() => navigate(`/campaigns/${filename}/drafts?draft=${draftId}`)}
        type="button"
      >
        Review
      </button>
    )
  }

  if (draftStatus === "approved") {
    return (
      <label className="send-check">
        <input
          checked={selectedDraftIds.includes(draftId)}
          disabled={!draftId || actionBusy}
          onChange={() => onSendToggle(draftId)}
          type="checkbox"
        />
        Send
      </label>
    )
  }

  return <StatusPill value={draftStatus} />
}

export default function QueueTab({ campaignName, filename, onSelectTab, showNotice }) {
  const queryClient = useQueryClient()
  const { data: queueData = defaultQueue, isLoading } = useCampaignQueue(filename)
  const { data: sendPolicy } = useSendPolicyStatus()
  const generateDue = useGenerateDue(filename)
  const sendQueueSelected = useSendCampaignQueueSelected(filename)

  const [selectedDraftIds, setSelectedDraftIds] = useState([])
  const [activeJobContext, setActiveJobContext] = useState(null)
  const [pendingSendDraftIds, setPendingSendDraftIds] = useState(null)
  const [quickConfirmCount, setQuickConfirmCount] = useState(0)
  const [progressToastId, setProgressToastId] = useState(null)

  const { job: activeJob, error: activeJobError } = useJobPolling(activeJobContext?.id || "")

  const queue = {
    ...defaultQueue,
    items: [],
    history: [],
    ...queueData,
  }

  const items = useMemo(() => flattenQueue(queue), [queueData])
  const history = useMemo(() => flattenHistory(queue), [queueData])

  const grouped = useMemo(() => {
    const groups = Object.fromEntries(SECTIONS.map((section) => [section, []]))

    for (const item of items) {
      const dueAt = item.next_due_at || item.next_touch_due_at || item.scheduled_for
      groups[sectionOf(dueAt)].push(item)
    }

    return groups
  }, [items])

  const approvedDueIds = items
    .filter((item) => {
      const draftStatus = getQueueDraftStatus(item)
      const dueAt = item.next_due_at || item.next_touch_due_at || item.scheduled_for
      return draftStatus === "approved" && sectionOf(dueAt) === "Due now" && getDraftId(item)
    })
    .map((item) => getDraftId(item))

  const selectedApprovedIds = selectedDraftIds.filter((draftId) =>
    items.some((item) => getDraftId(item) === draftId && getQueueDraftStatus(item) === "approved"),
  )

  const sentToday = history.filter((item) => {
    const sentAt = item.sent_at || item.previous_sent_at
    if (!sentAt) return false
    return new Date(sentAt).toDateString() === new Date().toDateString()
  }).length

  const policyWindow = sendPolicy?.window || {}
  const queuePolicyLine = sendPolicy
    ? `Today: ${sendPolicy.sent_today ?? 0}/${sendPolicy.todays_cap ?? 0} sent · window ${policyWindow.start || "--:--"}–${policyWindow.end || "--:--"} ${policyWindow.open_now ? "· open now" : "· closed"}`
    : ""

  const actionBusy =
    generateDue.isPending ||
    sendQueueSelected.isPending ||
    Boolean(activeJobContext)

  const toggleDraft = (draftId) => {
    if (!draftId) return

    setSelectedDraftIds((current) =>
      current.includes(draftId)
        ? current.filter((id) => id !== draftId)
        : [...current, draftId],
    )
  }

  const startJob = (res, context) => {
    const jobId = res.data?.job_id

    if (!jobId) {
      showNotice("Job was not created", true)
      return false
    }

    setActiveJobContext({ ...context, id: jobId })

    const toastId = showNotice("Queue job started", false, {
      title: "Queue job started",
      detail: jobProgressMessage(
        { total: context.total, done: 0, failed: 0, skipped: 0 },
        context,
      ),
      type: "info",
      persist: true,
    })

    setProgressToastId(toastId)
    return true
  }

  useEffect(() => {
    if (activeJobError && activeJobContext) {
      const timer = window.setTimeout(() => showNotice(activeJobError, true), 0)
      return () => window.clearTimeout(timer)
    }

    return undefined
  }, [activeJobContext, activeJobError, showNotice])

  useEffect(() => {
    if (!activeJob || !activeJobContext || activeJob.id !== activeJobContext.id) {
      return undefined
    }

    if (!terminalJobStatuses.has(activeJob.status)) {
      const timer = window.setTimeout(() => {
        showNotice(jobProgressMessage(activeJob, activeJobContext), false, {
          progressId: progressToastId,
          title: "Queue job running",
          detail: jobProgressMessage(activeJob, activeJobContext),
          type: "info",
          persist: true,
        })
      }, 0)

      return () => window.clearTimeout(timer)
    }

    const isError = activeJob.status !== "done"

    showNotice(jobCompletionMessage(activeJob, activeJobContext), isError, {
      progressId: progressToastId,
      actionLabel: "View drafts",
      onAction: () => onSelectTab("drafts"),
    })

    setProgressToastId(null)
    queryClient.invalidateQueries({ queryKey: ["campaign", filename] })

    if (activeJob.status === "done") {
      if (activeJobContext.clearQueue) setSelectedDraftIds([])
      if (activeJobContext.nextTab) onSelectTab(activeJobContext.nextTab)
    }

    setActiveJobContext(null)
    return undefined
  }, [activeJob, activeJobContext, filename, onSelectTab, progressToastId, queryClient, showNotice])

  const handleRefreshQueue = () => {
    queryClient.invalidateQueries({ queryKey: ["campaign", filename, "queue"] })
    showNotice("Queue refreshed")
  }

  const handleGenerateItem = async (item) => {
    try {
      const leadId = item.lead_id || item.id
      const touchNumber = item.touch_number || 1

      const res = await generateDue.mutateAsync({
        lead_ids: leadId ? [leadId] : [],
        touch_number: touchNumber,
      })

      startJob(res, {
        kind: "generate",
        total: 1,
        progressLabel: "Generating",
        doneLabel: "Due draft generation",
        nextTab: "drafts",
      })
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft generation failed", true)
    }
  }

  const handleGenerateAllDue = async () => {
    try {
      const res = await generateDue.mutateAsync({})

      startJob(res, {
        kind: "generate",
        total: grouped["Due now"].filter((item) => getQueueDraftStatus(item) === "none").length,
        progressLabel: "Generating",
        doneLabel: "Due draft generation",
        nextTab: "drafts",
      })
    } catch (err) {
      showNotice(friendlyMessage(err) || "Due draft generation failed", true)
    }
  }

  const sendQueueDrafts = async (draftIds) => {
    if (!draftIds.length) {
      showNotice("Approve queue drafts before sending.", true)
      return
    }

    try {
      const res = await sendQueueSelected.mutateAsync({ draft_ids: draftIds })

      startJob(res, {
        kind: "send",
        total: draftIds.length,
        progressLabel: "Sending",
        doneLabel: "Queue send",
        clearQueue: true,
      })
    } catch (err) {
      showNotice(friendlyMessage(err) || "Queue send failed", true)
    }
  }

  const requestSend = async (draftIds) => {
    const cleanIds = [...new Set(draftIds.filter(Boolean))]

    if (!cleanIds.length) {
      showNotice("No approved drafts selected.", true)
      return
    }

    if (cleanIds.length >= 5) {
      setPendingSendDraftIds(cleanIds)
      return
    }

    if (quickConfirmCount !== cleanIds.length) {
      setQuickConfirmCount(cleanIds.length)
      showNotice(`Click send again to confirm ${cleanIds.length} email(s).`)
      return
    }

    setQuickConfirmCount(0)
    await sendQueueDrafts(cleanIds)
  }

  if (isLoading) {
    return <div className="card queue-empty">Loading queue…</div>
  }

  return (
    <>
      <div className="queue-metrics">
        <div className="metric-card static">
          <strong>{items.length}</strong>
          <span>Active queue</span>
        </div>
        <div className="metric-card static">
          <strong>{grouped["Due now"].length}</strong>
          <span>Due now</span>
        </div>
        <div className="metric-card static">
          <strong>{approvedDueIds.length}</strong>
          <span>Approved due</span>
        </div>
        <div className="metric-card static">
          <strong>{history.length}</strong>
          <span>History</span>
        </div>
        <div className="metric-card static">
          <strong>{sentToday}</strong>
          <span>Sent today</span>
        </div>
      </div>

      <div className="queue-timeline">
        <div className="queue-header-actions card">
          <div>
            <h2>Queue timeline</h2>
            <p>
              Follow-ups are grouped by when they are due, with sequence position and next action.
            </p>
            {queuePolicyLine && <div className="queue-policy-line">{queuePolicyLine}</div>}
          </div>

          <div className="topbar-actions">
            <button className="btn sm" disabled={actionBusy} onClick={handleRefreshQueue} type="button">
              Refresh
            </button>
            <button className="btn sm" disabled={actionBusy} onClick={handleGenerateAllDue} type="button">
              Generate all due
            </button>
            <button
              className="btn primary sm"
              disabled={actionBusy || approvedDueIds.length === 0}
              onClick={() => requestSend(approvedDueIds)}
              type="button"
            >
              Send all approved due ({approvedDueIds.length})
            </button>
            <button
              className="btn sm"
              disabled={actionBusy || selectedApprovedIds.length === 0}
              onClick={() => requestSend(selectedApprovedIds)}
              type="button"
            >
              Send selected ({selectedApprovedIds.length})
            </button>
          </div>
        </div>

        {items.length === 0 && (
          <div className="queue-empty card">
            <h3>No active sequence items</h3>
            <p>
              Approve and send Email 1 drafts to start follow-up timing. When delays pass,
              follow-ups will appear here.
            </p>
            <button className="btn primary" onClick={() => onSelectTab("drafts")} type="button">
              Go to Drafts
            </button>
          </div>
        )}

        {SECTIONS.map((section) => {
          const sectionItems = grouped[section]
          if (!sectionItems.length) return null

          return (
            <section className="queue-section card" key={section}>
              <h3>
                {section} <span>({sectionItems.length})</span>
              </h3>

              <div className="queue-section-rows">
                {sectionItems.map((item) => {
                  const draftId = getDraftId(item)
                  const dueAt = item.next_due_at || item.next_touch_due_at || item.scheduled_for
                  const previousAt = item.previous_sent_at || item.sent_at || ""
                  const draftStatus = getQueueDraftStatus(item)

                  return (
                    <div className="queue-row" key={`${item.lead_id || item.id}-${item.touch_number}-${draftId}`}>
                      <div className="queue-identity">
                        <strong>{queueLeadName(item)}</strong>
                        <span>{queueCompanyLine(item)}</span>
                      </div>

                      <div className="queue-position">
                        <SequenceDots
                          current={item.touch_number || 1}
                          total={item.total_touches || 3}
                        />

                        <div className="queue-timing">
                          <strong>Email {item.touch_number || 1} of {item.total_touches || 3}</strong>
                          <span>
                            {previousAt ? `sent ${relativeTime(previousAt)} → ` : ""}
                            due {relativeTime(dueAt) || fmtDate(dueAt)}
                          </span>
                          {item.wait_reason && <small>{item.wait_reason}</small>}
                        </div>
                      </div>

                      <div className="queue-status">
                        <StatusPill value={draftStatus} />
                      </div>

                      <div className="queue-action">
                        <QueueAction
                          actionBusy={actionBusy}
                          filename={filename}
                          item={item}
                          onGenerate={handleGenerateItem}
                          onSendToggle={toggleDraft}
                          selectedDraftIds={selectedDraftIds}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )
        })}

        {history.length > 0 && (
          <details className="queue-history card">
            <summary>History ({history.length})</summary>

            <div className="queue-section-rows">
              {history.map((item, index) => (
                <div className="queue-row muted" key={`${item.lead_id || item.id}-${item.touch_number}-${index}`}>
                  <div className="queue-identity">
                    <strong>{queueLeadName(item)}</strong>
                    <span>{queueCompanyLine(item)}</span>
                  </div>
                  <div className="queue-position">
                    <SequenceDots current={item.touch_number || 1} total={item.total_touches || 3} />
                    <div className="queue-timing">
                      <strong>Email {item.touch_number || 1}</strong>
                      <span>{item.sent_at ? relativeTime(item.sent_at) : fmtDate(item.updated_at)}</span>
                    </div>
                  </div>
                  <StatusPill value={item.status || item.draft_status} />
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      {pendingSendDraftIds && (
        <ConfirmSendModal
          campaignName={campaignName}
          count={pendingSendDraftIds.length}
          onClose={() => setPendingSendDraftIds(null)}
          onConfirm={() => sendQueueDrafts(pendingSendDraftIds)}
        />
      )}
    </>
  )
}