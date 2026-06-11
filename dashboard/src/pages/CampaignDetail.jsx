import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import {
  addLeadSourceSegment,
  approveDraft,
  approveSelectedDrafts,
  createLeadUniverse,
  exportCampaignZoomInfo,
  generateCampaignDrafts,
  generateDueDrafts,
  getCampaignActivities,
  getCampaignDrafts,
  getCampaignLeadUniverses,
  getCampaignLeads,
  getCampaignOverview,
  getCampaignQueue,
  getCampaignRuns,
  getCampaigns,
  getLeadActivities,
  getSequenceSettings,
  markLeadBounced,
  markLeadDoNotContact,
  markLeadReplied,
  markLeadUnsubscribed,
  pauseLeadSourceSegments,
  runAllLeadSourceSegments,
  runLeadSourceSegment,
  runNextLeadSourceSegment,
  saveSequenceSettings,
  sendCampaignQueueSelected,
  sendDraftTest,
  sendSelectedDrafts,
  skipDraft,
  startRun,
  updateOutreachDraft,
  uploadCampaignEnriched,
} from "../api"

const tabs = [
  "Overview",
  "Sources",
  "Leads",
  "Drafts",
  "Queue",
  "Sequence",
  "Activity",
  "Settings",
]

const defaultQueue = {
  due_today: [],
  scheduled: [],
  waiting: [],
  sent: [],
  failed: [],
  skipped: [],
}

const emptyOverview = {
  total_leads: 0,
  needs_enrichment: 0,
  with_email: 0,
  drafts_generated: 0,
  approved_drafts: 0,
  scheduled: 0,
  emails_sent: 0,
  followups_due: 0,
  replies: 0,
  bounces: 0,
  unsubscribed: 0,
  completed: 0,
  active_sequence_steps: 0,
  pipeline: {
    scraped: 0,
    enriched: 0,
    drafted: 0,
    approved: 0,
    sent: 0,
    replied: 0,
    completed: 0,
  },
  lead_collection: {
    total_source_segments: 0,
    completed_segments: 0,
    running_segments: 0,
    total_scraped: 0,
    unique_leads: 0,
    duplicates_removed: 0,
    needs_enrichment: 0,
    with_email: 0,
  },
}

const defaultRules = {
  mode: "review",
  timezone: "Asia/Karachi",
  stop_on_reply: true,
  stop_on_bounce: true,
  stop_on_unsubscribe: true,
  skip_no_email: true,
  skip_weekends: true,
  send_window_start: "09:00",
  send_window_end: "17:00",
  daily_send_limit: 50,
  delay_between_sends_seconds: 60,
}

const leadFilters = [
  ["all", "All"],
  ["needs_enrichment", "Needs enrichment"],
  ["with_email", "With email"],
  ["draft_not_generated", "Draft not generated"],
  ["draft_generated", "Draft generated"],
  ["approved", "Approved"],
  ["sent", "Sent"],
  ["replied", "Replied"],
  ["bounced", "Bounced"],
  ["unsubscribed", "Unsubscribed"],
]

const queueViews = [
  ["due_today", "Due today"],
  ["scheduled", "Scheduled"],
  ["waiting", "Waiting"],
  ["failed", "Failed"],
  ["sent", "Sent"],
  ["skipped", "Skipped"],
]

const activityFilters = [
  ["all", "All"],
  ["scraping", "Scraping"],
  ["enrichment", "Enrichment"],
  ["drafts", "Drafts"],
  ["sending", "Sending"],
  ["replies", "Replies"],
  ["errors", "Errors"],
]

const fmtDate = (value) => {
  if (!value) return "-"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

const statusClass = (value) =>
  (value || "pending").toLowerCase().replace(/_/g, "-")

const statusText = (value) =>
  (value || "not_started").replace(/_/g, " ")

const getDraftId = (draft) => draft?.draft_id || draft?.id || ""
const getLeadId = (item) => item?.lead_id || item?.id || ""
const draftSubject = (draft) => draft?.subject || draft?.email_subject || ""
const draftBody = (draft) => draft?.body || draft?.email_body || ""
const getDetectedTimezone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Karachi"
  } catch (err) {
    return "Asia/Karachi"
  }
}
const sequenceStepName = (number) => {
  if (Number(number) === 1) return "Intro"
  if (Number(number) === 2) return "Follow-up"
  if (Number(number) === 3) return "Final follow-up"
  return `Email ${number}`
}
const sequenceStepLabel = (number) => `Email ${number} - ${sequenceStepName(number)}`
const draftToForm = (draft) => ({
  subject: draftSubject(draft),
  body: draftBody(draft),
})

const latestByLead = (drafts) => {
  const map = new Map()
  drafts.forEach((draft) => {
    const leadId = getLeadId(draft)
    if (!leadId) return
    const existing = map.get(leadId)
    if (!existing || String(draft.updated_at || "") > String(existing.updated_at || "")) {
      map.set(leadId, draft)
    }
  })
  return map
}

const activityBucket = (type = "") => {
  if (["scraped", "exported_for_zoominfo"].includes(type)) return "scraping"
  if (["enriched", "uploaded_enriched"].includes(type)) return "enrichment"
  if (type.startsWith("draft_")) return "drafts"
  if (["email_sent", "followup_scheduled", "followup_due", "test_sent"].includes(type)) return "sending"
  if (["replied", "bounced", "unsubscribed", "do_not_contact"].includes(type)) return "replies"
  if (["failed", "skipped"].includes(type)) return "errors"
  return "all"
}

const emptyDraftForm = {
  subject: "",
  body: "",
}

const safeData = (result, fallback) =>
  result.status === "fulfilled" ? result.value.data : fallback

