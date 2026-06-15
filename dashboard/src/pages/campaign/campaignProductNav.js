export const campaignProductSections = (filename = "") => {
  const safeFilename = encodeURIComponent(filename || "")
  const base = safeFilename ? `/campaigns/${safeFilename}` : "#"

  return [
    {
      label: "Campaign",
      items: [
        ["Overview", "ti-layout-dashboard", `${base}/overview`],
        ["Leads", "ti-users", `${base}/leads`],
        ["Sequences", "ti-mail-bolt", `${base}/sequences`],
        ["Drafts", "ti-mail-check", `${base}/drafts`],
        ["Reports", "ti-report-analytics", `${base}/reports`],
        ["Settings", "ti-settings", `${base}/settings`],
      ],
    },
  ]
}
