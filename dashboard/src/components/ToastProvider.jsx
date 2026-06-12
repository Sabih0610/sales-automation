import { createContext, useCallback, useContext, useRef, useState } from "react"

const ToastContext = createContext(null)

export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const idRef = useRef(0)

  const dismiss = useCallback((id) => setToasts((items) => items.filter((item) => item.id !== id)), [])

  const update = useCallback((id, patch) => {
    setToasts((items) => items.map((item) => item.id === id ? { ...item, ...patch } : item))
  }, [])

  const toast = useCallback(({ type = "info", title, detail, actionLabel, onAction, persist = false }) => {
    const id = ++idRef.current
    setToasts((items) => [...items.slice(-3), { id, type, title, detail, actionLabel, onAction }])
    if (type !== "error" && !persist) window.setTimeout(() => dismiss(id), 5000)
    return id
  }, [dismiss])

  toast.dismiss = dismiss
  toast.update = update

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-stack">
        {toasts.map((item) => (
          <div key={item.id} className={`toast toast-${item.type}`}>
            <div className="toast-body">
              <strong>{item.title}</strong>
              {item.detail && <div className="toast-detail">{item.detail}</div>}
            </div>
            {item.actionLabel && (
              <button onClick={() => { item.onAction?.(); dismiss(item.id) }}>
                {item.actionLabel}
              </button>
            )}
            <button className="toast-x" onClick={() => dismiss(item.id)}>×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
