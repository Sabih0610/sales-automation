import ProductSidebar from "./ProductSidebar.jsx"
import ProductTopbar from "./ProductTopbar.jsx"

export default function ProductShell({
  activeItem = "Overview",
  campaignName,
  campaigns,
  children,
  className = "",
  contentClassName = "",
  onCampaignChange,
  onSearchChange,
  searchValue,
  sidebarProps = {},
  topbarProps = {},
}) {
  return (
    <div className={`product-shell ${className}`.trim()}>
      <ProductSidebar activeItem={activeItem} {...sidebarProps} />
      <div className="product-shell-main">
        <ProductTopbar
          campaignName={campaignName}
          campaigns={campaigns}
          onCampaignChange={onCampaignChange}
          onSearchChange={onSearchChange}
          searchValue={searchValue}
          {...topbarProps}
        />
        <main className={`product-content ${contentClassName}`.trim()}>
          {children}
        </main>
      </div>
    </div>
  )
}