export default function CampaignDetail() {
  const { filename: encodedFilename } = useParams()
  const filename = decodeURIComponent(encodedFilename || "")
  const navigate = useNavigate()

  const [campaign, setCampaign] = useState(null)
  const [overview, setOverview] = useState(emptyOverview)
  const [runs, setRuns] = useState([])
  const [universes, setUniverses] = useState([])
  const [selectedUniverseId, setSelectedUniverseId] = useState("")
  const [leads, setLeads] = useState([])
  const [drafts, setDrafts] = useState([])
  const [queue, setQueue] = useState(defaultQueue)
  const [activities, setActivities] = useState([])
  const [sequence, setSequence] = useState({ steps: [], touches: [], rules: defaultRules })
  const [activeTab, setActiveTab] = useState("Overview")
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState(null)
  const [previewDraft, setPreviewDraft] = useState(null)

  const [leadFilter, setLeadFilter] = useState("all")
  const [selectedLeadIds, setSelectedLeadIds] = useState([])
  const [leadDrawer, setLeadDrawer] = useState(null)
  const [leadDrawerTab, setLeadDrawerTab] = useState("Overview")
  const [leadActivities, setLeadActivities] = useState([])

  const [draftStatusFilter, setDraftStatusFilter] = useState("")
  const [draftTouchFilter, setDraftTouchFilter] = useState("")
  const [selectedDraftIds, setSelectedDraftIds] = useState([])
  const [selectedDraftId, setSelectedDraftId] = useState("")
  const selectedDraftIdRef = useRef("")
  const [draftForm, setDraftForm] = useState(emptyDraftForm)
  const [testEmail, setTestEmail] = useState("")

  const [queueView, setQueueView] = useState("due_today")
  const [selectedDueLeadIds, setSelectedDueLeadIds] = useState([])
  const [selectedQueueDraftIds, setSelectedQueueDraftIds] = useState([])

  const [activityFilter, setActivityFilter] = useState("all")
  const [sourceBusy, setSourceBusy] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [savingSequence, setSavingSequence] = useState(false)
  const [uploadingEnriched, setUploadingEnriched] = useState(false)

  const [sourceForm, setSourceForm] = useState({
    source_url: "",
    max_leads: 100,
    titles: "CTO, CIO, Head of Data",
    keywords: "",
    geos: "",
    showAdvanced: false,
  })
  const [universeForm, setUniverseForm] = useState({
    name: "",
    description: "",
    target_leads: 1000,
  })
  const [segmentForm, setSegmentForm] = useState({
    label: "",
    source_url: "",
    expected_count: 50,
  })

  const loadWorkspace = useCallback(async () => {
    setLoading(true)
    const [
      campaignsRes,
      overviewRes,
      runsRes,
      universesRes,
      leadsRes,
      draftsRes,
      queueRes,
      activitiesRes,
      sequenceRes,
    ] = await Promise.allSettled([
      getCampaigns(),
      getCampaignOverview(filename),
      getCampaignRuns(filename),
      getCampaignLeadUniverses(filename),
      getCampaignLeads(filename, { limit: 1000 }),
      getCampaignDrafts(filename, { limit: 1000 }),
      getCampaignQueue(filename),
      getCampaignActivities(filename, { limit: 100 }),
      getSequenceSettings(filename),
    ])

    const campaignRows = safeData(campaignsRes, [])
    setCampaign(campaignRows.find((item) => item.filename === filename) || null)
    setOverview({ ...emptyOverview, ...safeData(overviewRes, emptyOverview) })
    setRuns(safeData(runsRes, []))

    const loadedUniverses = safeData(universesRes, [])
    setUniverses(loadedUniverses)
    setSelectedUniverseId((current) => current || loadedUniverses[0]?.id || "")

    setLeads(safeData(leadsRes, []))
    const loadedDrafts = safeData(draftsRes, [])
    setDrafts(loadedDrafts)
    setQueue({ ...defaultQueue, ...safeData(queueRes, defaultQueue) })
    setActivities(safeData(activitiesRes, []))

    const sequenceData = safeData(sequenceRes, { steps: [], touches: [], rules: defaultRules })
    setSequence({
      ...sequenceData,
      rules: { ...defaultRules, ...(sequenceData.rules || {}) },
      steps: sequenceData.steps || sequenceData.touches || [],
      touches: sequenceData.touches || sequenceData.steps || [],
    })

    const currentDraftId = selectedDraftIdRef.current
    const nextDraft =
      loadedDrafts.find((draft) => getDraftId(draft) === currentDraftId) ||
      loadedDrafts[0] ||
      null
    const nextDraftId = getDraftId(nextDraft)
    selectedDraftIdRef.current = nextDraftId
    setSelectedDraftId(nextDraftId)
    setDraftForm(nextDraft ? draftToForm(nextDraft) : emptyDraftForm)
    setLoading(false)
  }, [filename])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadWorkspace().catch((err) => {
        setLoading(false)
        setNotice({ error: err.response?.data?.detail || "Campaign workspace failed to load" })
      })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadWorkspace])

  const selectDraft = (draft) => {
    const draftId = getDraftId(draft)
    selectedDraftIdRef.current = draftId
    setSelectedDraftId(draftId)
    setDraftForm(draft ? draftToForm(draft) : emptyDraftForm)
  }

  const campaignName = campaign?.name || filename
  const selectedUniverse =
    universes.find((universe) => universe.id === selectedUniverseId) || universes[0] || null
  const sourceSegments = selectedUniverse?.segments || []
  const leadCollection = overview.lead_collection || emptyOverview.lead_collection
  const draftByLead = useMemo(() => latestByLead(drafts), [drafts])
  const steps = sequence.steps || sequence.touches || []
  const rules = { ...defaultRules, ...(sequence.rules || {}) }

  const selectedDraft = useMemo(
    () => drafts.find((draft) => getDraftId(draft) === selectedDraftId) || null,
    [drafts, selectedDraftId],
  )

  const filteredLeads = useMemo(() => {
    return leads.filter((lead) => {
      const latestDraft = draftByLead.get(lead.id)
      const leadStatus = (lead.email_sequence_status || "").toLowerCase()
      const latestStatus = (latestDraft?.status || "").toLowerCase()
      if (leadFilter === "needs_enrichment") return !lead.email || lead.segment === "NO_EMAIL"
      if (leadFilter === "with_email") return Boolean(lead.email)
      if (leadFilter === "draft_not_generated") return lead.email && !latestDraft
      if (leadFilter === "draft_generated") return Boolean(latestDraft)
      if (leadFilter === "approved") return latestStatus === "approved"
      if (leadFilter === "sent") return latestStatus === "sent" || leadStatus.includes("sent")
      if (leadFilter === "replied") return leadStatus === "replied"
      if (leadFilter === "bounced") return leadStatus === "bounced"
      if (leadFilter === "unsubscribed") return leadStatus === "unsubscribed"
      return true
    })
  }, [draftByLead, leadFilter, leads])

  const filteredDrafts = useMemo(() => {
    return drafts.filter((draft) => {
      if (draftStatusFilter && draft.status !== draftStatusFilter) return false
      if (draftTouchFilter && String(draft.touch_number) !== String(draftTouchFilter)) return false
      return true
    })
  }, [draftStatusFilter, draftTouchFilter, drafts])

  const filteredActivities = useMemo(() => {
    if (activityFilter === "all") return activities
    return activities.filter((activity) => activityBucket(activity.activity_type) === activityFilter)
  }, [activities, activityFilter])

  const selectedEmailLeadIds = selectedLeadIds.filter((leadId) =>
    leads.some((lead) => lead.id === leadId && lead.email),
  )

  const approvedSelectedDraftIds = selectedDraftIds.filter((draftId) => {
    const draft = drafts.find((item) => getDraftId(item) === draftId)
    return draft?.status === "approved"
  })

  const queueDraftRows = queue[queueView] || []
  const sentToday = (queue.sent || []).filter((draft) => {
    if (!draft.sent_at) return false
    return new Date(draft.sent_at).toDateString() === new Date().toDateString()
  }).length

  const showNotice = (message, error = false) => {
    if (error) console.error(message)
    setNotice(error ? { error: message } : { success: true, message })
  }

  const sendResultMessage = (res, fallback) => {
    const data = res.data || {}
    const detailReason = data.details?.find((item) => item.message || item.reason)
    return (
      data.message ||
      detailReason?.message ||
      (detailReason?.reason ? `${fallback} Reason: ${detailReason.reason}` : "") ||
      fallback
    )
  }

  const toggleLead = (leadId) => {
    setSelectedLeadIds((current) =>
      current.includes(leadId)
        ? current.filter((id) => id !== leadId)
        : [...current, leadId],
    )
  }

  const toggleDraft = (draftId) => {
    setSelectedDraftIds((current) =>
      current.includes(draftId)
        ? current.filter((id) => id !== draftId)
        : [...current, draftId],
    )
  }

  const toggleDueLead = (leadId) => {
    setSelectedDueLeadIds((current) =>
      current.includes(leadId)
        ? current.filter((id) => id !== leadId)
        : [...current, leadId],
    )
  }

  const toggleQueueDraft = (draftId) => {
    setSelectedQueueDraftIds((current) =>
      current.includes(draftId)
        ? current.filter((id) => id !== draftId)
        : [...current, draftId],
    )
  }

  const handleStartRun = async () => {
    if (!sourceForm.source_url.trim()) {
      showNotice("Source URL is required", true)
      return
    }
    setSourceBusy(true)
    try {
      const parseList = (value) => value.split(",").map((item) => item.trim()).filter(Boolean)
      const res = await startRun({
        start_url: sourceForm.source_url.trim(),
        max_leads: Number(sourceForm.max_leads) || 100,
        campaign: filename,
        titles: parseList(sourceForm.titles),
        keywords: sourceForm.keywords,
        geos: parseList(sourceForm.geos),
        industries: [],
        company_sizes: [],
      })
      showNotice("Campaign source run started")
      navigate(`/runs/${res.data.id}`)
    } catch (err) {
      showNotice(err.response?.data?.detail || "Run failed to start", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleCreateUniverse = async () => {
    if (!universeForm.name.trim()) {
      showNotice("Universe name is required", true)
      return
    }
    setSourceBusy(true)
    try {
      const res = await createLeadUniverse({
        name: universeForm.name.trim(),
        campaign_filename: filename,
        description: universeForm.description.trim(),
        target_leads: Number(universeForm.target_leads) || 0,
        source_type: "sales_navigator",
      })
      setSelectedUniverseId(res.data.id)
      setUniverseForm({ name: "", description: "", target_leads: 1000 })
      showNotice("Lead universe created")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Universe creation failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleAddSegment = async () => {
    if (!selectedUniverse) {
      showNotice("Create a lead universe first", true)
      return
    }
    if (!segmentForm.source_url.trim()) {
      showNotice("Sales Navigator URL is required", true)
      return
    }
    setSourceBusy(true)
    try {
      await addLeadSourceSegment(selectedUniverse.id, {
        label: segmentForm.label.trim(),
        source_url: segmentForm.source_url.trim(),
        expected_count: Number(segmentForm.expected_count) || 50,
        filters: {},
      })
      setSegmentForm({ label: "", source_url: "", expected_count: 50 })
      showNotice("Source segment added")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Segment creation failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleRunSegment = async (segmentId) => {
    setSourceBusy(true)
    try {
      await runLeadSourceSegment(segmentId)
      showNotice("Segment run started")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Segment run failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleRunNext = async () => {
    if (!selectedUniverse) return
    setSourceBusy(true)
    try {
      const res = await runNextLeadSourceSegment(selectedUniverse.id)
      showNotice(res.data.started ? "Next segment started" : "No queued segments")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Run next failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleRunAll = async () => {
    if (!selectedUniverse) return
    setSourceBusy(true)
    try {
      const res = await runAllLeadSourceSegments(selectedUniverse.id)
      showNotice(res.data.started ? `Started ${res.data.queued || 0} queued segments` : "No queued segments")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Run all failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handlePauseAll = async () => {
    if (!selectedUniverse) return
    setSourceBusy(true)
    try {
      const res = await pauseLeadSourceSegments(selectedUniverse.id)
      showNotice(`Paused ${res.data.paused || 0} segments`)
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Pause failed", true)
    } finally {
      setSourceBusy(false)
    }
  }

  const handleExportZoomInfo = async () => {
    try {
      const res = await exportCampaignZoomInfo(filename)
      const blob = new Blob([res.data], { type: "text/csv;charset=utf-8" })
      const url = window.URL.createObjectURL(blob)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = `${filename.replace(/\.json$/, "")}_zoominfo_export.csv`
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      window.URL.revokeObjectURL(url)
      showNotice("ZoomInfo export downloaded")
    } catch (err) {
      showNotice(err.response?.data?.detail || "ZoomInfo export failed", true)
    }
  }

  const handleUploadEnriched = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    setUploadingEnriched(true)
    try {
      const res = await uploadCampaignEnriched(filename, file)
      showNotice(
        `Rows ${res.data.total_rows}, matched ${res.data.matched}, updated ${res.data.updated}`,
      )
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Enriched upload failed", true)
    } finally {
      setUploadingEnriched(false)
      event.target.value = ""
    }
  }

  const handleGenerateDrafts = async (leadIds = selectedEmailLeadIds, touchNumber = 1) => {
    if (!leadIds.length) {
      showNotice("Select leads with email first.", true)
      return
    }
    setActionBusy(true)
    try {
      const res = await generateCampaignDrafts(filename, {
        lead_ids: leadIds,
        touch_number: touchNumber,
      })
      showNotice(`${res.data.generated || 0} drafts generated. Review them in Drafts.`)
      setSelectedLeadIds([])
      await loadWorkspace()
      setActiveTab("Drafts")
    } catch (err) {
      showNotice(err.response?.data?.detail || "Draft generation failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const openLeadDrawer = async (lead) => {
    setLeadDrawer(lead)
    setLeadDrawerTab("Overview")
    try {
      const res = await getLeadActivities(lead.id, { campaign_filename: filename })
      setLeadActivities(res.data || [])
    } catch {
      setLeadActivities([])
    }
  }

  const handleMarkLead = async (leadId, type) => {
    const apiByType = {
      replied: markLeadReplied,
      bounced: markLeadBounced,
      unsubscribed: markLeadUnsubscribed,
      do_not_contact: markLeadDoNotContact,
    }
    const label = type.replace(/_/g, " ")
    if (!window.confirm(`Mark this lead as ${label}? Future follow-ups will be stopped.`)) {
      return
    }
    setActionBusy(true)
    try {
      await apiByType[type](leadId, {
        campaign_filename: filename,
        reason: `Marked ${label}`,
      })
      showNotice(`Lead marked ${label}`)
      await loadWorkspace()
      if (leadDrawer?.id === leadId) {
        const res = await getLeadActivities(leadId, { campaign_filename: filename })
        setLeadActivities(res.data || [])
      }
    } catch (err) {
      showNotice(err.response?.data?.detail || "Lead status update failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleSaveDraft = async () => {
    if (!selectedDraft) return
    setActionBusy(true)
    try {
      await updateOutreachDraft(getDraftId(selectedDraft), draftForm)
      showNotice("Draft saved")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Draft save failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleApproveDraft = async (draftId = selectedDraftId) => {
    if (!draftId) return
    setActionBusy(true)
    try {
      if (selectedDraft && draftId === getDraftId(selectedDraft)) {
        await updateOutreachDraft(draftId, draftForm)
      }
      await approveDraft(draftId)
      showNotice("Draft approved")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Draft approval failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleApproveSelected = async (draftIds = selectedDraftIds) => {
    if (!draftIds.length) {
      showNotice("Select drafts first.", true)
      return
    }
    setActionBusy(true)
    try {
      const res = await approveSelectedDrafts({ draft_ids: draftIds })
      showNotice(`${res.data.approved || 0} drafts approved`)
      setSelectedDraftIds([])
      setSelectedQueueDraftIds([])
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Bulk approval failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleSkipDraft = async () => {
    if (!selectedDraft) return
    if (!window.confirm("Skip this draft? It will not be sent unless regenerated.")) {
      return
    }
    setActionBusy(true)
    try {
      await skipDraft(getDraftId(selectedDraft), { reason: "Skipped from review workspace" })
      showNotice("Draft skipped")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Draft skip failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleSendTest = async () => {
    if (!selectedDraft) return
    if (!testEmail.trim()) {
      showNotice("Enter a test email first.", true)
      return
    }
    setActionBusy(true)
    try {
      await updateOutreachDraft(getDraftId(selectedDraft), draftForm)
      const res = await sendDraftTest(getDraftId(selectedDraft), { test_email: testEmail.trim() })
      showNotice(res.data.success ? `Test sent to ${testEmail}` : res.data.error || "Test send failed", !res.data.success)
    } catch (err) {
      showNotice(err.response?.data?.detail || "Test send failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleSendSelectedApproved = async (draftIds = approvedSelectedDraftIds) => {
    if (!draftIds.length) {
      showNotice("Approve drafts before sending.", true)
      return
    }
    setActionBusy(true)
    try {
      if (selectedDraft && draftIds.includes(getDraftId(selectedDraft))) {
        await updateOutreachDraft(getDraftId(selectedDraft), draftForm)
      }
      const res = await sendSelectedDrafts({ draft_ids: draftIds })
      showNotice(sendResultMessage(
        res,
        `Sent ${res.data.sent || 0}, skipped ${res.data.skipped || 0}, failed ${res.data.failed || 0}`,
      ))
      setSelectedDraftIds([])
      setSelectedQueueDraftIds([])
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Send failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleSendQueueSelected = async (draftIds) => {
    if (!draftIds.length) {
      showNotice("Approve queue drafts before sending.", true)
      return
    }
    setActionBusy(true)
    try {
      const res = await sendCampaignQueueSelected(filename, { draft_ids: draftIds })
      showNotice(sendResultMessage(
        res,
        `Sent ${res.data.sent || 0}, skipped ${res.data.skipped || 0}, failed ${res.data.failed || 0}`,
      ))
      setSelectedQueueDraftIds([])
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Queue send failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleGenerateDue = async () => {
    setActionBusy(true)
    try {
      const payload = selectedDueLeadIds.length ? { lead_ids: selectedDueLeadIds } : {}
      const res = await generateDueDrafts(filename, payload)
      showNotice(`${res.data.generated || 0} due drafts generated`)
      setSelectedDueLeadIds([])
      await loadWorkspace()
      setActiveTab("Drafts")
    } catch (err) {
      showNotice(err.response?.data?.detail || "Due draft generation failed", true)
    } finally {
      setActionBusy(false)
    }
  }

  const handleRefreshWorkspace = async (message = "Workspace refreshed") => {
    try {
      await loadWorkspace()
      showNotice(message)
    } catch (err) {
      showNotice(err.response?.data?.detail || "Refresh failed", true)
    }
  }

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

  const handleSaveSequence = async () => {
    setSavingSequence(true)
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
        mode: rules.mode === "autopilot" ? "autopilot" : "review",
        timezone: rules.timezone || getDetectedTimezone(),
      }
      await saveSequenceSettings(filename, { steps: cleanedSteps, touches: cleanedSteps, rules: cleanedRules })
      showNotice("Sequence settings saved")
      await loadWorkspace()
    } catch (err) {
      showNotice(err.response?.data?.detail || "Sequence save failed", true)
    } finally {
      setSavingSequence(false)
    }
  }

  const primaryAction = () => {
    if (activeTab === "Sources") {
      return (
        <button className="btn primary" onClick={handleStartRun} disabled={sourceBusy}>
          <i className="ti ti-player-play" aria-hidden="true" />
          Start run
        </button>
      )
    }
    if (activeTab === "Leads") {
      return (
        <button
          className="btn primary"
          onClick={() => handleGenerateDrafts()}
          disabled={actionBusy || selectedEmailLeadIds.length === 0}
          title={selectedEmailLeadIds.length === 0 ? "Select leads with email first." : ""}
        >
          <i className="ti ti-sparkles" aria-hidden="true" />
          Generate drafts ({selectedEmailLeadIds.length})
        </button>
      )
    }
    if (activeTab === "Drafts") {
      return (
        <button
          className="btn primary"
          onClick={() => handleSendSelectedApproved()}
          disabled={actionBusy || approvedSelectedDraftIds.length === 0}
          title={approvedSelectedDraftIds.length === 0 ? "Approve drafts before sending." : ""}
        >
          <i className="ti ti-send" aria-hidden="true" />
          Send approved ({approvedSelectedDraftIds.length})
        </button>
      )
    }
    if (activeTab === "Queue") {
      const approvedQueueIds = selectedQueueDraftIds.filter((draftId) =>
        drafts.some((draft) => getDraftId(draft) === draftId && draft.status === "approved"),
      )
      return (
        <button
          className="btn primary"
          onClick={() => handleSendQueueSelected(approvedQueueIds)}
          disabled={actionBusy || approvedQueueIds.length === 0}
          title={approvedQueueIds.length === 0 ? "Approve drafts before sending." : ""}
        >
          <i className="ti ti-send" aria-hidden="true" />
          Send due batch
        </button>
      )
    }
    if (activeTab === "Sequence") {
      return (
        <button className="btn primary" onClick={handleSaveSequence} disabled={savingSequence}>
          <i className="ti ti-device-floppy" aria-hidden="true" />
          Save settings
        </button>
      )
    }
    return (
      <button className="btn primary" onClick={() => setActiveTab("Sources")}>
        <i className="ti ti-player-play" aria-hidden="true" />
        New run
      </button>
    )
  }

  return (
    <>
      <div className="topbar">
        <Link to="/campaigns" className="topbar-link">
          <i className="ti ti-arrow-left" aria-hidden="true" /> Campaigns
        </Link>
        <div className="topbar-title">{campaignName}</div>
        <div className="topbar-actions">{primaryAction()}</div>
      </div>

      <div className="page-content campaign-workspace">
        {notice && (
          <div className={`toast ${notice.error ? "red" : "green"}`}>
            <i className={`ti ti-${notice.error ? "alert-circle" : "check"}`} aria-hidden="true" />
            <span>{notice.error || notice.message}</span>
            <button className="btn xs icon" onClick={() => setNotice(null)}>
              <i className="ti ti-x" aria-hidden="true" />
            </button>
          </div>
        )}

        <div className="campaign-hero">
          <div>
            <div className="campaign-kicker">Campaign workspace</div>
            <h1>{campaignName}</h1>
            <p>{campaign?.description || "Manage collection, enrichment, drafts, approvals, follow-ups, and activity from one place."}</p>
          </div>
          <span className="badge completed">Active</span>
        </div>

        <div className="workspace-tabs">
          {tabs.map((tab) => (
            <button
              type="button"
              className={`workspace-tab${activeTab === tab ? " active" : ""}`}
              key={tab}
              onClick={() => setActiveTab(tab)}
            >
              {tab}
            </button>
          ))}
        </div>

        {loading && (
          <div className="card">
            <div className="card-body muted">Loading campaign workspace...</div>
          </div>
        )}

        {!loading && activeTab === "Overview" && (
          <OverviewTab
            activities={activities}
            leadCollection={leadCollection}
            overview={overview}
            runs={runs}
            setActiveTab={setActiveTab}
          />
        )}

        {!loading && activeTab === "Sources" && (
          <SourcesTab
            handleAddSegment={handleAddSegment}
            handleCreateUniverse={handleCreateUniverse}
            handlePauseAll={handlePauseAll}
            handleRunAll={handleRunAll}
            handleRunNext={handleRunNext}
            handleRunSegment={handleRunSegment}
            handleStartRun={handleStartRun}
            selectedUniverse={selectedUniverse}
            selectedUniverseId={selectedUniverseId}
            segmentForm={segmentForm}
            setSegmentForm={setSegmentForm}
            setSelectedUniverseId={setSelectedUniverseId}
            setSourceForm={setSourceForm}
            setUniverseForm={setUniverseForm}
            sourceBusy={sourceBusy}
            sourceForm={sourceForm}
            sourceSegments={sourceSegments}
            universeForm={universeForm}
            universes={universes}
            runs={runs}
          />
        )}

        {!loading && activeTab === "Leads" && (
          <LeadsTab
            allLeadCount={leads.length}
            draftByLead={draftByLead}
            filteredLeads={filteredLeads}
            handleExportZoomInfo={handleExportZoomInfo}
            handleGenerateDrafts={() => handleGenerateDrafts()}
            handleMarkLead={handleMarkLead}
            handleUploadEnriched={handleUploadEnriched}
            leadFilter={leadFilter}
            openLeadDrawer={openLeadDrawer}
            selectedEmailLeadIds={selectedEmailLeadIds}
            selectedLeadIds={selectedLeadIds}
            setLeadFilter={setLeadFilter}
            setSelectedLeadIds={setSelectedLeadIds}
            toggleLead={toggleLead}
            uploadingEnriched={uploadingEnriched}
          />
        )}

        {!loading && activeTab === "Drafts" && (
          <DraftsTab
            actionBusy={actionBusy}
            draftForm={draftForm}
            draftStatusFilter={draftStatusFilter}
            draftTouchFilter={draftTouchFilter}
            filteredDrafts={filteredDrafts}
            handleApproveDraft={handleApproveDraft}
            handleApproveSelected={handleApproveSelected}
            handlePreviewDraft={() => setPreviewDraft(selectedDraft)}
            handleRefreshDrafts={() => handleRefreshWorkspace("Drafts refreshed")}
            handleSaveDraft={handleSaveDraft}
            handleSendSelectedApproved={handleSendSelectedApproved}
            handleSendTest={handleSendTest}
            handleSkipDraft={handleSkipDraft}
            selectedDraft={selectedDraft}
            selectedDraftId={selectedDraftId}
            selectedDraftIds={selectedDraftIds}
            selectDraft={selectDraft}
            setDraftForm={setDraftForm}
            setDraftStatusFilter={setDraftStatusFilter}
            setDraftTouchFilter={setDraftTouchFilter}
            setTestEmail={setTestEmail}
            testEmail={testEmail}
            toggleDraft={toggleDraft}
          />
        )}

        {!loading && activeTab === "Queue" && (
          <QueueTab
            handleApproveSelected={handleApproveSelected}
            handleGenerateDue={handleGenerateDue}
            handleRefreshQueue={() => handleRefreshWorkspace("Queue refreshed")}
            handleSendQueueSelected={handleSendQueueSelected}
            queue={queue}
            queueDraftRows={queueDraftRows}
            queueView={queueView}
            selectedDueLeadIds={selectedDueLeadIds}
            selectedQueueDraftIds={selectedQueueDraftIds}
            sentToday={sentToday}
            setQueueView={setQueueView}
            setSelectedDueLeadIds={setSelectedDueLeadIds}
            setSelectedQueueDraftIds={setSelectedQueueDraftIds}
            toggleDueLead={toggleDueLead}
            toggleQueueDraft={toggleQueueDraft}
          />
        )}

        {!loading && activeTab === "Sequence" && (
          <SequenceTab
            handleSaveSequence={handleSaveSequence}
            rules={rules}
            savingSequence={savingSequence}
            steps={steps}
            updateRule={updateRule}
            updateStep={updateStep}
          />
        )}

        {!loading && activeTab === "Activity" && (
          <ActivityTab
            activityFilter={activityFilter}
            filteredActivities={filteredActivities}
            setActivityFilter={setActivityFilter}
          />
        )}

        {!loading && activeTab === "Settings" && (
          <SettingsTab campaign={campaign} campaignName={campaignName} rules={rules} />
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
          leadDrawerTab={leadDrawerTab}
          onClose={() => setLeadDrawer(null)}
          setLeadDrawerTab={setLeadDrawerTab}
        />
      )}

      {previewDraft && (
        <PreviewModal
          draft={previewDraft}
          draftForm={draftForm}
          onClose={() => setPreviewDraft(null)}
        />
      )}
    </>
  )
}

function OverviewTab({ activities, leadCollection, overview, runs, setActiveTab }) {
  const cards = [
    ["total_leads", "Total leads", "ti-users", "Leads"],
    ["with_email", "With email", "ti-at", "Leads"],
    ["needs_enrichment", "Needs enrichment", "ti-database-search", "Leads"],
    ["drafts_generated", "Drafts generated", "ti-mail-edit", "Drafts"],
    ["approved_drafts", "Approved", "ti-circle-check", "Drafts"],
    ["emails_sent", "Emails sent", "ti-send", "Queue"],
    ["followups_due", "Follow-ups due", "ti-clock", "Queue"],
    ["replies", "Replies", "ti-message-reply", "Activity"],
  ]
  const pipeline = [
    ["scraped", "Scraped", overview.pipeline?.scraped ?? overview.total_leads],
    ["enriched", "Enriched", overview.pipeline?.enriched ?? overview.with_email],
    ["drafted", "Drafted", overview.pipeline?.drafted ?? overview.drafts_generated],
    ["approved", "Approved", overview.pipeline?.approved ?? overview.approved_drafts],
    ["sent", "Sent", overview.pipeline?.sent ?? overview.emails_sent],
    ["replied", "Replied", overview.pipeline?.replied ?? overview.replies],
    ["completed", "Completed", overview.pipeline?.completed ?? overview.completed],
  ]

  return (
    <>
      <div className="metric-grid">
        {cards.map(([key, label, icon, tab]) => (
          <button className="metric-card" key={key} onClick={() => setActiveTab(tab)}>
            <span className="metric-icon"><i className={`ti ${icon}`} aria-hidden="true" /></span>
            <strong>{overview[key] ?? 0}</strong>
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="card">
        <div className="card-head"><h2>Pipeline</h2></div>
        <div className="card-body">
          <div className="campaign-pipeline">
            {pipeline.map(([key, label, count], index) => (
              <div className="pipe-card" key={key}>
                <span className="pipe-step">{index + 1}</span>
                <strong>{count || 0}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="workspace-two-col">
        <div className="card">
          <div className="card-head"><h2>Recent source runs</h2></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Source type</th>
                  <th>Status</th>
                  <th>Scraped</th>
                  <th>Unique</th>
                  <th>Duplicates</th>
                  <th>Stop reason</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && <EmptyRow colSpan={8} text="No campaign runs yet." />}
                {runs.slice(0, 8).map((run) => (
                  <tr key={run.id}>
                    <td className="mono">{run.id.slice(0, 8)}</td>
                    <td>Sales Navigator</td>
                    <td><StatusBadge value={run.status} /></td>
                    <td>{run.total_scraped || 0}</td>
                    <td>{leadCollection.unique_leads || "-"}</td>
                    <td>{leadCollection.duplicates_removed || "-"}</td>
                    <td>{run.stop_reason || "-"}</td>
                    <td><Link className="btn xs" to={`/runs/${run.id}`}>View logs</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <ActivityMini activities={activities.slice(0, 10)} />
      </div>
    </>
  )
}

function SourcesTab(props) {
  const {
    handleAddSegment,
    handleCreateUniverse,
    handlePauseAll,
    handleRunAll,
    handleRunNext,
    handleRunSegment,
    handleStartRun,
    selectedUniverse,
    selectedUniverseId,
    segmentForm,
    setSegmentForm,
    setSelectedUniverseId,
    setSourceForm,
    setUniverseForm,
    sourceBusy,
    sourceForm,
    sourceSegments,
    universeForm,
    universes,
    runs,
  } = props

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h2>Start campaign source run</h2>
          <button className="btn primary sm" onClick={handleStartRun} disabled={sourceBusy}>
            <i className="ti ti-player-play" aria-hidden="true" />
            Start run
          </button>
        </div>
        <div className="card-body">
          <div className="source-run-grid">
            <div className="form-group span-2">
              <div className="form-label">Source URL</div>
              <input
                className="form-input"
                value={sourceForm.source_url}
                onChange={(e) => setSourceForm((form) => ({ ...form, source_url: e.target.value }))}
                placeholder="https://www.linkedin.com/sales/search/people..."
              />
            </div>
            <div className="form-group">
              <div className="form-label">Campaign</div>
              <input className="form-input" value="Locked to this campaign" readOnly />
            </div>
            <div className="form-group">
              <div className="form-label">Max leads</div>
              <input
                className="form-input"
                type="number"
                min="1"
                value={sourceForm.max_leads}
                onChange={(e) => setSourceForm((form) => ({ ...form, max_leads: e.target.value }))}
              />
            </div>
          </div>
          <button
            className="plain-toggle"
            type="button"
            onClick={() => setSourceForm((form) => ({ ...form, showAdvanced: !form.showAdvanced }))}
          >
            <i className={`ti ti-chevron-${sourceForm.showAdvanced ? "down" : "right"}`} aria-hidden="true" />
            Advanced settings
          </button>
          {sourceForm.showAdvanced && (
            <div className="source-run-grid">
              <div className="form-group">
                <div className="form-label">Target titles</div>
                <input
                  className="form-input"
                  value={sourceForm.titles}
                  onChange={(e) => setSourceForm((form) => ({ ...form, titles: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <div className="form-label">Locations</div>
                <input
                  className="form-input"
                  value={sourceForm.geos}
                  onChange={(e) => setSourceForm((form) => ({ ...form, geos: e.target.value }))}
                />
              </div>
              <div className="form-group span-2">
                <div className="form-label">Keywords</div>
                <input
                  className="form-input"
                  value={sourceForm.keywords}
                  onChange={(e) => setSourceForm((form) => ({ ...form, keywords: e.target.value }))}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Source runs</h2></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Source URL</th>
                <th>Status</th>
                <th>Requested</th>
                <th>Scraped</th>
                <th>Unique</th>
                <th>Duplicates</th>
                <th>Started</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && <EmptyRow colSpan={9} text="No source runs for this campaign yet." />}
              {runs.map((run) => (
                <tr key={run.id}>
                  <td className="mono">{run.id.slice(0, 8)}</td>
                  <td className="truncate wide">{run.start_url || "-"}</td>
                  <td><StatusBadge value={run.status} /></td>
                  <td>{run.max_leads || "-"}</td>
                  <td>{run.total_scraped || 0}</td>
                  <td>{run.unique_count || "-"}</td>
                  <td>{run.duplicate_count || "-"}</td>
                  <td>{fmtDate(run.started_at)}</td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn xs" to={`/runs/${run.id}`}>View logs</Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Lead universe and source segments</h2>
          <div className="topbar-actions">
            <button className="btn sm" onClick={handleRunNext} disabled={sourceBusy || !selectedUniverse}>Run next</button>
            <button className="btn primary sm" onClick={handleRunAll} disabled={sourceBusy || !selectedUniverse}>Run all queued</button>
            <button className="btn sm" onClick={handlePauseAll} disabled={sourceBusy || !selectedUniverse}>Pause</button>
          </div>
        </div>
        <div className="card-body">
          <div className="source-run-grid">
            <div className="form-group">
              <div className="form-label">Universe</div>
              <select
                className="form-input"
                value={selectedUniverseId}
                onChange={(e) => setSelectedUniverseId(e.target.value)}
              >
                {universes.length === 0 && <option value="">No universe yet</option>}
                {universes.map((universe) => (
                  <option key={universe.id} value={universe.id}>{universe.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <div className="form-label">New universe name</div>
              <input
                className="form-input"
                value={universeForm.name}
                onChange={(e) => setUniverseForm((form) => ({ ...form, name: e.target.value }))}
                placeholder="US CTO search universe"
              />
            </div>
            <div className="form-group">
              <div className="form-label">Target leads</div>
              <input
                className="form-input"
                type="number"
                value={universeForm.target_leads}
                onChange={(e) => setUniverseForm((form) => ({ ...form, target_leads: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <div className="form-label">Description</div>
              <input
                className="form-input"
                value={universeForm.description}
                onChange={(e) => setUniverseForm((form) => ({ ...form, description: e.target.value }))}
              />
            </div>
          </div>
          <button className="btn sm" onClick={handleCreateUniverse} disabled={sourceBusy}>
            <i className="ti ti-database-plus" aria-hidden="true" />
            Create universe
          </button>

          {selectedUniverse && (
            <div className="segment-create">
              <div className="source-run-grid">
                <div className="form-group">
                  <div className="form-label">Segment label</div>
                  <input
                    className="form-input"
                    value={segmentForm.label}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, label: e.target.value }))}
                    placeholder="US CTOs page 1"
                  />
                </div>
                <div className="form-group">
                  <div className="form-label">Target leads</div>
                  <input
                    className="form-input"
                    type="number"
                    value={segmentForm.expected_count}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, expected_count: e.target.value }))}
                  />
                </div>
                <div className="form-group span-2">
                  <div className="form-label">Sales Navigator URL</div>
                  <input
                    className="form-input"
                    value={segmentForm.source_url}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, source_url: e.target.value }))}
                    placeholder="https://www.linkedin.com/sales/search/people..."
                  />
                </div>
              </div>
              <button className="btn sm" onClick={handleAddSegment} disabled={sourceBusy}>
                <i className="ti ti-plus" aria-hidden="true" />
                Add source segment
              </button>
            </div>
          )}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Segment</th>
                <th>Source URL</th>
                <th>Status</th>
                <th>Scraped</th>
                <th>Unique</th>
                <th>Duplicates</th>
                <th>Stop reason</th>
                <th>Last run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sourceSegments.length === 0 && <EmptyRow colSpan={9} text="No source segments yet." />}
              {sourceSegments.map((segment) => (
                <tr key={segment.id}>
                  <td>{segment.label || "-"}</td>
                  <td className="truncate wide">{segment.source_url}</td>
                  <td><StatusBadge value={segment.status} /></td>
                  <td>{segment.scraped_count || 0}</td>
                  <td>{segment.unique_count || 0}</td>
                  <td>{segment.duplicate_count || 0}</td>
                  <td>{segment.stop_reason || "-"}</td>
                  <td>{segment.last_run_id ? <Link to={`/runs/${segment.last_run_id}`}>{segment.last_run_id.slice(0, 8)}</Link> : "-"}</td>
                  <td><button className="btn xs" onClick={() => handleRunSegment(segment.id)} disabled={sourceBusy}>Run</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}

function LeadsTab(props) {
  const {
    allLeadCount,
    draftByLead,
    filteredLeads,
    handleExportZoomInfo,
    handleGenerateDrafts,
    handleMarkLead,
    handleUploadEnriched,
    leadFilter,
    openLeadDrawer,
    selectedEmailLeadIds,
    selectedLeadIds,
    setLeadFilter,
    setSelectedLeadIds,
    toggleLead,
    uploadingEnriched,
  } = props
  const emptyLeadText =
    allLeadCount === 0
      ? "No leads yet. Add a Sales Navigator source in Sources."
      : leadFilter === "needs_enrichment"
        ? "These leads need enrichment before drafts can be generated."
        : "No leads match this filter."

  return (
    <div className="card">
      <div className="card-head">
        <h2>Leads and enrichment</h2>
        <div className="topbar-actions">
          <button className="btn sm" onClick={handleExportZoomInfo}>
            <i className="ti ti-download" aria-hidden="true" />
            Export for ZoomInfo
          </button>
          <label className="btn sm">
            <i className="ti ti-upload" aria-hidden="true" />
            {uploadingEnriched ? "Uploading..." : "Upload enriched file"}
            <input type="file" accept=".csv,.xlsx" style={{ display: "none" }} onChange={handleUploadEnriched} />
          </label>
          <button className="btn sm" onClick={() => setSelectedLeadIds(filteredLeads.filter((lead) => lead.email).slice(0, 5).map((lead) => lead.id))}>Select first 5</button>
          <button className="btn sm" onClick={() => setSelectedLeadIds(filteredLeads.filter((lead) => lead.email).map((lead) => lead.id))}>Select all visible</button>
          <button className="btn sm" onClick={() => setSelectedLeadIds([])}>Clear</button>
          <button
            className="btn primary sm"
            onClick={handleGenerateDrafts}
            disabled={selectedEmailLeadIds.length === 0}
            title={selectedEmailLeadIds.length === 0 ? "Select leads with email first." : ""}
          >
            <i className="ti ti-sparkles" aria-hidden="true" />
            Generate drafts ({selectedEmailLeadIds.length})
          </button>
        </div>
      </div>
      <div className="banner blue table-banner">
        <i className="ti ti-info-circle" aria-hidden="true" />
        <div className="banner-msg">
          Sales Navigator usually does not include email or phone. Export leads for ZoomInfo enrichment, enrich externally, then upload the enriched file here.
        </div>
      </div>
      <div className="filter-row padded">
        {leadFilters.map(([value, label]) => (
          <button
            className={`seg-btn ${leadFilter === value ? "active" : ""}`}
            key={value}
            onClick={() => {
              setLeadFilter(value)
              setSelectedLeadIds([])
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Name</th>
              <th>Company</th>
              <th>Title</th>
              <th>Email</th>
              <th>Phone</th>
              <th>Location</th>
              <th>Segment</th>
              <th>Sequence status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredLeads.length === 0 && <EmptyRow colSpan={10} text={emptyLeadText} />}
            {filteredLeads.map((lead) => {
              const latestDraft = draftByLead.get(lead.id)
              const sequenceStatus = latestDraft?.status || lead.email_sequence_status || "not_started"
              return (
                <tr key={lead.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedLeadIds.includes(lead.id)}
                      disabled={!lead.email}
                      onChange={() => toggleLead(lead.id)}
                    />
                  </td>
                  <td><button className="link-button" onClick={() => openLeadDrawer(lead)}>{lead.full_name || "-"}</button></td>
                  <td className="truncate">{lead.company || "-"}</td>
                  <td className="truncate">{lead.title || "-"}</td>
                  <td className={lead.email ? "blue-text" : "muted"}>{lead.email || "-"}</td>
                  <td>{lead.phone || "-"}</td>
                  <td className="truncate">{lead.location || "-"}</td>
                  <td><StatusBadge value={lead.segment === "NO_EMAIL" ? "NEEDS_ENRICHMENT" : lead.segment} /></td>
                  <td><StatusBadge value={sequenceStatus} /></td>
                  <td>
                    <div className="row-actions">
                      <button className="btn xs" onClick={() => openLeadDrawer(lead)}>View</button>
                      {lead.linkedin_url && <a className="btn xs icon" href={lead.linkedin_url} target="_blank" rel="noreferrer"><i className="ti ti-brand-linkedin" aria-hidden="true" /></a>}
                      <MenuButton lead={lead} handleMarkLead={handleMarkLead} />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function DraftsTab(props) {
  const {
    actionBusy,
    draftForm,
    draftStatusFilter,
    draftTouchFilter,
    filteredDrafts,
    handleApproveDraft,
    handleApproveSelected,
    handlePreviewDraft,
    handleRefreshDrafts,
    handleSaveDraft,
    handleSendSelectedApproved,
    handleSendTest,
    handleSkipDraft,
    selectedDraft,
    selectedDraftId,
    selectedDraftIds,
    selectDraft,
    setDraftForm,
    setDraftStatusFilter,
    setDraftTouchFilter,
    setTestEmail,
    testEmail,
    toggleDraft,
  } = props
  const readOnly = ["sent", "skipped"].includes(selectedDraft?.status)
  const approvedIds = selectedDraftIds.filter((draftId) =>
    filteredDrafts.some((draft) => getDraftId(draft) === draftId && draft.status === "approved"),
  )

  return (
    <div className="draft-workspace">
      <div className="draft-toolbar">
        <div className="topbar-actions">
          <button className="btn sm" onClick={() => handleApproveSelected()} disabled={selectedDraftIds.length === 0}>Approve selected</button>
          <button className="btn primary sm" onClick={() => handleSendSelectedApproved()} disabled={approvedIds.length === 0}>Send selected approved</button>
          <button className="btn sm" onClick={handleRefreshDrafts}>Refresh drafts</button>
        </div>
        <div className="topbar-actions">
          <select className="form-input compact" value={draftStatusFilter} onChange={(e) => setDraftStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {["draft", "approved", "scheduled", "sent", "failed", "skipped"].map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
          <select className="form-input compact" value={draftTouchFilter} onChange={(e) => setDraftTouchFilter(e.target.value)}>
            <option value="">All emails</option>
            {[1, 2, 3].map((touch) => <option key={touch} value={touch}>Email {touch}</option>)}
          </select>
        </div>
      </div>
      <div className="draft-grid">
        <div className="card draft-list">
          <div className="card-head"><h2>Draft review</h2></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Lead</th>
                  <th>Email</th>
                  <th>Plan email</th>
                  <th>Status</th>
                  <th>Subject</th>
                </tr>
              </thead>
              <tbody>
                {filteredDrafts.length === 0 && <EmptyRow colSpan={6} text="No drafts yet. Select enriched leads in Leads and generate drafts." />}
                {filteredDrafts.map((draft) => {
                  const draftId = getDraftId(draft)
                  return (
                    <tr className={selectedDraftId === draftId ? "selected-row" : ""} key={draftId} onClick={() => selectDraft(draft)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selectedDraftIds.includes(draftId)} onChange={() => toggleDraft(draftId)} />
                      </td>
                      <td>
                        <strong>{draft.full_name || "-"}</strong>
                        <div className="muted">{draft.company || "-"}</div>
                      </td>
                      <td className="blue-text">{draft.email || "-"}</td>
                      <td><span className="touch-badge">E{draft.touch_number || 1}</span></td>
                      <td><StatusBadge value={draft.status} /></td>
                      <td className="truncate">{draftSubject(draft) || "-"}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card composer-card">
          <div className="card-head">
            <h2>Email composer</h2>
            {selectedDraft && (
              <div className="topbar-actions">
                <StatusBadge value={selectedDraft.status} />
              </div>
            )}
          </div>
          {!selectedDraft ? (
            <div className="empty-state">Select a draft to review and approve.</div>
          ) : (
            <div className="composer-body">
              <div className="composer-line">
                <span>To</span>
                <div className="email-chip">{selectedDraft.email || "missing email"}</div>
              </div>
              <div className="composer-line">
                <span>From</span>
                <div className="muted">Configured Microsoft Graph sender</div>
              </div>
              <div className="composer-line">
                <span>Context</span>
                <div className="muted">{selectedDraft.title || "Lead"} at {selectedDraft.company || "their company"}</div>
              </div>
              {Number(selectedDraft.touch_number || 1) > 1 && (
                <div className="previous-context">
                  <div className="previous-context-title">Previous email context</div>
                  <LabeledValue label="Previous email subject" value={selectedDraft.previous_subject || "-"} />
                  <LabeledValue label="Previous sent time" value={fmtDate(selectedDraft.previous_sent_at)} />
                  <div className="previous-body-preview">
                    {(selectedDraft.previous_body || "").slice(0, 700) || "No previous email body found."}
                  </div>
                </div>
              )}
              <div className="composer-line">
                <span>Subject</span>
                <input
                  disabled={readOnly}
                  value={draftForm.subject}
                  onChange={(e) => setDraftForm((form) => ({ ...form, subject: e.target.value }))}
                />
              </div>
              <textarea
                className="composer-textarea"
                disabled={readOnly}
                value={draftForm.body}
                onChange={(e) => setDraftForm((form) => ({ ...form, body: e.target.value }))}
              />
              <div className="composer-actions">
                <button className="btn" onClick={handleSaveDraft} disabled={actionBusy || readOnly}>Save</button>
                <button className="btn" onClick={handlePreviewDraft} disabled={!selectedDraft}>Preview</button>
                <button className="btn" onClick={() => handleApproveDraft()} disabled={actionBusy || selectedDraft.status === "sent"}>Approve</button>
                <input className="form-input test-email" placeholder="test@company.com" value={testEmail} onChange={(e) => setTestEmail(e.target.value)} />
                <button className="btn" onClick={handleSendTest} disabled={actionBusy}>Send test</button>
                <button className="btn primary" onClick={() => handleSendSelectedApproved([getDraftId(selectedDraft)])} disabled={selectedDraft.status !== "approved"}>Send approved</button>
                <button className="btn danger" onClick={handleSkipDraft} disabled={actionBusy || readOnly}>Skip</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function QueueTab(props) {
  const {
    handleApproveSelected,
    handleGenerateDue,
    handleRefreshQueue,
    handleSendQueueSelected,
    queue,
    queueDraftRows,
    queueView,
    selectedDueLeadIds,
    selectedQueueDraftIds,
    sentToday,
    setQueueView,
    setSelectedDueLeadIds,
    setSelectedQueueDraftIds,
    toggleDueLead,
    toggleQueueDraft,
  } = props
  const approvedQueueIds = selectedQueueDraftIds.filter((draftId) =>
    queueDraftRows.some((draft) => getDraftId(draft) === draftId && draft.status === "approved"),
  )

  return (
    <>
      <div className="queue-metrics">
        <MetricBox label="Due today" value={queue.due_today?.length || 0} />
        <MetricBox label="Scheduled" value={queue.scheduled?.length || 0} />
        <MetricBox label="Waiting follow-up" value={queue.waiting?.length || 0} />
        <MetricBox label="Failed" value={queue.failed?.length || 0} />
        <MetricBox label="Sent today" value={sentToday} />
      </div>
      <div className="banner blue">
        <i className="ti ti-info-circle" aria-hidden="true" />
        <div className="banner-msg">
          Follow-ups appear here only when delay days have passed and the lead has not replied, bounced, or unsubscribed.
        </div>
      </div>
      <div className="card">
        <div className="card-head">
          <div className="queue-tabs">
            {queueViews.map(([key, label]) => (
              <button className={`workspace-tab ${queueView === key ? "active" : ""}`} key={key} onClick={() => {
                setQueueView(key)
                setSelectedDueLeadIds([])
                setSelectedQueueDraftIds([])
              }}>
                {label}
              </button>
            ))}
          </div>
          <div className="topbar-actions">
            <button className="btn sm" onClick={handleRefreshQueue}>Refresh due queue</button>
            <button className="btn sm" onClick={handleGenerateDue}>Generate due follow-up drafts</button>
            <button className="btn sm" onClick={() => handleApproveSelected(selectedQueueDraftIds)} disabled={selectedQueueDraftIds.length === 0}>Approve selected</button>
            <button className="btn primary sm" onClick={() => handleSendQueueSelected(approvedQueueIds)} disabled={approvedQueueIds.length === 0}>Send selected approved</button>
          </div>
        </div>
        {queueView === "due_today" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Lead</th>
                  <th>Company</th>
                  <th>Email</th>
                  <th>Plan email</th>
                  <th>Due date</th>
                  <th>Status</th>
                  <th>Reason due</th>
                </tr>
              </thead>
              <tbody>
                {(queue.due_today || []).length === 0 && <EmptyRow colSpan={8} text="No follow-ups due. Follow-ups will appear after the configured delay days." />}
                {(queue.due_today || []).map((item) => (
                  <tr key={item.lead_id}>
                    <td><input type="checkbox" checked={selectedDueLeadIds.includes(item.lead_id)} onChange={() => toggleDueLead(item.lead_id)} /></td>
                    <td>{item.full_name || "-"}</td>
                    <td>{item.company || "-"}</td>
                    <td className="blue-text">{item.email || "-"}</td>
                    <td><span className="touch-badge">E{item.touch_number}</span></td>
                    <td>{fmtDate(item.next_touch_due_at)}</td>
                    <td><StatusBadge value={item.status} /></td>
                    <td>{item.due_label || "Due now"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <QueueDraftTable
            rows={queueDraftRows}
            selectedQueueDraftIds={selectedQueueDraftIds}
            toggleQueueDraft={toggleQueueDraft}
          />
        )}
      </div>
    </>
  )
}

function QueueDraftTable({ rows, selectedQueueDraftIds, toggleQueueDraft }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th></th>
            <th>Lead</th>
            <th>Company</th>
            <th>Email</th>
            <th>Plan email</th>
            <th>Subject</th>
            <th>Status</th>
            <th>Sent/due</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && <EmptyRow colSpan={8} text="Nothing in this queue." />}
          {rows.map((draft) => {
            const draftId = getDraftId(draft)
            return (
              <tr key={draftId || draft.lead_id}>
                <td>{draftId && <input type="checkbox" checked={selectedQueueDraftIds.includes(draftId)} onChange={() => toggleQueueDraft(draftId)} />}</td>
                <td>{draft.full_name || "-"}</td>
                <td>{draft.company || "-"}</td>
                <td className="blue-text">{draft.email || "-"}</td>
                <td><span className="touch-badge">E{draft.touch_number || "-"}</span></td>
                <td className="truncate">{draftSubject(draft) || "-"}</td>
                <td><StatusBadge value={draft.status} /></td>
                <td>{draft.due_label || fmtDate(draft.sent_at || draft.scheduled_for || draft.next_touch_due_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SequenceTab({ handleSaveSequence, rules, savingSequence, steps, updateRule, updateStep }) {
  const mode = rules.mode === "autopilot" ? "autopilot" : "review"
  const detectedTimezone = getDetectedTimezone()
  const selectedTimezone = rules.timezone || detectedTimezone
  const setSendingMode = (nextMode) => {
    updateRule("mode", nextMode)
    updateRule("require_approval_for_followups", nextMode !== "autopilot")
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
          <div className="sequence-mode-grid">
            <label className="sequence-mode-option">
              <input
                type="radio"
                name="sequence-sending-choice"
                checked={mode !== "autopilot"}
                onChange={() => setSendingMode("review")}
              />
              <span>
                <strong>Review each email before sending</strong>
                <small>Follow-ups appear in Queue for a person to review and send.</small>
              </span>
            </label>
            <label className="sequence-mode-option">
              <input
                type="radio"
                name="sequence-sending-choice"
                checked={mode === "autopilot"}
                onChange={() => setSendingMode("autopilot")}
              />
              <span>
                <strong>Auto-send approved follow-ups when due</strong>
                <small>The scheduler may send follow-ups automatically when they are due.</small>
              </span>
            </label>
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

function ActivityTab({ activityFilter, filteredActivities, setActivityFilter }) {
  return (
    <div className="card">
      <div className="card-head">
        <h2>Campaign activity</h2>
        <div className="filter-row no-margin">
          {activityFilters.map(([value, label]) => (
            <button className={`seg-btn ${activityFilter === value ? "active" : ""}`} key={value} onClick={() => setActivityFilter(value)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <ActivityTimeline activities={filteredActivities} />
    </div>
  )
}

function SettingsTab({ campaign, campaignName, rules }) {
  return (
    <div className="settings-grid">
      <div className="card">
        <div className="card-head"><h2>Campaign profile</h2></div>
        <div className="card-body">
          <LabeledValue label="Campaign name" value={campaignName} />
          <LabeledValue label="Description" value={campaign?.description || "-"} />
          <LabeledValue label="Target persona" value={(campaign?.target_personas || []).join(", ") || "-"} />
          <LabeledValue label="Value proposition" value={campaign?.email_goal || "book a 20-minute discovery call"} />
          <LabeledValue label="Knowledge bases" value={(campaign?.knowledge_bases || []).join(", ") || "-"} />
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h2>Sending defaults</h2></div>
        <div className="card-body">
          <LabeledValue label="Sender name" value={import.meta.env.VITE_SENDER_NAME || "Royal Cyber Team"} />
          <LabeledValue label="Sender email / reply-to" value={import.meta.env.VITE_SENDER_EMAIL || "Configured in backend .env"} />
          <LabeledValue label="Email provider" value="Microsoft Graph" />
          <LabeledValue label="Daily send limit" value={rules.daily_send_limit} />
          <LabeledValue label="Send window" value={`${rules.send_window_start} to ${rules.send_window_end}`} />
          <LabeledValue label="ACS Email" value="Placeholder / future provider" />
        </div>
      </div>
    </div>
  )
}

function LeadDrawer(props) {
  const {
    draftByLead,
    drafts,
    handleGenerateDrafts,
    handleMarkLead,
    lead,
    leadActivities,
    leadDrawerTab,
    onClose,
    setLeadDrawerTab,
  } = props
  const latestDraft = draftByLead.get(lead.id)

  return (
    <div className="drawer-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="lead-drawer">
        <div className="drawer-head">
          <div>
            <h2>{lead.full_name || "Lead"}</h2>
            <p>{lead.title || "-"} at {lead.company || "-"}</p>
          </div>
          <button className="btn icon" onClick={onClose}><i className="ti ti-x" aria-hidden="true" /></button>
        </div>
        <div className="drawer-tabs">
          {["Overview", "Drafts", "Activity"].map((tab) => (
            <button className={`workspace-tab ${leadDrawerTab === tab ? "active" : ""}`} key={tab} onClick={() => setLeadDrawerTab(tab)}>{tab}</button>
          ))}
        </div>
        {leadDrawerTab === "Overview" && (
          <div className="drawer-body">
            <LabeledValue label="Email" value={lead.email || "-"} />
            <LabeledValue label="Phone" value={lead.phone || "-"} />
            <LabeledValue label="Location" value={lead.location || "-"} />
            <LabeledValue label="LinkedIn URL" value={lead.linkedin_url || "-"} />
            <LabeledValue label="Segment" value={lead.segment || "-"} />
            <LabeledValue label="Sequence status" value={latestDraft?.status || lead.email_sequence_status || "not_started"} />
            <LabeledValue label="Last email sent" value={fmtDate(latestDraft?.sent_at)} />
            <LabeledValue label="Next follow-up due" value={fmtDate(lead.next_touch_due_at)} />
            <LabeledValue label="Stop reason" value={lead.stop_reason || "-"} />
            <div className="drawer-actions">
              <button className="btn primary" onClick={handleGenerateDrafts} disabled={!lead.email}>Generate draft</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "replied")}>Mark replied</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "bounced")}>Mark bounced</button>
              <button className="btn" onClick={() => handleMarkLead(lead.id, "unsubscribed")}>Mark unsubscribed</button>
              <button className="btn danger" onClick={() => handleMarkLead(lead.id, "do_not_contact")}>Do not contact</button>
            </div>
          </div>
        )}
        {leadDrawerTab === "Drafts" && (
          <div className="drawer-body">
            {drafts.length === 0 && <div className="empty-state">No drafts generated for this lead.</div>}
            {drafts.map((draft) => (
              <div className="mini-draft-card" key={getDraftId(draft)}>
                <div>
                  <span className="touch-badge">Email {draft.touch_number}</span>
                  <StatusBadge value={draft.status} />
                </div>
                <strong>{draftSubject(draft) || "No subject"}</strong>
                <p>{draftBody(draft).slice(0, 180)}</p>
              </div>
            ))}
          </div>
        )}
        {leadDrawerTab === "Activity" && (
          <ActivityTimeline activities={leadActivities} compact />
        )}
      </aside>
    </div>
  )
}

function PreviewModal({ draft, draftForm, onClose }) {
  return (
    <div className="modal-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal modal-wide preview-modal">
        <div className="modal-head">
          <h2>Email preview</h2>
          <button className="btn icon" onClick={onClose}><i className="ti ti-x" aria-hidden="true" /></button>
        </div>
        <div className="modal-body">
          <div className="preview-meta">
            <LabeledValue label="Recipient" value={draft.email || "-"} />
            <LabeledValue label="Sender" value={import.meta.env.VITE_SENDER_EMAIL || "Configured Microsoft Graph sender"} />
            <LabeledValue label="Plan email" value={`Email ${draft.touch_number || 1}`} />
            <LabeledValue label="Status" value={draft.status || "draft"} />
          </div>
          <div className="preview-subject">{draftForm.subject || "No subject"}</div>
          <pre className="preview-body">{draftForm.body || "No body"}</pre>
        </div>
      </div>
    </div>
  )
}

function ActivityMini({ activities }) {
  return (
    <div className="card">
      <div className="card-head"><h2>Recent activity</h2></div>
      <ActivityTimeline activities={activities} compact />
    </div>
  )
}

function ActivityTimeline({ activities, compact = false }) {
  return (
    <div className={`activity-timeline ${compact ? "compact" : ""}`}>
      {activities.length === 0 && <div className="empty-state">No activity yet.</div>}
      {activities.map((activity, idx) => (
        <div className="activity-row" key={activity.id || `${activity.created_at}-${idx}`}>
          <div className={`activity-icon ${activityBucket(activity.activity_type)}`}>
            <i className="ti ti-point" aria-hidden="true" />
          </div>
          <div>
            <div className="activity-title">
              <strong>{activity.full_name || activity.lead_name || activity.title || activity.activity_type}</strong>
              <StatusBadge value={activity.activity_type} />
            </div>
            <p>{activity.description || activity.title || "-"}</p>
            <time>{fmtDate(activity.created_at)}</time>
          </div>
        </div>
      ))}
    </div>
  )
}

function MenuButton({ lead, handleMarkLead }) {
  return (
    <details className="row-menu">
      <summary className="btn xs">Status</summary>
      <div className="row-menu-pop">
        <button onClick={() => handleMarkLead(lead.id, "replied")}>Mark replied</button>
        <button onClick={() => handleMarkLead(lead.id, "bounced")}>Mark bounced</button>
        <button onClick={() => handleMarkLead(lead.id, "unsubscribed")}>Mark unsubscribed</button>
        <button onClick={() => handleMarkLead(lead.id, "do_not_contact")}>Do not contact</button>
      </div>
    </details>
  )
}

function MetricBox({ label, value }) {
  return (
    <div className="metric-card static">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}

function StatusBadge({ value }) {
  return <span className={`badge ${statusClass(value)}`}>{statusText(value)}</span>
}

function EmptyRow({ colSpan, text }) {
  return (
    <tr>
      <td colSpan={colSpan} className="empty-cell">{text}</td>
    </tr>
  )
}

function LabeledValue({ label, value }) {
  return (
    <div className="labeled-value">
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  )
}

function LabeledInput({ label, onChange, type = "text", value }) {
  return (
    <div className="form-group">
      <div className="form-label">{label}</div>
      <input className="form-input" type={type} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  )
}
