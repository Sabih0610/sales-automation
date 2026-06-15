import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import * as api from "./api"

const unwrap = (request) => request.then((res) => res.data)

const invalidateCampaign = (qc, filename) => {
  if (filename) qc.invalidateQueries({ queryKey: ["campaign", filename] })
  qc.invalidateQueries({ queryKey: ["campaigns"] })
  qc.invalidateQueries({ queryKey: ["dashboard"] })
}

const invalidateRun = (qc, runId) => {
  if (runId) qc.invalidateQueries({ queryKey: ["run", runId] })
  qc.invalidateQueries({ queryKey: ["dashboard"] })
}

export const useDashboardSummary = () =>
  useQuery({
    queryKey: ["dashboard"],
    queryFn: () => unwrap(api.getDashboardSummary()),
    refetchInterval: 60000,
  })

export const useCampaigns = () =>
  useQuery({ queryKey: ["campaigns"], queryFn: () => unwrap(api.getCampaigns()) })

export const useCampaignOverview = (filename) =>
  useQuery({
    queryKey: ["campaign", filename, "overview"],
    queryFn: () => unwrap(api.getCampaignOverview(filename)),
    enabled: !!filename,
  })

export const useCampaignLeads = (filename, params) =>
  useQuery({
    queryKey: ["campaign", filename, "leads", params],
    queryFn: () => unwrap(api.getCampaignLeads(filename, params)),
    enabled: !!filename,
    placeholderData: (prev) => prev,
  })

export const useCampaignDrafts = (filename, params = {}) =>
  useQuery({
    queryKey: ["campaign", filename, "drafts", params],
    queryFn: () => unwrap(api.getCampaignDrafts(filename, params)),
    enabled: !!filename,
    placeholderData: (prev) => prev,
  })

export const useCampaignActivities = (filename, params = {}) =>
  useQuery({
    queryKey: ["campaign", filename, "activities", params],
    queryFn: () => unwrap(api.getCampaignActivities(filename, params)),
    enabled: !!filename,
    placeholderData: (prev) => prev,
  })

export const useCampaignRuns = (filename) =>
  useQuery({
    queryKey: ["campaign", filename, "runs"],
    queryFn: () => unwrap(api.getCampaignRuns(filename)),
    enabled: !!filename,
  })

export const useCampaignLeadUniverses = (filename) =>
  useQuery({
    queryKey: ["campaign", filename, "universes"],
    queryFn: () => unwrap(api.getCampaignLeadUniverses(filename)),
    enabled: !!filename,
  })

export const useCampaignQueue = (filename) =>
  useQuery({
    queryKey: ["campaign", filename, "queue"],
    queryFn: () => unwrap(api.getCampaignQueue(filename)),
    enabled: !!filename,
    refetchInterval: 30000,
  })

export const useSequenceSettings = (filename) =>
  useQuery({
    queryKey: ["campaign", filename, "sequence-settings"],
    queryFn: () => unwrap(api.getSequenceSettings(filename)),
    enabled: !!filename,
  })

export const useRun = (id) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => unwrap(api.getRun(id)),
    enabled: !!id,
    refetchInterval: 3000,
  })

export const useRunLeads = (id, params = {}) =>
  useQuery({
    queryKey: ["run", id, "leads", params],
    queryFn: () => unwrap(api.getRunLeads(id, params)),
    enabled: !!id,
    placeholderData: (prev) => prev,
  })

export const useRunEvents = (id) =>
  useQuery({
    queryKey: ["run", id, "events"],
    queryFn: () => unwrap(api.getRunEvents(id)),
    enabled: !!id,
  })

export const useSchedulerStatus = () =>
  useQuery({
    queryKey: ["scheduler-status"],
    queryFn: () => unwrap(api.getSchedulerStatus()),
    refetchInterval: 60000,
  })

export const useSendPolicyStatus = () =>
  useQuery({
    queryKey: ["send-policy-status"],
    queryFn: () => unwrap(api.getSendPolicyStatus()),
    refetchInterval: 60000,
  })

export const useKnowledgeBases = () =>
  useQuery({ queryKey: ["knowledge-bases"], queryFn: () => unwrap(api.getKnowledgeBases()) })

export const useLeadActivities = (leadId, params = {}) =>
  useQuery({
    queryKey: ["lead", leadId, "activities", params],
    queryFn: () => unwrap(api.getLeadActivities(leadId, params)),
    enabled: !!leadId,
    placeholderData: (prev) => prev,
  })

export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => unwrap(api.loadSettings()) })

export const useJob = (id) =>
  useQuery({
    queryKey: ["job", id],
    queryFn: () => unwrap(api.getJob(id)),
    enabled: !!id,
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status) ? 2000 : false,
  })

export const useJobs = (limit = 20) =>
  useQuery({
    queryKey: ["jobs", limit],
    queryFn: () => unwrap(api.getJobs(limit)),
    refetchInterval: (query) => {
      const jobs = query.state.data || []
      return jobs.some((job) =>
        ["queued", "running"].includes(String(job.status || "").toLowerCase()),
      )
        ? 2000
        : false
    },
  })

export const useCreateCampaign = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createCampaign,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaigns"] })
      qc.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}


export const useDeleteCampaign = () => {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: api.deleteCampaign,
    onSuccess: (_data, filename) => {
      qc.removeQueries({ queryKey: ["campaign", filename] })
      qc.invalidateQueries({ queryKey: ["campaigns"] })
      qc.invalidateQueries({ queryKey: ["dashboard"] })
    },
  })
}

