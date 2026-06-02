import { useEffect, useRef, useState } from "react"
import { getRunEvents, openWS } from "../api"

const timeOnly = (v) => {
  if (!v) return ""
  const d = new Date(v)
  return isNaN(d) ? v.slice(11, 19) : d.toTimeString().slice(0, 8)
}

const rowClass = (event) => {
  const s = event?.payload?.status
  const t = event?.event_type
  if (s === "browser_ready" || s === "waiting_for_login") return "log-row yellow"
  if (s === "copying") return "log-row blue"
  if (t === "LEAD_SCRAPED" && !s) return "log-row green"
  if (t === "AGENT_FAILED" || t === "PIPELINE_FAILED") return "log-row red"
  return "log-row"
}

const summary = (event) => {
  const p = event?.payload || {}
  if (p.message) return p.message
  if (p.name) return `${p.name}${p.company ? " @ " + p.company : ""} (${p.total_so_far || ""})`
  if (p.status) return p.status
  const t = JSON.stringify(p)
  return t.length > 100 ? t.slice(0, 97) + "..." : t
}

export default function LiveLog({ runId, onEvent }) {
  const [events, setEvents] = useState([])
  const [wsReady, setWsReady] = useState(false)
  const wsReadyRef = useRef(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    let mounted = true
    let ws

    const load = async () => {
      try {
        const res = await getRunEvents(runId)
        if (mounted) setEvents(res.data.slice().reverse().slice(-50))
      } catch { /* ignore */ }
    }

    load()
    ws = openWS(runId, (ev) => {
      setEvents(cur => [...cur, ev].slice(-50))
      onEvent?.(ev)
    })
    ws.onopen = () => { wsReadyRef.current = true; if (mounted) setWsReady(true) }
    ws.onerror = ws.onclose = () => {
      wsReadyRef.current = false; if (mounted) setWsReady(false)
    }

    const fallback = setInterval(() => {
      if (!wsReadyRef.current) load()
    }, 4000)

    return () => {
      mounted = false; clearInterval(fallback); ws?.close()
    }
  }, [runId, onEvent])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" })
  }, [events])

  return (
    <section className="panel live-log">
      <div className="panel-head">
        <h2>Live log</h2>
        <span className={`dot ${wsReady ? "online" : "offline"}`} />
      </div>
      <div className="log-list">
        {events.length === 0 && <p className="empty">Waiting for events...</p>}
        {events.map((ev, i) => (
          <div className={rowClass(ev)} key={`${ev.timestamp}-${i}`}>
            <time>{timeOnly(ev.timestamp)}</time>
            <strong>{ev.agent_name}</strong>
            <small>{summary(ev)}</small>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
