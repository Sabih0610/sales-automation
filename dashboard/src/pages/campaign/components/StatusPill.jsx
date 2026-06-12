import { statusClass, statusText } from "../utils.jsx"

export default function StatusPill({ value }) {
  return <span className={`badge ${statusClass(value)}`}>{statusText(value)}</span>
}
