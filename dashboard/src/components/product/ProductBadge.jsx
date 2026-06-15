const statusTone = {
  active: "success",
  approved: "success",
  completed: "success",
  sent: "success",
  scheduled: "info",
  sending: "info",
  queued: "info",
  draft: "neutral",
  pending: "neutral",
  warning: "warning",
  failed: "danger",
  error: "danger",
  skipped: "warning",
  paused: "warning",
  archived: "neutral",
}

export default function ProductBadge({
  children,
  className = "",
  tone = "neutral",
  variant = "soft",
}) {
  return (
    <span className={`product-badge product-badge-${tone} product-badge-${variant} ${className}`.trim()}>
      {children}
    </span>
  )
}

export function ProductStatusBadge({ status = "active", children, className = "" }) {
  const normalized = String(status || "active").toLowerCase()
  const tone = statusTone[normalized] || "neutral"
  const label = children || normalized.replace(/_/g, " ")

  return (
    <ProductBadge className={className} tone={tone}>
      <span className="product-status-dot" />
      {label}
    </ProductBadge>
  )
}
