function safeParse(value) {
  if (!value) return {}
  if (typeof value === "object") return value

  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

function compactPayload(payload) {
  const text = JSON.stringify(payload || {})
  if (!text || text === "{}") return "No details"
  return text.length > 110 ? `${text.slice(0, 110)}…` : text
}

function failureDetails(event, payload) {
  return (
    event?.error ||
    payload.error ||
    payload.message ||
    payload.status ||
    "No details"
  )
}

export function humanizeEvent(event) {
  const payload = safeParse(event?.payload)
  const agent = event?.agent_name || "System"
  const type = event?.event_type || ""

  if (type === "AGENT_FAILED" || type === "PIPELINE_FAILED") {
    return {
      icon: "✕",
      text: `${agent} failed — ${failureDetails(event, payload)}`,
      tone: "error",
    }
  }

  if (event?.error) {
    return {
      icon: "✕",
      text: event.error,
      tone: "error",
    }
  }

  if (payload.message) {
    return {
      icon: type.includes("FAILED") ? "✕" : "•",
      text: payload.message,
      tone: type.includes("FAILED") ? "error" : "muted",
    }
  }

  if (payload.status === "browser_ready") {
    return {
      icon: "🌐",
      text: "Browser opened — complete login or CAPTCHA if needed",
      tone: "warning",
    }
  }

  if (payload.status === "waiting_for_login") {
    return {
      icon: "⏳",
      text: "Waiting for LinkedIn login",
      tone: "warning",
    }
  }

  if (payload.status === "copying") {
    return {
      icon: "📋",
      text: "Copying Sales Navigator page content",
      tone: "info",
    }
  }

  if (type === "LEAD_SCRAPED" || payload.name) {
    const name = payload.name || "Lead"
    const company = payload.company ? ` at ${payload.company}` : ""
    return {
      icon: "✓",
      text: `${name}${company} captured`,
      tone: "ok",
    }
  }

  if (agent === "ScraperAgent" && payload.page != null) {
    return {
      icon: "✓",
      text: `Page ${payload.page} scraped — ${payload.count ?? payload.result_count ?? "?"} leads`,
      tone: "ok",
    }
  }

  if (agent === "VerifierAgent" && payload.kept != null) {
    return {
      icon: "✓",
      text: `${payload.kept} kept, ${payload.dropped ?? 0} dropped after verification`,
      tone: "ok",
    }
  }

  if (agent === "SegmentAgent" && payload.result_count != null) {
    return {
      icon: "✓",
      text: `Segmented ${payload.result_count} leads`,
      tone: "ok",
    }
  }

  if (type === "LEAD_SEGMENTED") {
  return {
    icon: "•",
    text: `Lead marked as ${payload.segment || "segmented"}`,
    tone: payload.segment === "NO_EMAIL" ? "warning" : "ok",
  }
}


  if (agent === "ExportAgent" && payload.file) {
    return {
      icon: "📄",
      text: `Export ready: ${String(payload.file).split(/[\\/]/).pop()}`,
      tone: "ok",
    }
  }

  if (type === "AGENT_STARTED") {
    return {
      icon: "•",
      text: `${agent} started`,
      tone: "info",
    }
  }

  if (type === "AGENT_COMPLETED") {
    return {
      icon: "✓",
      text: `${agent} completed`,
      tone: "ok",
    }
  }

  if (type === "PIPELINE_COMPLETED" || type === "COMPLETED") {
  return {
    icon: "✓",
    text: `Run completed — ${payload.total_scraped ?? 0} scraped, ${payload.total_exported ?? 0} exported`,
    tone: "success",
  }
}

  return {
    icon: "•",
    text: `${agent}: ${compactPayload(payload)}`,
    tone: "muted",
  }
}
