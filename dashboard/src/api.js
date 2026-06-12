import axios from "axios"

const BASE = import.meta.env.VITE_API_BASE || ""
const WS_BASE = import.meta.env.VITE_WS_BASE || window.location.origin.replace(/^http/, "ws")
const API_KEY = import.meta.env.VITE_API_KEY || ""

const client = axios.create({
  baseURL: BASE,
  headers: { "X-API-Key": API_KEY },
})

const wsUrl = (path) => {
  const base = WS_BASE.replace(/\/$/, "")
  const separator = path.includes("?") ? "&" : "?"
  return `${base}${path}${separator}api_key=${encodeURIComponent(API_KEY)}`
}

export async function downloadFile(path, filename) {
  const resp = await client.get(path, { responseType: "blob" })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const friendlyMessage = (err) => err.response?.data?.detail || err.message

export const getDashboardSummary = () => client.get("/api/dashboard/summary")
export const getRun = (id) => client.get(`/api/runs/${id}`)
export const startRun = (body) => client.post("/api/runs/start", body)
export const getRunLeads = (id, params) => client.get(`/api/runs/${id}/leads`, { params })
export const getRunEvents = (id) => client.get(`/api/runs/${id}/events`)
export const exportRun = (id) => client.get(`/api/runs/${id}/leads/export`)
export const uploadEnrichedCsv = (id, file) => {
  const form = new FormData()
  form.append("file", file)
  return client.post(`/api/runs/${id}/leads/upload-enriched`, form)
}
export const getCampaigns = () => client.get("/api/campaigns")
export const getCampaignOverview = (filename) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/overview`)

export const getCampaignReport = (filename, params = {}) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/report`, { params })

export const getCampaignsSummary = () =>
  client.get("/api/campaigns/summary")

export const getCampaignLeads = (filename, params = {}) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/leads`, { params })
export const generateCampaignDrafts = (filename, data) =>
  client.post(`/api/campaigns/${encodeURIComponent(filename)}/drafts/generate`, data)
export const getCampaignDrafts = (filename, params = {}) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/drafts`, { params })
export const updateOutreachDraft = (draftId, data) =>
  client.put(`/api/drafts/${draftId}`, data)
export const approveDraft = (draftId) =>
  client.post(`/api/drafts/${draftId}/approve`)
export const approveSelectedDrafts = (draftIdsOrBody) =>
  client.post(
    "/api/drafts/approve-selected",
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const skipDraft = (draftId, reasonOrBody = "") =>
  client.post(
    `/api/drafts/${draftId}/skip`,
    typeof reasonOrBody === "string" ? { reason: reasonOrBody } : reasonOrBody,
  )
export const sendSelectedDrafts = (draftIdsOrBody) =>
  client.post(
    "/api/drafts/send-selected",
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const sendDraftTest = (draftId, testEmailOrBody) =>
  client.post(
    `/api/drafts/${draftId}/send-test`,
    typeof testEmailOrBody === "string"
      ? { test_email: testEmailOrBody }
      : testEmailOrBody,
  )
export const getCampaignQueue = (filename) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/queue`)
export const generateDueDrafts = (filename, data = {}) =>
  client.post(`/api/campaigns/${encodeURIComponent(filename)}/queue/generate-due`, data)
export const sendCampaignQueueSelected = (filename, draftIdsOrBody) =>
  client.post(
    `/api/campaigns/${encodeURIComponent(filename)}/queue/send-selected`,
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const getCampaignActivities = (filename, params = {}) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/activities`, { params })
export const getLeadActivities = (leadId, params = {}) =>
  client.get(`/api/leads/${leadId}/activities`, { params })
export const markLeadReplied = (leadId, data) =>
  client.post(`/api/leads/${leadId}/mark-replied`, data)
export const markLeadBounced = (leadId, data) =>
  client.post(`/api/leads/${leadId}/mark-bounced`, data)
export const markLeadUnsubscribed = (leadId, data) =>
  client.post(`/api/leads/${leadId}/mark-unsubscribed`, data)
export const markLeadDoNotContact = (leadId, data) =>
  client.post(`/api/leads/${leadId}/mark-do-not-contact`, data)
export const uploadCampaignEnriched = (filename, file) => {
  const form = new FormData()
  form.append("file", file)
  return client.post(
    `/api/campaigns/${encodeURIComponent(filename)}/upload-enriched`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  )
}
export const verifyCampaignEmails = (filename, params = {}) =>
  client
    .post(`/api/campaigns/${encodeURIComponent(filename)}/verify-emails`, null, {
      params,
    })
    .then((response) => response.data)
export const getCampaignRuns = (filename) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/runs`)
export const getCampaignLeadUniverses = (filename) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/lead-universes`)
export const createLeadUniverse = (data) =>
  client.post("/api/lead-universes", data)
export const addLeadSourceSegment = (universeId, data) =>
  client.post(`/api/lead-universes/${universeId}/segments`, data)
export const runLeadSourceSegment = (segmentId) =>
  client.post(`/api/segments/${segmentId}/run`)
export const runNextLeadSourceSegment = (universeId) =>
  client.post(`/api/lead-universes/${universeId}/run-next`)
export const runAllLeadSourceSegments = (universeId) =>
  client.post(`/api/lead-universes/${universeId}/run-all`)
export const pauseLeadSourceSegments = (universeId) =>
  client.post(`/api/lead-universes/${universeId}/pause-all`)
export const getSequenceSettings = (filename) =>
  client.get(`/api/campaigns/${encodeURIComponent(filename)}/sequence-settings`)
export const saveSequenceSettings = (filename, data) =>
  client.post(`/api/campaigns/${encodeURIComponent(filename)}/sequence-settings`, data)
export const getKnowledgeBases = () => client.get("/api/knowledge-bases")
export const uploadKnowledgeBase = (file) => {
  const form = new FormData()
  form.append("file", file)
  return client.post("/api/knowledge-bases/upload", form)
}
export const getSchedulerStatus = () => client.get("/api/scheduler/status")
export const getSendPolicyStatus = () => client.get("/api/send-policy/status")

export const updateCampaign = (filename, data) =>
  client.patch(`/api/campaigns/${encodeURIComponent(filename)}`, data)

export const createCampaign = (data) =>
  client.post("/api/campaigns", data)
export const loadSettings = () =>
  client.get("/api/settings")
export const saveSettings = (data) =>
  client.post("/api/settings", data)
export const testSettingsEmail = () =>
  client.post("/api/settings/test-email")
export const getJob = (id) => client.get(`/api/jobs/${id}`)
export const getJobs = (limit = 20) => client.get("/api/jobs", { params: { limit } })
export const cancelJob = (id) => client.post(`/api/jobs/${id}/cancel`)
export const openWS = (runId, onMsg) => {
  const ws = new WebSocket(wsUrl(`/ws/runs/${runId}`))
  ws.onmessage = (e) => onMsg(JSON.parse(e.data))
  return ws
}

export default client
