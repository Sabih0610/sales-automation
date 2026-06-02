import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { startRun } from "../api"

const parseList = (v) => v.split(",").map(s => s.trim()).filter(Boolean)

export default function StartRunForm({ onClose }) {
  const navigate = useNavigate()
  const [url, setUrl] = useState("")
  const [maxLeads, setMaxLeads] = useState(100)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [titles, setTitles] = useState("CTO, CIO, CXO, Head of Data, VP Engineering")
  const [keywords, setKeywords] = useState("Microsoft Fabric")
  const [geos, setGeos] = useState("")
  const [industries, setIndustries] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (!url.trim()) { setError("URL is required."); return }
    setError(""); setLoading(true)
    try {
      const res = await startRun({
        start_url: url.trim(),
        max_leads: Number(maxLeads) || 100,
        titles: parseList(titles),
        keywords,
        geos: parseList(geos),
        industries: parseList(industries),
        company_sizes: [],
      })
      onClose?.()
      navigate(`/run/${res.data.id}`)
    } catch (err) {
      setError(
        err.response?.status === 409
          ? "A run is already active. Wait for it to finish."
          : err.response?.data?.detail || "Failed to start run."
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="run-form" onSubmit={submit}>
      <div className="url-field">
        <label className="url-label">
          URL to scrape
          <span className="url-hint">
            Paste any search results or directory page URL
          </span>
        </label>
        <input
          className="url-input"
          type="url"
          placeholder="https://www.yellowpages.com.au/search?search_terms=..."
          value={url}
          onChange={e => setUrl(e.target.value)}
          autoFocus
        />
      </div>

      <div className="max-leads-row">
        <label>
          Max leads to collect
          <input
            type="number"
            min="1"
            max="10000"
            value={maxLeads}
            onChange={e => setMaxLeads(e.target.value)}
          />
        </label>
      </div>

      <button
        type="button"
        className="toggle-advanced"
        onClick={() => setShowAdvanced(s => !s)}
      >
        {showAdvanced ? "▼" : "▶"} Advanced settings
      </button>

      {showAdvanced && (
        <div className="advanced-fields">
          <label>
            Titles (comma separated)
            <textarea rows="2" value={titles}
              onChange={e => setTitles(e.target.value)} />
          </label>
          <label>
            Keywords
            <input type="text" value={keywords}
              onChange={e => setKeywords(e.target.value)} />
          </label>
          <label>
            Locations (comma separated)
            <input type="text" value={geos}
              placeholder="United States, Australia"
              onChange={e => setGeos(e.target.value)} />
          </label>
          <label>
            Industries (comma separated)
            <input type="text" value={industries}
              placeholder="Software, IT Services"
              onChange={e => setIndustries(e.target.value)} />
          </label>
        </div>
      )}

      {error && <p className="form-error">{error}</p>}

      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          type="submit"
          className="button primary"
          disabled={loading || !url.trim()}
        >
          {loading ? "Starting..." : "Start Scraping"}
        </button>
      </div>
    </form>
  )
}
