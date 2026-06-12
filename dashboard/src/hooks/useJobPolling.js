import { useEffect, useState } from "react"
import { getJob } from "../api"

const terminalStatuses = new Set(["done", "failed", "cancelled"])

export default function useJobPolling(jobId) {
  const [job, setJob] = useState(null)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!jobId) {
      const resetTimer = window.setTimeout(() => {
        setJob(null)
        setError("")
      }, 0)
      return () => window.clearTimeout(resetTimer)
    }

    let stopped = false
    let timer = null

    const poll = async () => {
      try {
        const res = await getJob(jobId)
        if (stopped) return
        const nextJob = res.data
        setJob(nextJob)
        setError("")
        if (!terminalStatuses.has(nextJob.status)) {
          timer = window.setTimeout(poll, 2000)
        }
      } catch (err) {
        if (stopped) return
        setError(err.response?.data?.detail || "Job status unavailable")
        timer = window.setTimeout(poll, 2000)
      }
    }

    poll()

    return () => {
      stopped = true
      if (timer) window.clearTimeout(timer)
    }
  }, [jobId])

  return { job, error }
}
