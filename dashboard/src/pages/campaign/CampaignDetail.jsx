import { useCallback, useEffect, useMemo } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router-dom"
import { useToast } from "../../components/ToastProvider"
import { useCampaignOverview, useCampaigns } from "../../queries"
import LeadsTab from "./LeadsTab.jsx"
import OverviewTab from "./OverviewTab.jsx"
import ReportsTab from "./ReportsTab.jsx"
import SettingsTab from "./SettingsTab.jsx"
import { emptyOverview, tabAliases, tabLabels, tabs } from "./utils.jsx"
import DraftReviewScheduling from "../drafts/DraftReviewScheduling.jsx"
import CampaignSequencesHome from "../sequences/CampaignSequencesHome.jsx"


const normalizeTab = (value) => {
  const slug = String(value || "overview").toLowerCase()
  return tabLabels[slug] ? slug : tabAliases[slug] || "overview"
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

  useEffect(() => {
    const rawTab = String(tab || "").toLowerCase()
    if (rawTab && rawTab !== activeTab) {
      navigate(`/campaigns/${encodeURIComponent(filename)}/${activeTab}`, {
        replace: true,
      })
    }
  }, [activeTab, filename, navigate, tab])

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
    navigate(
      `/campaigns/${encodeURIComponent(filename)}/${slug}`,
      state ? { state } : undefined,
    )
  }, [filename, navigate])

  const activeContent = () => {
    if (activeTab === "overview") {
      return <OverviewTab filename={filename} onSelectTab={selectTab} />
    }

    if (activeTab === "leads") {
      return (
        <LeadsTab
          filename={filename}
          onSelectTab={selectTab}
          showNotice={showNotice}
        />
      )
    }

    if (activeTab === "sequences") {
      return <CampaignSequencesHome />
    }

    if (activeTab === "drafts") {
      return <DraftReviewScheduling />
    }

    if (activeTab === "reports") {
      return <ReportsTab filename={filename} />
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
          <button className="btn primary" onClick={() => selectTab("leads")}>
            <i className="ti ti-users-plus" aria-hidden="true" />
            Add leads
          </button>
        </div>
      </div>

      <div className="page-content campaign-workspace">
        <div className="campaign-hero">
          <div>
            <div className="campaign-kicker">Campaign workspace</div>
            <h1>{campaignName}</h1>
            <p>
              {campaign?.description ||
                "Manage leads, email sequences, draft review, sending, reports, and settings from one campaign workspace."}
            </p>
          </div>

          <span className="badge completed">Active</span>
        </div>

        <div className="metric-grid">
          {[
            ["total_leads", "Total leads", "ti-users", "leads"],
            ["with_email", "With email", "ti-at", "leads"],
            ["approved_drafts", "Approved drafts", "ti-mail-check", "drafts"],
            ["emails_sent", "Sent emails", "ti-send", "reports"],
          ].map(([key, label, icon, targetTab]) => (
            <button
              className="metric-card"
              key={key}
              onClick={() => selectTab(targetTab)}
              type="button"
            >
              <span className="metric-icon">
                <i className={`ti ${icon}`} aria-hidden="true" />
              </span>
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
        ) : (
          activeContent()
        )}
      </div>
    </>
  )
}