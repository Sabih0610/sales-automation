export function relativeTime(iso) {
  if (!iso) return ""

  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return String(iso)

  const diff = date - new Date()
  const abs = Math.abs(diff)
  const minutes = Math.round(abs / 60000)
  const hours = Math.round(minutes / 60)
  const days = Math.round(hours / 24)

  const span =
    minutes < 60
      ? `${Math.max(1, minutes)}m`
      : hours < 48
        ? `${hours}h`
        : `${days}d`

  return diff > 0 ? `in ${span}` : `${span} ago`
}