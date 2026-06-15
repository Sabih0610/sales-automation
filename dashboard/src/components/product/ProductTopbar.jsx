import ProductButton from "./ProductButton.jsx"

export default function ProductTopbar({
  campaignName = "SAP Migration for Enterprise",
  campaigns = [],
  onCampaignChange,
  onSearchChange,
  searchPlaceholder = "Search sequences, steps, or contacts...",
  searchValue = "",
  user = { name: "Royal Cyber", role: "Sales Team", initials: "RC" },
}) {
  return (
    <header className="product-topbar">
      <label className="product-campaign-select">
        <span>Campaign</span>
        {campaigns.length > 0 ? (
          <select
            value={campaignName}
            onChange={(event) => onCampaignChange?.(event.target.value)}
          >
            {campaigns.map((campaign) => (
              <option key={campaign.value || campaign.filename || campaign.name} value={campaign.value || campaign.filename || campaign.name}>
                {campaign.label || campaign.name}
              </option>
            ))}
          </select>
        ) : (
          <strong>{campaignName}</strong>
        )}
      </label>

      <label className="product-global-search">
        <i className="ti ti-search" aria-hidden="true" />
        <input
          onChange={(event) => onSearchChange?.(event.target.value)}
          placeholder={searchPlaceholder}
          type="search"
          value={searchValue}
        />
      </label>

      <div className="product-topbar-actions">
        <ProductButton aria-label="Notifications" className="product-icon-button" variant="ghost">
          <i className="ti ti-bell" aria-hidden="true" />
        </ProductButton>
        <ProductButton aria-label="Help" className="product-icon-button" variant="ghost">
          <i className="ti ti-help-circle" aria-hidden="true" />
        </ProductButton>
        <button className="product-user-menu" type="button">
          <span className="product-user-avatar">{user.initials || "RC"}</span>
          <span>
            <strong>{user.name || "Royal Cyber"}</strong>
            <small>{user.role || "Sales Team"}</small>
          </span>
          <i className="ti ti-chevron-down" aria-hidden="true" />
        </button>
      </div>
    </header>
  )
}
