import { useCallback, useEffect, useState } from "react"
import { getSchedulerStatus } from "../api"

export default function SystemHealthBar() {
  const [status, setStatus] = useState(null)
  const [hasError, setHasError] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const res = await getSchedulerStatus()
      setStatus(res.data || null)
      setHasError(false)
    } catch {
      setStatus(null)
      setHasError(true)
    }
  }, [])

  useEffect(() => {
    loadStatus()
    const intervalId = window.setInterval(loadStatus, 60000)
    return () => window.clearInterval(intervalId)
  }, [loadStatus])

  if (!hasError && (!status || status.enabled === false || status.healthy === true)) {
    return null
  }

  return (
    <div className="system-health-bar" role="status">
      <span>Automation paused — scheduler heartbeat stale. Follow-ups are not being prepared or sent.</span>
      <button className="system-health-retry" type="button" onClick={loadStatus}>
        Retry
      </button>
    </div>
  )
}
