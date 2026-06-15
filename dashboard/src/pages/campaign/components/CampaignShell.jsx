import { Link, useNavigate } from "react-router-dom"
import { ProductShell } from "../../../components/product"
import { useCampaignOverview, useCampaigns } from "../../../queries"
import { emptyOverview, tabs } from "../utils.jsx"
import { campaignProductSections } from "../campaignProductNav"

const tabLabel = (slug = "overview") =>
  tabs.find(([value]) => value === slug)?.[1] || "Overview"

const tabPath = (filename, slug) =>
  `/campaigns/${encodeURIComponent(filename)}/${slug === "overview" ? "overview" : slug}`

function CampaignHeader({ activeTab, campaign, campaignName, onSelectTab }) {
  const showAddLeads = ["overview", "leads"].includes(activeTab)

  return (
    <section className="campaign-shell-header">
      <div>
        <Link className="campaign-shell-back" to="/campaigns">
          <i className="ti ti-arrow-left" aria-hidden="true" />
          Back to Campaigns
        </Link>
        <div className="campaign-shell-title-row">
          <h1>{campaignName}</h1>
          <span className="product-badge product-badge-success">
            <span className="product-status-dot" />
            Active
          </span>
        </div>
        <p>
          {campaign?.description ||
            "Manage leads, sequences, draft review, sending, and performance from one campaign workspace."}
        </p>
      </div>

      {showAddLeads && (
        <button
          className="product-button product-button-primary product-button-md"
          onClick={() => onSelectTab("leads")}
          type="button"
        >
          <i className="ti ti-user-plus" aria-hidden="true" />
          <span>Add leads</span>
        </button>
      )}
    </section>
  )
}

function CampaignMetrics({ onSelectTab, overview }) {
  const metrics = [
    ["ti-users", "Total leads", "leads", overview.total_leads ?? 0],
    ["ti-at", "Verified emails", "leads", overview.verified_emails ?? overview.with_email ?? 0],
    ["ti-circle-check", "Approved drafts", "drafts", overview.approved_drafts ?? 0],
    ["ti-send", "Sent emails", "reports", overview.emails_sent ?? 0],
  ]

  return (
    <div className="campaign-shell-metrics">
      {metrics.map(([icon, label, tab, value]) => (
        <button
          className="campaign-shell-metric"
          key={label}
          onClick={() => onSelectTab(tab)}
          type="button"
        >
          <span><i className={`ti ${icon}`} aria-hidden="true" /></span>
          <strong>{value}</strong>
          <small>{label}</small>
        </button>
      ))}
    </div>
  )
}

function CampaignTabs({ activeTab, onSelectTab }) {
  return (
    <div className="campaign-shell-tabs" role="tablist" aria-label="Campaign workspace">
      {tabs.map(([slug, label]) => (
        <button
          aria-selected={activeTab === slug}
          className={activeTab === slug ? "active" : ""}
          key={slug}
          onClick={() => onSelectTab(slug)}
          role="tab"
          type="button"
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export default function CampaignShell({
  activeTab = "overview",
  children,
  className = "",
  contentClassName = "",
  filename,
  onSearchChange,
  searchPlaceholder = "Search leads, sequences, drafts, or reports...",
  searchValue = "",
}) {
  const navigate = useNavigate()
  const { data: campaigns = [] } = useCampaigns()
  const { data: overviewData = emptyOverview } = useCampaignOverview(filename)

  const campaign = campaigns.find((item) => item.filename === filename) || null
  const campaignName = campaign?.name || filename || "SAP Migration for Enterprise"
  const campaignOptions = campaigns.map((item) => ({
    label: item.name || item.filename,
    value: item.filename,
  }))
  const overview = { ...emptyOverview, ...overviewData }

  const selectTab = (slug) => {
    navigate(tabPath(filename, slug === "sequence" ? "sequences" : slug))
  }

  return (
    <ProductShell
      activeItem={tabLabel(activeTab)}
      campaignName={campaignOptions.length ? filename : campaignName}
      campaigns={campaignOptions}
      className={`campaign-product-shell ${className}`.trim()}
      contentClassName={`campaign-shell-content ${contentClassName}`.trim()}
      onCampaignChange={(nextFilename) => {
        if (nextFilename) navigate(tabPath(nextFilename, activeTab))
      }}
      onSearchChange={onSearchChange}
      searchValue={searchValue}
      sidebarProps={{ sections: campaignProductSections(filename) }}
      topbarProps={{ searchPlaceholder }}
    >
      <div className="campaign-shell-workspace">
        <CampaignHeader
          activeTab={activeTab}
          campaign={campaign}
          campaignName={campaignName}
          onSelectTab={selectTab}
        />
        <CampaignMetrics onSelectTab={selectTab} overview={overview} />
        <CampaignTabs activeTab={activeTab} onSelectTab={selectTab} />
        <div className="campaign-shell-body">{children}</div>
      </div>
    </ProductShell>
  )
}
