import { useCallback, useMemo } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { useToast } from "../../components/ToastProvider"
import { useCampaignOverview, useCampaigns } from "../../queries"
import ActivityTab from "./ActivityTab.jsx"
import DraftsTab from "./DraftsTab.jsx"
import LeadsTab from "./LeadsTab.jsx"
import OverviewTab from "./OverviewTab.jsx"
import QueueTab from "./QueueTab.jsx"
import SequenceTab from "./SequenceTab.jsx"
import SettingsTab from "./SettingsTab.jsx"
import SourcesTab from "./SourcesTab.jsx"
import { emptyOverview, tabLabels, tabs } from "./utils.jsx"

import ReportsTab from "./ReportsTab.jsx"

const normalizeTab = (value) => {
  const slug = String(value || "overview").toLowerCase()
  return tabLabels[slug] ? slug : "overview"
}

export default function CampaignDetail() {
  const { filename: encodedFilename, tab } = useParams()
  const filename = decodeURIComponent(encodedFilename || "")
  const navigate = useNavigate()
  const location = useLocation()
  const activeTab = normalizeTab(tab)
  const toast = useToast()
  const { data: campaigns = [] } = useCampaigns()
  const { data: overviewData = emptyOverview, isLoading } = useCampaignOverview(filename)

  const campaign = useMemo(
    () => campaigns.find((item) => item.filename === filename) || null,
    [campaigns, filename],
  )
  const overview = { ...emptyOverview, ...overviewData }
  const campaignName = campaign?.name || filename

  const showNotice = useCallback((message, error = false, options = {}) => {
    if (error) console.error(message)
    const type = options.type || (error ? "error" : "success")
    const title = options.title || (error ? "Action failed" : "Done")
    const detail = options.detail ?? message
    if (options.progressId && toast.update) {
      toast.update(options.progressId, {
        type,
        title,
        detail,
        actionLabel: options.actionLabel,
        onAction: options.onAction,
      })
      if (type !== "error" && !options.persist) {
        window.setTimeout(() => toast.dismiss?.(options.progressId), 5000)
      }
      return options.progressId
    }
    return toast({
      type,
      title,
      detail,
      actionLabel: options.actionLabel,
      onAction: options.onAction,
      persist: options.persist,
    })
  }, [toast])

  const selectTab = useCallback((nextTab, state) => {
    const slug = normalizeTab(nextTab)
    navigate(`/campaigns/${encodeURIComponent(filename)}/${slug}`, state ? { state } : undefined)
  }, [filename, navigate])

  const activeContent = () => {
    if (activeTab === "overview") {
      return <OverviewTab filename={filename} onSelectTab={selectTab} />
    }
    if (activeTab === "sources") {
      return <SourcesTab filename={filename} showNotice={showNotice} />
    }
    if (activeTab === "leads") {
      return <LeadsTab filename={filename} onSelectTab={selectTab} showNotice={showNotice} />
    }
    if (activeTab === "drafts") {
      return <DraftsTab campaignName={campaignName} filename={filename} initialJobContext={location.state?.draftJobContext} onSelectTab={selectTab} showNotice={showNotice} />
    }
    if (activeTab === "queue") {
      return <QueueTab campaignName={campaignName} filename={filename} onSelectTab={selectTab} showNotice={showNotice} />
    }
    if (activeTab === "sequence") {
      return <SequenceTab filename={filename} showNotice={showNotice} />
    }
    if (activeTab === "reports") {
      return <ReportsTab filename={filename} />
    }
    if (activeTab === "activity") {
      return <ActivityTab filename={filename} />
    }
    return (
  <SettingsTab
    filename={filename}
    campaignName={campaignName}
    showNotice={showNotice}
  />
)
  }

  return (
    <>
      <div className="topbar">
        <Link to="/campaigns" className="topbar-link">
          <i className="ti ti-arrow-left" aria-hidden="true" /> Campaigns
        </Link>
        <div className="topbar-title">{campaignName}</div>
        <div className="topbar-actions">
          <button className="btn primary" onClick={() => selectTab("sources")}>
            <i className="ti ti-player-play" aria-hidden="true" />
            New run
          </button>
        </div>
      </div>

      <div className="page-content campaign-workspace">
        <div className="campaign-hero">
          <div>
            <div className="campaign-kicker">Campaign workspace</div>
            <h1>{campaignName}</h1>
            <p>{campaign?.description || "Manage collection, enrichment, drafts, approvals, follow-ups, and activity from one place."}</p>
          </div>
          <span className="badge completed">Active</span>
        </div>

        <div className="metric-grid">
          {[
            ["total_leads", "Total leads", "ti-users"],
            ["with_email", "With email", "ti-at"],
            ["drafts_generated", "Drafts generated", "ti-mail-edit"],
            ["followups_due", "Follow-ups due", "ti-clock"],
          ].map(([key, label, icon]) => (
            <button className="metric-card" key={key} onClick={() => selectTab(key === "followups_due" ? "queue" : key === "drafts_generated" ? "drafts" : "leads")}>
              <span className="metric-icon"><i className={`ti ${icon}`} aria-hidden="true" /></span>
              <strong>{overview[key] ?? 0}</strong>
              <span>{label}</span>
            </button>
          ))}
        </div>

        <div className="workspace-tabs">
          {tabs.map(([slug, label]) => (
            <button
              type="button"
              className={`workspace-tab${activeTab === slug ? " active" : ""}`}
              key={slug}
              onClick={() => selectTab(slug)}
            >
              {label}
            </button>
          ))}
        </div>

        {isLoading ? (
          <div className="card">
            <div className="card-body muted">Loading campaign workspace...</div>
          </div>
        ) : activeContent()}
      </div>
    </>
  )
}
