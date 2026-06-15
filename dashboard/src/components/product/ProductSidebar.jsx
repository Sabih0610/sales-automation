const defaultSections = [
  {
    label: "Main",
    items: [
      ["Dashboard", "ti-layout-dashboard", "/"],
      ["Campaigns", "ti-speakerphone", "/campaigns"],
      ["Settings", "ti-settings", "/settings"],
    ],
  },
]

export default function ProductSidebar({
  activeItem = "Overview",
  emailsRemaining = 1240,
  emailsTotal = 2000,
  sections = defaultSections,
  showPlanCard = false,
}) {
  const progress = Math.max(0, Math.min(100, Math.round((emailsRemaining / emailsTotal) * 100)))

  return (
    <aside className="product-sidebar">
      <div className="product-sidebar-brand">
        <div className="product-brand-mark">RC</div>
        <div>
          <strong>RC Sales</strong>
          <span>Sales Automation Platform</span>
        </div>
      </div>

      <nav className="product-sidebar-nav" aria-label="Product navigation">
        {sections.map((section) => (
          <div className="product-sidebar-section" key={section.label}>
            <div className="product-sidebar-section-label">{section.label}</div>
            {section.items.map(([label, icon, href]) => (
              <a
                className={`product-sidebar-link${activeItem === label ? " active" : ""}`}
                href={href}
                key={label}
              >
                <i className={`ti ${icon}`} aria-hidden="true" />
                <span>{label}</span>
              </a>
            ))}
          </div>
        ))}
      </nav>

      {showPlanCard ? (
        <div className="product-plan-card">
          <div className="product-plan-head">
            <span>Premium Plan</span>
            <i className="ti ti-sparkles" aria-hidden="true" />
          </div>
          <strong>{emailsRemaining.toLocaleString()} emails remaining</strong>
          <div className="product-progress" aria-label={`${progress}% emails remaining`}>
            <span style={{ width: `${progress}%` }} />
          </div>
        </div>
      ) : (
        <div className="product-account-card">
          <span className="product-user-avatar">RC</span>
          <div>
            <strong>Royal Cyber</strong>
            <small>Sales Team</small>
          </div>
        </div>
      )}
    </aside>
  )
}
