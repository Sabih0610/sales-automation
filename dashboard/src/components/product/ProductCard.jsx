import ProductBadge, { ProductStatusBadge } from "./ProductBadge.jsx"

export default function ProductCard({
  as: Component = "section",
  children,
  className = "",
  padding = "md",
  ...props
}) {
  return (
    <Component className={`product-card product-card-${padding} ${className}`.trim()} {...props}>
      {children}
    </Component>
  )
}

export function ProductIconBox({ className = "", icon = "ti-sparkles", tone = "primary" }) {
  return (
    <span className={`product-icon-box product-icon-box-${tone} ${className}`.trim()}>
      <i className={`ti ${icon}`} aria-hidden="true" />
    </span>
  )
}

export function ProductMetricCard({
  className = "",
  delta = "",
  icon = "",
  label,
  tone = "primary",
  value,
}) {
  return (
    <ProductCard className={`product-metric-card ${className}`.trim()}>
      <div className="product-metric-head">
        <span>{label}</span>
        {icon && <ProductIconBox icon={icon} tone={tone} />}
      </div>
      <strong>{value}</strong>
      {delta && <small>{delta}</small>}
    </ProductCard>
  )
}

export function ProductEmptyState({
  action,
  className = "",
  description,
  icon = "ti-inbox",
  title,
}) {
  return (
    <ProductCard className={`product-empty-state ${className}`.trim()}>
      <ProductIconBox icon={icon} tone="primary" />
      <h2>{title}</h2>
      {description && <p>{description}</p>}
      {action && <div className="product-empty-action">{action}</div>}
    </ProductCard>
  )
}

export function ProductStepCard({
  actions,
  children,
  className = "",
  description,
  step = 1,
  status = "draft",
  title,
}) {
  return (
    <ProductCard className={`product-step-card ${className}`.trim()}>
      <div className="product-step-number">{step}</div>
      <div className="product-step-body">
        <div className="product-step-head">
          <div>
            <h3>{title}</h3>
            {description && <p>{description}</p>}
          </div>
          <ProductStatusBadge status={status} />
        </div>
        {children}
      </div>
      {actions && <div className="product-step-actions">{actions}</div>}
    </ProductCard>
  )
}

export { ProductBadge, ProductStatusBadge }
