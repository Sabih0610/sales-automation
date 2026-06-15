import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { friendlyMessage } from "../../api"
import {
  useAddLeadSourceSegment,
  useBulkScrapeJobs,
  useCampaignLeadUniverses,
  useCampaignRuns,
  useCancelBulkScrapeJob,
  useCreateLeadUniverse,
  usePauseBulkScrapeJob,
  usePauseLeadSourceSegments,
  useResumeBulkScrapeJob,
  useRunAllLeadSourceSegments,
  useRunLeadSourceSegment,
  useRunNextLeadSourceSegment,
  useStartBulkScrape,
  useStartRun,
  useStopRun,
  useDeleteRun,
} from "../../queries"
import StatusPill from "./components/StatusPill.jsx"
import { EmptyRow, fmtDate } from "./utils.jsx"

const parseList = (value) => value.split(",").map((item) => item.trim()).filter(Boolean)
const fmtNumber = (value) => new Intl.NumberFormat().format(Number(value || 0))
const fmtPct = (value) => `${Math.min(100, Math.max(0, Number(value || 0))).toFixed(1)}%`
const runPath = (filename, runId) =>
  `/campaigns/${encodeURIComponent(filename)}/runs/${encodeURIComponent(runId)}`

function RunLink({ filename, run }) {
  const id = typeof run === "string" ? run : run?.id
  if (!id) return "-"
  const label =
    typeof run === "string"
      ? `Run ${id.slice(0, 8)}`
      : run?.label || `Run ${id.slice(0, 8)}`
  return (
    <Link className="run-link" to={runPath(filename, id)}>
      <span>{label}</span>
      <span className="run-id-muted">{id.slice(0, 8)}</span>
    </Link>
  )
}


function displayRunStatus(run) {
  const error = String(run?.error || run?.stop_reason || "").toLowerCase()
  if (error.includes("stopped by user") || error.includes("stop requested")) {
    return "STOPPED"
  }
  return run?.status || "-"
}