export const useUploadKnowledgeBase = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.uploadKnowledgeBase,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge-bases"] }),
  })
}


export const useBulkScrapeJobs = (limit = 20) =>
  useQuery({
    queryKey: ["bulk-scrape", limit],
    queryFn: () => unwrap(api.getBulkScrapeJobs(limit)),
    refetchInterval: (query) => {
      const jobs = query.state.data || []
      return jobs.some((job) => ["queued", "running"].includes(job.status)) ? 3000 : 15000
    },
  })

export const useStartBulkScrape = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.startBulkScrape,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bulk-scrape"] })
      invalidateCampaign(qc, filename)
    },
  })
}

export const usePauseBulkScrapeJob = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.pauseBulkScrapeJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bulk-scrape"] }),
  })
}

export const useResumeBulkScrapeJob = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.resumeBulkScrapeJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bulk-scrape"] }),
  })
}

export const useCancelBulkScrapeJob = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.cancelBulkScrapeJob,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bulk-scrape"] }),
  })
}

export const useStartRun = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.startRun,
    onSuccess: () => invalidateRun(qc),
  })
}

export const useStopRun = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.stopRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", filename, "runs"] })
      qc.invalidateQueries({ queryKey: ["bulk-scrape"] })
      invalidateCampaign(qc, filename)
    },
  })
}

export const useDeleteRun = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", filename, "runs"] })
      invalidateCampaign(qc, filename)
    },
  })
}

export const useExportRun = () =>
  useMutation({ mutationFn: api.exportRun })

export const useUploadRunEnriched = (runId) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file) => api.uploadEnrichedCsv(runId, file),
    onSuccess: () => invalidateRun(qc, runId),
  })
}

export const useUploadCampaignEnriched = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file) => api.uploadCampaignEnriched(filename, file),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useVerifyCampaignEmails = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ only_missing = true, limit = 500 } = {}) =>
      api.verifyCampaignEmails(filename, { only_missing, limit }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", filename] })
      qc.invalidateQueries({ queryKey: ["campaign", filename, "leads"] })
    },
  })
}

export const useGenerateDrafts = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => api.generateCampaignDrafts(filename, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useGenerateDue = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => api.generateDueDrafts(filename, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useUpdateDraft = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ draftId, data }) => api.updateOutreachDraft(draftId, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useApproveDraft = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.approveDraft,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useApproveSelected = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.approveSelectedDrafts,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useSkipDraft = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ draftId, reasonOrBody = "" }) => api.skipDraft(draftId, reasonOrBody),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useSendSelected = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.sendSelectedDrafts,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useScheduleApprovedDrafts = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (draftIdsOrBody) => api.scheduleApprovedDrafts(filename, draftIdsOrBody),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useScheduleSendDrafts = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api.scheduleSendDrafts(filename, body),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useApproveScheduleDrafts = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body) => api.approveScheduleDrafts(filename, body),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useDeleteDraft = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.deleteDraft,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}


export const useUpdateCampaign = (filename) => {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: (data) => api.updateCampaign(filename, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useCampaignReport = (filename, days = 30) =>
  useQuery({
    queryKey: ["campaign", filename, "report", days],
    queryFn: () => unwrap(api.getCampaignReport(filename, { days })),
    enabled: !!filename,
    placeholderData: (prev) => prev,
  })

export const useCampaignsSummary = () =>
  useQuery({
    queryKey: ["campaigns", "summary"],
    queryFn: () => unwrap(api.getCampaignsSummary()),
  })






export const useSendCampaignQueueSelected = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (draftIdsOrBody) => api.sendCampaignQueueSelected(filename, draftIdsOrBody),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useSendDraftTest = () =>
  useMutation({
    mutationFn: ({ draftId, testEmailOrBody }) => api.sendDraftTest(draftId, testEmailOrBody),
  })

export const useSaveSequenceSettings = (filename) => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data) => api.saveSequenceSettings(filename, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

const leadStatusMutations = {
  replied: api.markLeadReplied,
  bounced: api.markLeadBounced,
  unsubscribed: api.markLeadUnsubscribed,
  do_not_contact: api.markLeadDoNotContact,
}

export const useMarkLeadStatus = (kind, filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ leadId, data }) => leadStatusMutations[kind](leadId, data),
    onSuccess: (_data, variables) => {
      invalidateCampaign(qc, filename)
      qc.invalidateQueries({ queryKey: ["lead", variables?.leadId] })
      qc.invalidateQueries({ queryKey: ["leads"] })
    },
  })
}

export const useCreateLeadUniverse = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createLeadUniverse,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useAddLeadSourceSegment = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ universeId, data }) => api.addLeadSourceSegment(universeId, data),
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useRunLeadSourceSegment = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.runLeadSourceSegment,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useRunNextLeadSourceSegment = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.runNextLeadSourceSegment,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useRunAllLeadSourceSegments = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.runAllLeadSourceSegments,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const usePauseLeadSourceSegments = (filename = "") => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.pauseLeadSourceSegments,
    onSuccess: () => invalidateCampaign(qc, filename),
  })
}

export const useSaveSettings = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.saveSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  })
}

export const useTestSettingsEmail = () =>
  useMutation({ mutationFn: api.testSettingsEmail })

export const useCancelJob = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.cancelJob,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["job", id] })
      qc.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
}
