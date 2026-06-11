import axios from "axios"

const BASE = "http://localhost:8000/api"
const WS_BASE = "ws://localhost:8000"

const api = axios.create({ baseURL: BASE })

export const getRuns = () => api.get("/runs")
export const getRun = (id) => api.get(`/runs/${id}`)
export const startRun = (body) => api.post("/runs/start", body)
export const getRunLeads = (id, params) => api.get(`/runs/${id}/leads`, { params })
export const getRunEvents = (id) => api.get(`/runs/${id}/events`)
export const exportRun = (id) => api.get(`/runs/${id}/leads/export`)
export const getEmailStatus = (id) => api.get(`/runs/${id}/email-status`)
export const getEmailPreview = (runId) =>
  api.get(`/runs/${runId}/email-preview`)
export const personaliseRun = (runId, body) =>
  api.post(`/runs/${runId}/personalise`, body)
export const getDrafts = (runId, campaignName = "") =>
  api.get(`/runs/${runId}/drafts`, {
    params: campaignName ? { campaign_name: campaignName } : {},
  })
export const updateDraft = (runId, leadId, body) =>
  api.post(`/runs/${runId}/drafts/${leadId}/update`, body)
export const sendTestCopy = (runId, leadId, body) =>
  api.post(`/runs/${runId}/drafts/${leadId}/send-test-copy`, body)
export const sendEmails = (runId, leadIds = []) =>
  api.post(`/runs/${runId}/send-emails`, { lead_ids: leadIds })
export const downloadForZoominfo = (id) => `${BASE}/runs/${id}/leads/download-for-zoominfo`
export const uploadEnrichedCsv = (id, file) => {
  const form = new FormData()
  form.append("file", file)
  return api.post(`/runs/${id}/leads/upload-enriched`, form)
}
export const getCampaigns = () => api.get("/campaigns")
export const getCampaignOverview = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/overview`)
export const getCampaignLeads = (filename, params = {}) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/leads`, { params })
export const generateCampaignDrafts = (filename, data) =>
  api.post(`/campaigns/${encodeURIComponent(filename)}/drafts/generate`, data)
export const getCampaignDrafts = (filename, params = {}) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/drafts`, { params })
export const updateOutreachDraft = (draftId, data) =>
  api.put(`/drafts/${draftId}`, data)
export const approveDraft = (draftId) =>
  api.post(`/drafts/${draftId}/approve`)
export const approveSelectedDrafts = (draftIdsOrBody) =>
  api.post(
    "/drafts/approve-selected",
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const skipDraft = (draftId, reasonOrBody = "") =>
  api.post(
    `/drafts/${draftId}/skip`,
    typeof reasonOrBody === "string" ? { reason: reasonOrBody } : reasonOrBody,
  )
export const sendSelectedDrafts = (draftIdsOrBody) =>
  api.post(
    "/drafts/send-selected",
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const sendDraftTest = (draftId, testEmailOrBody) =>
  api.post(
    `/drafts/${draftId}/send-test`,
    typeof testEmailOrBody === "string"
      ? { test_email: testEmailOrBody }
      : testEmailOrBody,
  )
export const getCampaignQueue = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/queue`)
export const generateDueDrafts = (filename, data = {}) =>
  api.post(`/campaigns/${encodeURIComponent(filename)}/queue/generate-due`, data)
export const sendCampaignQueueSelected = (filename, draftIdsOrBody) =>
  api.post(
    `/campaigns/${encodeURIComponent(filename)}/queue/send-selected`,
    Array.isArray(draftIdsOrBody) ? { draft_ids: draftIdsOrBody } : draftIdsOrBody,
  )
export const getCampaignActivities = (filename, params = {}) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/activities`, { params })
export const getLeadActivities = (leadId, params = {}) =>
  api.get(`/leads/${leadId}/activities`, { params })
export const markLeadReplied = (leadId, data) =>
  api.post(`/leads/${leadId}/mark-replied`, data)
export const markLeadBounced = (leadId, data) =>
  api.post(`/leads/${leadId}/mark-bounced`, data)
export const markLeadUnsubscribed = (leadId, data) =>
  api.post(`/leads/${leadId}/mark-unsubscribed`, data)
export const markLeadDoNotContact = (leadId, data) =>
  api.post(`/leads/${leadId}/mark-do-not-contact`, data)
export const exportCampaignZoomInfo = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/export-zoominfo`, {
    responseType: "blob",
  })
export const uploadCampaignEnriched = (filename, file) => {
  const form = new FormData()
  form.append("file", file)
  return api.post(
    `/campaigns/${encodeURIComponent(filename)}/upload-enriched`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  )
}
export const getCampaignRuns = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/runs`)
export const getCampaignLeadUniverses = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/lead-universes`)
export const createLeadUniverse = (data) =>
  api.post("/lead-universes", data)
export const addLeadSourceSegment = (universeId, data) =>
  api.post(`/lead-universes/${universeId}/segments`, data)
export const runLeadSourceSegment = (segmentId) =>
  api.post(`/segments/${segmentId}/run`)
export const runNextLeadSourceSegment = (universeId) =>
  api.post(`/lead-universes/${universeId}/run-next`)
export const runAllLeadSourceSegments = (universeId) =>
  api.post(`/lead-universes/${universeId}/run-all`)
export const pauseLeadSourceSegments = (universeId) =>
  api.post(`/lead-universes/${universeId}/pause-all`)
export const getSequenceSettings = (filename) =>
  api.get(`/campaigns/${encodeURIComponent(filename)}/sequence-settings`)
export const saveSequenceSettings = (filename, data) =>
  api.post(`/campaigns/${encodeURIComponent(filename)}/sequence-settings`, data)
export const getKnowledgeBases = () => api.get("/knowledge-bases")
export const uploadKnowledgeBase = (file) => {
  const form = new FormData()
  form.append("file", file)
  return api.post("/knowledge-bases/upload", form)
}
export const getAllLeads = (params) => api.get("/leads", { params })
export const getStats = () => api.get("/stats")
export const sendEmailsAll = (campaign) => api.post("/sequences/send", { campaign })
export const getSequenceStats = () => api.get("/sequences/stats")
export const updateEmailContent = (leadId, data) =>
  api.put(`/leads/${leadId}/email-content`, data)
export const sendSingleEmail = (leadId) =>
  api.post(`/leads/${leadId}/send-email`)
export const createCampaign = (data) =>
  api.post("/campaigns", data)
export const loadSettings = () =>
  api.get("/settings")
export const openWS = (runId, onMsg) => {
  const ws = new WebSocket(`${WS_BASE}/ws/runs/${runId}`)
  ws.onmessage = (e) => onMsg(JSON.parse(e.data))
  return ws
}

export default api
