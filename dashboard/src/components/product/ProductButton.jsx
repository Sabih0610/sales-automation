export default function ProductButton({
  as: Component = "button",
  children,
  className = "",
  icon = "",
  size = "md",
  variant = "secondary",
  ...props
}) {
  return (
    <Component
      className={`product-button product-button-${variant} product-button-${size} ${className}`.trim()}
      type={Component === "button" ? props.type || "button" : undefined}
      {...props}
    >
      {icon && <i className={`ti ${icon}`} aria-hidden="true" />}
      <span>{children}</span>
    </Component>
  )
}

export function ProductMoreMenuButton({ className = "", label = "More actions", ...props }) {
  return (
    <button
      aria-label={label}
      className={`product-more-menu ${className}`.trim()}
      type="button"
      {...props}
    >
      <i className="ti ti-dots-vertical" aria-hidden="true" />
    </button>
  )
}
