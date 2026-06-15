import { useEffect } from "react"
import ProductButton from "./ProductButton.jsx"

export default function ProductModal({
  children,
  className = "",
  footer,
  onClose,
  open,
  subtitle = "",
  title,
}) {
  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose?.()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [onClose, open])

  if (!open) return null

  return (
    <div className="product-modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}>
      <section className={`product-modal ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title}>
        <header className="product-modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <ProductButton aria-label="Close modal" className="product-modal-close" onClick={onClose} variant="ghost">
            <i className="ti ti-x" aria-hidden="true" />
          </ProductButton>
        </header>
        <div className="product-modal-body">{children}</div>
        {footer && <footer className="product-modal-footer">{footer}</footer>}
      </section>
    </div>
  )
}
