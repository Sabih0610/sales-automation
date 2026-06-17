import { useEffect, useMemo, useState } from "react"
import { downloadFile, friendlyMessage, getCampaignLeads } from "../../api"
import TableSkeleton from "../../components/TableSkeleton.jsx"
import {
  useCampaignDrafts,
  useCampaignLeads,
  useGenerateDrafts,
  useLeadActivities,
  useMarkLeadStatus,
  useUploadCampaignEnriched,
  useVerifyCampaignEmails,
} from "../../queries"
import { relativeTime } from "../../utils/relativeTime"
import ReconciliationReportModal from "../../components/ReconciliationReportModal.jsx"

import LeadDrawer from "./components/LeadDrawer.jsx"
import StatusPill from "./components/StatusPill.jsx"
import SourcesTab from "./SourcesTab.jsx"
import {
  getLeadId,
  latestByLead,
} from "./utils.jsx"

const SEGMENT_FILTERS = [
  ["", "All"],
  ["needs_enrichment", "Needs enrichment"],
  ["with_email", "With email"],
]

const SEQUENCE_FILTERS = [
  ["sent", "Sent"],
  ["scheduled", "Queued"],
  ["waiting_followup", "Waiting follow-up"],
]

function EmailVerificationBadge({ lead }) {
  const status = (lead.email_verification_status || "").toLowerCase()
  const reason = lead.email_verification_reason || ""

  if (!lead.email) {
    return <span className="pill-gray">No email</span>
  }

  if (!status) {
    return <span className="pill-gray">Not checked</span>
  }

  const label =
    status === "valid"
      ? "Verified"
      : status === "risky"
        ? "Risky"
        : status === "invalid"
          ? "Invalid"
          : status

  const badgeClass =
    status === "valid"
      ? "pill-green"
      : status === "risky"
        ? "pill-amber"
        : status === "invalid"
          ? "pill-red"
          : "pill-gray"

  return (
    <span className={badgeClass} title={reason}>
      {label}
    </span>
  )
}

function MenuButton({ lead, handleMarkLead }) {
  return (
    <details className="row-menu">
      <summary className="btn xs">Status</summary>
      <div className="row-menu-pop">
        <button onClick={() => handleMarkLead(lead.id, "replied")} type="button">
          Mark replied
        </button>
        <button onClick={() => handleMarkLead(lead.id, "bounced")} type="button">
          Mark bounced
        </button>
        <button onClick={() => handleMarkLead(lead.id, "unsubscribed")} type="button">
          Mark unsubscribed
        </button>
        <button onClick={() => handleMarkLead(lead.id, "do_not_contact")} type="button">
          Do not contact
        </button>
      </div>
    </details>
  )
}

function safeItems(data) {
  if (Array.isArray(data)) return data
  return data?.items || []
}

function safeTotal(data) {
  if (Array.isArray(data)) return data.length
  return Number(data?.total || 0)
}