export default function SourcesTab({ filename, showNotice }) {
  const navigate = useNavigate()
  const { data: runs = [] } = useCampaignRuns(filename)
  const { data: universes = [] } = useCampaignLeadUniverses(filename)
  const startRun = useStartRun()
  const { data: bulkJobs = [] } = useBulkScrapeJobs(20)
  const startBulkScrape = useStartBulkScrape(filename)
  const pauseBulkScrape = usePauseBulkScrapeJob()
  const resumeBulkScrape = useResumeBulkScrapeJob()
  const cancelBulkScrape = useCancelBulkScrapeJob()
  const stopRun = useStopRun(filename)
  const deleteRun = useDeleteRun(filename)
  const createUniverse = useCreateLeadUniverse(filename)
  const addSegment = useAddLeadSourceSegment(filename)
  const runSegment = useRunLeadSourceSegment(filename)
  const runNext = useRunNextLeadSourceSegment(filename)
  const runAll = useRunAllLeadSourceSegments(filename)
  const pauseAll = usePauseLeadSourceSegments(filename)
  const sourceBusy =
    startBulkScrape.isPending ||
    pauseBulkScrape.isPending ||
    resumeBulkScrape.isPending ||
    cancelBulkScrape.isPending ||
    stopRun.isPending ||
    deleteRun.isPending ||
    startRun.isPending ||
    createUniverse.isPending ||
    addSegment.isPending ||
    runSegment.isPending ||
    runNext.isPending ||
    runAll.isPending ||
    pauseAll.isPending

  const [selectedUniverseId, setSelectedUniverseId] = useState("")
  const [sourceForm, setSourceForm] = useState({
    source_url: "",
    max_leads: 30000,
    scrape_mode: "normal",
    batch_max_leads: 1000,
    batch_page_limit: 25,
  })
  const [universeForm, setUniverseForm] = useState({
    name: "",
    description: "",
    target_leads: 1000,
  })
  const [segmentForm, setSegmentForm] = useState({
    label: "",
    source_url: "",
    expected_count: 50,
  })

  useEffect(() => {
    if (!selectedUniverseId && universes.length > 0) {
      setSelectedUniverseId(universes[0].id)
    }
  }, [selectedUniverseId, universes])

  const selectedUniverse = useMemo(
    () => universes.find((universe) => universe.id === selectedUniverseId) || universes[0] || null,
    [selectedUniverseId, universes],
  )
  const sourceSegments = selectedUniverse?.segments || []
  const campaignBulkJobs = useMemo(
    () => bulkJobs.filter((job) => !job.campaign_key || job.campaign_key === filename),
    [bulkJobs, filename],
  )
  const bulkBusy =
    startBulkScrape.isPending ||
    pauseBulkScrape.isPending ||
    resumeBulkScrape.isPending ||
    cancelBulkScrape.isPending

  const handleStartRun = async () => {
    if (!sourceForm.source_url.trim()) {
      showNotice("Source URL is required", true)
      return
    }

    try {
      const res = await startBulkScrape.mutateAsync({
        start_url: sourceForm.source_url.trim(),
        campaign_key: filename,
        target_leads: Number(sourceForm.max_leads) || 30000,
        batch_max_leads: 1000,
        batch_page_limit: 25,
      })

      showNotice(`Scraping started: ${res.data.id.slice(0, 8)}`)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Scraping failed to start", true)
    }
  }

  const handleStopRun = async (runId) => {
    try {
      await stopRun.mutateAsync(runId)
      showNotice("Stop requested. Scraper will stop at the next safe checkpoint.")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Could not stop scraper", true)
    }
  }

  const handleDeleteRun = async (runId) => {
    if (!window.confirm("Delete this scrape run and its saved leads?")) return

    try {
      await deleteRun.mutateAsync(runId)
      showNotice("Scrape run deleted")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Could not delete scrape run", true)
    }
  }

  const handleBulkAction = async (jobId, action) => {
    try {
      if (action === "pause") await pauseBulkScrape.mutateAsync(jobId)
      if (action === "resume") await resumeBulkScrape.mutateAsync(jobId)
      if (action === "cancel") await cancelBulkScrape.mutateAsync(jobId)
      showNotice(`Bulk scrape ${action} request sent`)
    } catch (err) {
      showNotice(friendlyMessage(err) || `Bulk scrape ${action} failed`, true)
    }
  }

  const handleCreateUniverse = async () => {
    if (!universeForm.name.trim()) {
      showNotice("Universe name is required", true)
      return
    }
    try {
      const res = await createUniverse.mutateAsync({
        name: universeForm.name.trim(),
        campaign_filename: filename,
        description: universeForm.description.trim(),
        target_leads: Number(universeForm.target_leads) || 0,
        source_type: "sales_navigator",
      })
      setSelectedUniverseId(res.data.id)
      setUniverseForm({ name: "", description: "", target_leads: 1000 })
      showNotice("Lead universe created")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Universe creation failed", true)
    }
  }

  const handleAddSegment = async () => {
    if (!selectedUniverse) {
      showNotice("Create a lead universe first", true)
      return
    }
    if (!segmentForm.source_url.trim()) {
      showNotice("Sales Navigator URL is required", true)
      return
    }
    try {
      await addSegment.mutateAsync({
        universeId: selectedUniverse.id,
        data: {
          label: segmentForm.label.trim(),
          source_url: segmentForm.source_url.trim(),
          expected_count: Number(segmentForm.expected_count) || 50,
          filters: {},
        },
      })
      setSegmentForm({ label: "", source_url: "", expected_count: 50 })
      showNotice("Source segment added")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Segment creation failed", true)
    }
  }

  const handleRunSegment = async (segmentId) => {
    try {
      await runSegment.mutateAsync(segmentId)
      showNotice("Segment run started")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Segment run failed", true)
    }
  }

  const handleRunNext = async () => {
    if (!selectedUniverse) return
    try {
      const res = await runNext.mutateAsync(selectedUniverse.id)
      showNotice(res.data.started ? "Next segment started" : "No queued segments")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Run next failed", true)
    }
  }

  const handleRunAll = async () => {
    if (!selectedUniverse) return
    try {
      const res = await runAll.mutateAsync(selectedUniverse.id)
      showNotice(res.data.started ? `Started ${res.data.queued || 0} queued segments` : "No queued segments")
    } catch (err) {
      showNotice(friendlyMessage(err) || "Run all failed", true)
    }
  }

  const handlePauseAll = async () => {
    if (!selectedUniverse) return
    try {
      const res = await pauseAll.mutateAsync(selectedUniverse.id)
      showNotice(`Paused ${res.data.paused || 0} segments`)
    } catch (err) {
      showNotice(friendlyMessage(err) || "Pause failed", true)
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h2>Lead scraping</h2>
          <button className="btn primary sm" onClick={handleStartRun} disabled={sourceBusy}>
            <i className="ti ti-player-play" aria-hidden="true" />
            Start scraping
          </button>
        </div>
        <div className="card-body">
          <div className="lead-scrape-grid">
            <div className="form-group span-2">
              <div className="form-label">Source URL</div>
              <input
                className="form-input"
                value={sourceForm.source_url}
                onChange={(e) => setSourceForm((form) => ({ ...form, source_url: e.target.value }))}
                placeholder="https://www.linkedin.com/sales/search/people..."
              />
            </div>
            <div className="form-group">
              <div className="form-label">Number of leads</div>
              <input
                className="form-input"
                type="number"
                min="1"
                value={sourceForm.max_leads}
                onChange={(e) => setSourceForm((form) => ({ ...form, max_leads: e.target.value }))}
              />
            </div>
          </div>
        </div>
      </div>


            <div className="card">
        <div className="card-head"><h2>Scraping history</h2></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Source URL</th>
                <th>Status</th>
                <th>Requested</th>
                <th>Scraped</th>
                <th>Unique</th>
                <th>Duplicates</th>
                <th>Started</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && <EmptyRow colSpan={9} text="No source runs for this campaign yet." />}
              {runs.map((run) => (
                <tr key={run.id}>
                  <td><RunLink filename={filename} run={run} /></td>
                  <td className="truncate wide">{run.start_url || "-"}</td>
                  <td><StatusPill value={displayRunStatus(run)} /></td>
                  <td className="truncate wide">{run.error || run.stop_reason || "-"}</td>
                  <td>{run.max_leads || "-"}</td>
                  <td>{run.total_scraped || 0}</td>
                  <td>{run.unique_count || "-"}</td>
                  <td>{run.duplicate_count || "-"}</td>
                  <td>{fmtDate(run.started_at)}</td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn xs" to={runPath(filename, run.id)}>View logs</Link>
                      {run.status === "RUNNING" ? (
                        <button
                          className="btn xs danger"
                          type="button"
                          onClick={() => handleStopRun(run.id)}
                          disabled={sourceBusy}
                        >
                          Stop
                        </button>
                      ) : (
                        <button
                          className="btn xs danger"
                          type="button"
                          onClick={() => handleDeleteRun(run.id)}
                          disabled={sourceBusy}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </>
  )
}