export default function LeadsTab({ filename, onSelectTab, showNotice }) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [qInput, setQInput] = useState("")
  const [q, setQ] = useState("")
  const [segment, setSegment] = useState("")
  const [sequenceStatus, setSequenceStatus] = useState("")
  const [selectedLeadIds, setSelectedLeadIds] = useState([])
  const [leadDrawer, setLeadDrawer] = useState(null)
  const [reconciliationResult, setReconciliationResult] = useState(null)
  const [sourceToolsOpen, setSourceToolsOpen] = useState(false)
  const [selectingAll, setSelectingAll] = useState(false)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setQ(qInput)
      setPage(1)
      setSelectedLeadIds([])
    }, 300)

    return () => window.clearTimeout(timer)
  }, [qInput])

  const leadParams = useMemo(
    () => ({
      page,
      page_size: pageSize,
      q,
      segment,
      sequence_status: sequenceStatus,
    }),
    [page, pageSize, q, segment, sequenceStatus],
  )

  const {
    data: leadsData,
    isLoading,
    isFetching,
  } = useCampaignLeads(filename, leadParams)

  const leads = safeItems(leadsData)
  const total = safeTotal(leadsData)
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)

  const { data: drafts = [] } = useCampaignDrafts(filename, { limit: 1000 })
  const draftByLead = useMemo(() => latestByLead(drafts), [drafts])

  const uploadCampaignEnriched = useUploadCampaignEnriched(filename)
  const generateDrafts = useGenerateDrafts(filename)
  const verifyCampaignEmails = useVerifyCampaignEmails(filename)

  const handleVerifyEmails = async () => {
    try {
      const result = await verifyCampaignEmails.mutateAsync({
        only_missing: true,
        limit: 500,
      })
      showNotice(
        `Verification complete: ${result.checked || 0} checked · ${result.valid || 0} valid · ${result.risky || 0} risky · ${result.invalid || 0} invalid`,
      )
    } catch (err) {
      showNotice(friendlyMessage(err) || "Email verification failed", true)
    }
  }

  const { data: leadActivities = [] } = useLeadActivities(
    leadDrawer?.id,
    { campaign_filename: filename },
  )

  const uploadingEnriched = uploadCampaignEnriched.isPending

  const markLeadReplied = useMarkLeadStatus("replied", filename)
  const markLeadBounced = useMarkLeadStatus("bounced", filename)
  const markLeadUnsubscribed = useMarkLeadStatus("unsubscribed", filename)
  const markLeadDoNotContact = useMarkLeadStatus("do_not_contact", filename)

  const markLeadMutations = {
    replied: markLeadReplied,
    bounced: markLeadBounced,
    unsubscribed: markLeadUnsubscribed,
    do_not_contact: markLeadDoNotContact,
  }

  const selectedEmailLeadIds = selectedLeadIds

  const hasFilters = Boolean(q || segment || sequenceStatus)

  const toggleLead = (leadId) => {
    setSelectedLeadIds((current) =>
      current.includes(leadId)
        ? current.filter((id) => id !== leadId)
        : [...current, leadId],
    )
  }

  const clearFilters = () => {
    setQInput("")
    setQ("")
    setSegment("")
    setSequenceStatus("")
    setPage(1)
    setSelectedLeadIds([])
  }

  const selectAllMatchingWithEmail = async () => {
    setSelectingAll(true)

    try {
      const allIds = []
      const seen = new Set()
      const selectionSegment = segment === "needs_enrichment" ? "with_email" : (segment || "with_email")
      let nextPage = 1
      let totalMatching = 0

      while (true) {
        const response = await getCampaignLeads(filename, {
          page: nextPage,
          page_size: 200,
          q,
          segment: selectionSegment,
          sequence_status: sequenceStatus,
        })

        const data = response?.data || response
        const items = safeItems(data)
        totalMatching = safeTotal(data)

        items.forEach((lead) => {
          if (lead.email && !seen.has(lead.id)) {
            seen.add(lead.id)
            allIds.push(lead.id)
          }
        })

        if (!items.length || nextPage * 200 >= totalMatching) break
        nextPage += 1
      }

      setSelectedLeadIds(allIds)
      showNotice(`Selected ${allIds.length} leads with email across all pages.`)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Could not select leads across pages.", true)
    } finally {
      setSelectingAll(false)
    }
  }

  const handleExportZoomInfo = async () => {
    try {
      await downloadFile(
        `/api/campaigns/${encodeURIComponent(filename)}/export-zoominfo`,
        `${filename.replace(/\.json$/, "")}_zoominfo_export.csv`,
      )
      showNotice("ZoomInfo export downloaded")
    } catch (err) {
      showNotice(friendlyMessage(err) || "ZoomInfo export failed", true)
    }
  }

  const handleUploadEnriched = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    try {
      const response = await uploadCampaignEnriched.mutateAsync(file)
      const result = response?.data || response

      setReconciliationResult(result)

      showNotice(
        `Upload complete: ${result.updated || 0} updated · ${result.unmatched || 0} unmatched · ${result.ambiguous || 0} ambiguous`,
      )

      setPage(1)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Upload failed", true)
    } finally {
      event.target.value = ""
    }
  }

  const handleGenerateDrafts = async (leadIds = selectedEmailLeadIds, touchNumber = 1) => {
    if (!leadIds.length) {
      showNotice("Select leads with email first.", true)
      return
    }

    try {
      const res = await generateDrafts.mutateAsync({
        lead_ids: leadIds,
        touch_number: touchNumber,
      })
      showNotice(`Draft generation queued for ${leadIds.length} lead${leadIds.length === 1 ? "" : "s"}.`)

      const queuedJobId = res?.data?.job_id || res?.job_id || ""
      const draftJobContext = {
        id: queuedJobId,
        kind: "generate",
        total: leadIds.length,
        progressLabel: "Generating",
        doneLabel: "Draft generation",
        clearDrafts: false,
      }

      if (draftJobContext.id) {
        try {
          window.sessionStorage.setItem(
            `draftJobContext:${filename}`,
            JSON.stringify(draftJobContext),
          )
        } catch {
          // Ignore storage failures.
        }
      }

      setSelectedLeadIds([])
      onSelectTab("drafts", { draftJobContext })
    } catch (err) {
      showNotice(friendlyMessage(err) || "Draft generation failed", true)
    }
  }

  const handleMarkLead = async (leadId, type) => {
    const label = type.replace(/_/g, " ")

    if (!window.confirm(`Mark this lead as ${label}? Future follow-ups will be stopped.`)) {
      return
    }

    try {
      await markLeadMutations[type].mutateAsync({
        leadId,
        data: {
          campaign_filename: filename,
          reason: `Marked ${label}`,
        },
      })
      showNotice(`Lead marked ${label}`)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Lead status update failed", true)
    }
  }

  return (
    <>
      <details
        className="embedded-tool-panel lead-source-panel"
        onToggle={(event) => setSourceToolsOpen(event.currentTarget.open)}
        open={sourceToolsOpen}
      >
        <summary>
          <span>
            <strong>Lead acquisition</strong>
            <small>Import, scrape, and manage source runs</small>
          </span>
          <span className="btn sm" aria-hidden="true">
            {sourceToolsOpen ? "Hide tools" : "Open tools"}
          </span>
        </summary>
        <div className="embedded-tool-body">
          <SourcesTab filename={filename} showNotice={showNotice} />
        </div>
      </details>

      <div className="leads-page card">
        <div className="card-head leads-card-head">
          <div>
            <h2>Leads and enrichment</h2>
            <p>
              Manage lead data, enrichment, verification, and draft generation.
            </p>
          </div>

          <div className="topbar-actions">
            <button className="btn sm" onClick={handleExportZoomInfo} type="button">
              <i className="ti ti-download" aria-hidden="true" />
              Export CSV
            </button>

            <label className="btn sm">
              <i className="ti ti-upload" aria-hidden="true" />
              {uploadingEnriched ? "Uploading..." : "Upload leads/enriched"}
              <input
                accept=".csv,.xlsx"
                onChange={handleUploadEnriched}
                style={{ display: "none" }}
                type="file"
              />
            </label>

            <button
              className="btn sm"
              disabled={selectingAll || isFetching}
              onClick={selectAllMatchingWithEmail}
              type="button"
            >
              {selectingAll ? "Selecting..." : "Select all with email"}
            </button>

            {selectedLeadIds.length > 0 && (
              <button className="btn sm" onClick={() => setSelectedLeadIds([])} type="button">
                Clear
              </button>
            )}

            <button
              className="btn primary sm"
              disabled={selectedEmailLeadIds.length === 0 || generateDrafts.isPending || selectingAll}
              onClick={() => handleGenerateDrafts()}
              title={selectedEmailLeadIds.length === 0 ? "Select leads with email first." : ""}
              type="button"
            >
              <i className={`ti ${generateDrafts.isPending ? "ti-loader-2 spinner-inline" : "ti-sparkles"}`} aria-hidden="true" />
              {generateDrafts.isPending
                ? `Queuing drafts (${selectedEmailLeadIds.length})`
                : `Generate drafts (${selectedEmailLeadIds.length})`}
            </button>
          </div>
        </div>

        <div className="banner blue table-banner">
          <i className="ti ti-info-circle" aria-hidden="true" />
          <div className="banner-msg">
            Sales Navigator usually does not include email or phone. Export leads for ZoomInfo enrichment,
            enrich externally, then upload the enriched file here.
          </div>
        </div>

        <div className="leads-toolbar">
          <input
            className="search-input"
            onChange={(event) => setQInput(event.target.value)}
            placeholder="Search name, company, title, email, phone, location…"
            value={qInput}
          />

          {SEGMENT_FILTERS.map(([value, label]) => (
            <button
              className={`filter-pill ${segment === value && !sequenceStatus ? "active" : ""}`}
              key={value}
              onClick={() => {
                setSegment(value)
                setSequenceStatus("")
                setPage(1)
                setSelectedLeadIds([])
              }}
              type="button"
            >
              {label}
            </button>
          ))}

          {SEQUENCE_FILTERS.map(([value, label]) => (
            <button
              className={`filter-pill ${sequenceStatus === value ? "active" : ""}`}
              key={value}
              onClick={() => {
                setSequenceStatus(value)
                setSegment("")
                setPage(1)
                setSelectedLeadIds([])
              }}
              type="button"
            >
              {label}
            </button>
          ))}

          <select
            className="form-input compact"
            onChange={(event) => {
              setPageSize(Number(event.target.value))
              setPage(1)
              setSelectedLeadIds([])
            }}
            value={pageSize}
          >
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
        </div>

        {selectedLeadIds.length > 0 && (
          <div className="selection-bar">
            <strong>{selectedLeadIds.length}</strong>
            <span>selected across this campaign</span>
            <button className="btn xs" onClick={() => setSelectedLeadIds([])} type="button">
              Clear selection
            </button>
          </div>
        )}

        <div className="table-wrap leads-table-wrap">
          <table className="leads-table">
            <thead>
              <tr>
                <th></th>
                <th>Name</th>
                <th>Email</th>
                <th>Status</th>
                <th>Last activity</th>
                <th>Location</th>
                <th></th>
              </tr>
            </thead>

            {isLoading ? (
              <TableSkeleton cols={7} rows={8} />
            ) : (
              <tbody>
                {leads.length === 0 && (
                  <tr>
                    <td className="empty-cell" colSpan={7}>
                      {hasFilters ? (
                        <div className="inline-empty">
                          <strong>No leads match.</strong>
                          <span>Try clearing search or filters.</span>
                          <button className="btn sm" onClick={clearFilters} type="button">
                            Clear filters
                          </button>
                        </div>
                      ) : (
                        <div className="inline-empty">
                          <strong>No leads yet.</strong>
                          <span>Add or import leads to start this campaign.</span>
                          <button className="btn sm primary" onClick={() => setSourceToolsOpen(true)} type="button">
                            Open Lead Tools
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )}

                {leads.map((lead) => {
                  const latestDraft = draftByLead.get(lead.id)
                  const sequenceStatus =
                    latestDraft?.status ||
                    lead.sequence_status ||
                    lead.email_sequence_status ||
                    "not_started"

                  return (
                    <tr className="lead-row" key={lead.id}>
                      <td>
                        <input
                          checked={selectedLeadIds.includes(lead.id)}
                          disabled={!lead.email || selectingAll || generateDrafts.isPending}
                          onChange={() => toggleLead(lead.id)}
                          type="checkbox"
                        />
                      </td>

                      <td>
                        <button className="lead-name-button" onClick={() => setLeadDrawer(lead)} type="button">
                          {lead.full_name || "Unknown lead"}
                        </button>
                        <div className="lead-subline">
                          {lead.company || "—"} · {lead.title || "—"}
                        </div>
                        {lead.other_campaigns?.length > 0 ? (
                          <span
                            className="pill-amber"
                            title={`Also in: ${lead.other_campaigns.join(", ")}`}
                          >
                            {lead.other_campaigns.length === 1
                              ? `Also in: ${lead.other_campaigns[0]}`
                              : `Also in: ${lead.other_campaigns[0]} +${lead.other_campaigns.length - 1}`}
                          </span>
                        ) : lead.duplicate_of_lead_id ? (
                          <span
                            className="pill-amber"
                            title="This person also exists in another campaign"
                          >
                            Also in another campaign
                          </span>
                        ) : null}
                        {lead.is_suppressed && (
                          <span className="pill-amber">
                            Suppressed
                          </span>
                        )}
                      </td>

                      <td>
                        <div className="email-cell">
                          {lead.email ? (
                            <button
                              className="copy-email-button"
                              onClick={() => {
                                navigator.clipboard.writeText(lead.email)
                                showNotice("Email copied")
                              }}
                              type="button"
                            >
                              {lead.email}
                            </button>
                          ) : (
                            <span className="muted">— needs enrichment</span>
                          )}
                          <EmailVerificationBadge lead={lead} />
                        </div>
                      </td>

                      <td>
                        <div className="status-stack">
                          <StatusPill value={lead.segment === "NO_EMAIL" ? "NEEDS_ENRICHMENT" : lead.segment} />
                          <StatusPill value={sequenceStatus} />
                        </div>
                      </td>

                      <td className="muted">
                        {lead.last_activity_at ? (
                          <>
                            {relativeTime(lead.last_activity_at)}
                            {lead.last_activity_title ? ` · ${lead.last_activity_title}` : ""}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>

                      <td className="muted">
                        {lead.location || "—"}
                      </td>

                      <td>
                        <div className="row-actions">
                          <button className="btn xs" onClick={() => setLeadDrawer(lead)} type="button">
                            Open
                          </button>
                          {lead.linkedin_url && (
                            <a
                              className="btn xs icon"
                              href={lead.linkedin_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              <i className="ti ti-brand-linkedin" aria-hidden="true" />
                            </a>
                          )}
                          <MenuButton lead={lead} handleMarkLead={handleMarkLead} />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            )}
          </table>
        </div>

        {total > 0 && (
          <div className="pagination-footer">
            <span>
              {from}–{to} of {total}
              {isFetching ? " · refreshing…" : ""}
            </span>

            <div className="pagination-actions">
              <button
                className="btn sm"
                disabled={page === 1}
                onClick={() => {
                  setPage((current) => Math.max(1, current - 1))
                  setSelectedLeadIds([])
                }}
                type="button"
              >
                Prev
              </button>

              <span>Page {page}</span>

              <button
                className="btn sm"
                disabled={to >= total}
                onClick={() => {
                  setPage((current) => current + 1)
                  setSelectedLeadIds([])
                }}
                type="button"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {leadDrawer && (
        <LeadDrawer
          draftByLead={draftByLead}
          drafts={drafts.filter((draft) => getLeadId(draft) === leadDrawer.id)}
          handleGenerateDrafts={() => handleGenerateDrafts([leadDrawer.id])}
          handleMarkLead={handleMarkLead}
          lead={leadDrawer}
          leadActivities={leadActivities}
          onClose={() => setLeadDrawer(null)}
        />
      )}

      {reconciliationResult && (
        <ReconciliationReportModal
          result={reconciliationResult}
          onClose={() => setReconciliationResult(null)}
        />
      )}
    </>
  )
}
