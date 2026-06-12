import { useEffect, useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { friendlyMessage } from "../../api"
import {
  useAddLeadSourceSegment,
  useCampaignLeadUniverses,
  useCampaignRuns,
  useCreateLeadUniverse,
  usePauseLeadSourceSegments,
  useRunAllLeadSourceSegments,
  useRunLeadSourceSegment,
  useRunNextLeadSourceSegment,
  useStartRun,
} from "../../queries"
import StatusPill from "./components/StatusPill.jsx"
import { EmptyRow, fmtDate } from "./utils.jsx"

const parseList = (value) => value.split(",").map((item) => item.trim()).filter(Boolean)
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

export default function SourcesTab({ filename, showNotice }) {
  const navigate = useNavigate()
  const { data: runs = [] } = useCampaignRuns(filename)
  const { data: universes = [] } = useCampaignLeadUniverses(filename)
  const startRun = useStartRun()
  const createUniverse = useCreateLeadUniverse(filename)
  const addSegment = useAddLeadSourceSegment(filename)
  const runSegment = useRunLeadSourceSegment(filename)
  const runNext = useRunNextLeadSourceSegment(filename)
  const runAll = useRunAllLeadSourceSegments(filename)
  const pauseAll = usePauseLeadSourceSegments(filename)
  const sourceBusy =
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
    max_leads: 100,
    titles: "CTO, CIO, Head of Data",
    keywords: "",
    geos: "",
    showAdvanced: false,
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

  const handleStartRun = async () => {
    if (!sourceForm.source_url.trim()) {
      showNotice("Source URL is required", true)
      return
    }
    try {
      const res = await startRun.mutateAsync({
        start_url: sourceForm.source_url.trim(),
        max_leads: Number(sourceForm.max_leads) || 100,
        campaign: filename,
        titles: parseList(sourceForm.titles),
        keywords: sourceForm.keywords,
        geos: parseList(sourceForm.geos),
        industries: [],
        company_sizes: [],
      })
      showNotice("Campaign source run started")
      navigate(runPath(filename, res.data.id))
    } catch (err) {
      showNotice(friendlyMessage(err) || "Run failed to start", true)
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
          <h2>Start campaign source run</h2>
          <button className="btn primary sm" onClick={handleStartRun} disabled={sourceBusy}>
            <i className="ti ti-player-play" aria-hidden="true" />
            Start run
          </button>
        </div>
        <div className="card-body">
          <div className="source-run-grid">
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
              <div className="form-label">Campaign</div>
              <input className="form-input" value="Locked to this campaign" readOnly />
            </div>
            <div className="form-group">
              <div className="form-label">Max leads</div>
              <input
                className="form-input"
                type="number"
                min="1"
                value={sourceForm.max_leads}
                onChange={(e) => setSourceForm((form) => ({ ...form, max_leads: e.target.value }))}
              />
            </div>
          </div>
          <button
            className="plain-toggle"
            type="button"
            onClick={() => setSourceForm((form) => ({ ...form, showAdvanced: !form.showAdvanced }))}
          >
            <i className={`ti ti-chevron-${sourceForm.showAdvanced ? "down" : "right"}`} aria-hidden="true" />
            Advanced settings
          </button>
          {sourceForm.showAdvanced && (
            <div className="source-run-grid">
              <div className="form-group">
                <div className="form-label">Target titles</div>
                <input
                  className="form-input"
                  value={sourceForm.titles}
                  onChange={(e) => setSourceForm((form) => ({ ...form, titles: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <div className="form-label">Locations</div>
                <input
                  className="form-input"
                  value={sourceForm.geos}
                  onChange={(e) => setSourceForm((form) => ({ ...form, geos: e.target.value }))}
                />
              </div>
              <div className="form-group span-2">
                <div className="form-label">Keywords</div>
                <input
                  className="form-input"
                  value={sourceForm.keywords}
                  onChange={(e) => setSourceForm((form) => ({ ...form, keywords: e.target.value }))}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>Source runs</h2></div>
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
                  <td><StatusPill value={run.status} /></td>
                  <td>{run.max_leads || "-"}</td>
                  <td>{run.total_scraped || 0}</td>
                  <td>{run.unique_count || "-"}</td>
                  <td>{run.duplicate_count || "-"}</td>
                  <td>{fmtDate(run.started_at)}</td>
                  <td>
                    <div className="row-actions">
                      <Link className="btn xs" to={runPath(filename, run.id)}>View logs</Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Lead universe and source segments</h2>
          <div className="topbar-actions">
            <button className="btn sm" onClick={handleRunNext} disabled={sourceBusy || !selectedUniverse}>Run next</button>
            <button className="btn primary sm" onClick={handleRunAll} disabled={sourceBusy || !selectedUniverse}>Run all queued</button>
            <button className="btn sm" onClick={handlePauseAll} disabled={sourceBusy || !selectedUniverse}>Pause</button>
          </div>
        </div>
        <div className="card-body">
          <div className="source-run-grid">
            <div className="form-group">
              <div className="form-label">Universe</div>
              <select
                className="form-input"
                value={selectedUniverseId}
                onChange={(e) => setSelectedUniverseId(e.target.value)}
              >
                {universes.length === 0 && <option value="">No universe yet</option>}
                {universes.map((universe) => (
                  <option key={universe.id} value={universe.id}>{universe.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <div className="form-label">New universe name</div>
              <input
                className="form-input"
                value={universeForm.name}
                onChange={(e) => setUniverseForm((form) => ({ ...form, name: e.target.value }))}
                placeholder="US CTO search universe"
              />
            </div>
            <div className="form-group">
              <div className="form-label">Target leads</div>
              <input
                className="form-input"
                type="number"
                value={universeForm.target_leads}
                onChange={(e) => setUniverseForm((form) => ({ ...form, target_leads: e.target.value }))}
              />
            </div>
            <div className="form-group">
              <div className="form-label">Description</div>
              <input
                className="form-input"
                value={universeForm.description}
                onChange={(e) => setUniverseForm((form) => ({ ...form, description: e.target.value }))}
              />
            </div>
          </div>
          <button className="btn sm" onClick={handleCreateUniverse} disabled={sourceBusy}>
            <i className="ti ti-database-plus" aria-hidden="true" />
            Create universe
          </button>

          {selectedUniverse && (
            <div className="segment-create">
              <div className="source-run-grid">
                <div className="form-group">
                  <div className="form-label">Segment label</div>
                  <input
                    className="form-input"
                    value={segmentForm.label}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, label: e.target.value }))}
                    placeholder="US CTOs page 1"
                  />
                </div>
                <div className="form-group">
                  <div className="form-label">Target leads</div>
                  <input
                    className="form-input"
                    type="number"
                    value={segmentForm.expected_count}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, expected_count: e.target.value }))}
                  />
                </div>
                <div className="form-group span-2">
                  <div className="form-label">Sales Navigator URL</div>
                  <input
                    className="form-input"
                    value={segmentForm.source_url}
                    onChange={(e) => setSegmentForm((form) => ({ ...form, source_url: e.target.value }))}
                    placeholder="https://www.linkedin.com/sales/search/people..."
                  />
                </div>
              </div>
              <button className="btn sm" onClick={handleAddSegment} disabled={sourceBusy}>
                <i className="ti ti-plus" aria-hidden="true" />
                Add source segment
              </button>
            </div>
          )}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Segment</th>
                <th>Source URL</th>
                <th>Status</th>
                <th>Scraped</th>
                <th>Unique</th>
                <th>Duplicates</th>
                <th>Stop reason</th>
                <th>Last run</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sourceSegments.length === 0 && <EmptyRow colSpan={9} text="No source segments yet." />}
              {sourceSegments.map((segment) => (
                <tr key={segment.id}>
                  <td>{segment.label || "-"}</td>
                  <td className="truncate wide">{segment.source_url}</td>
                  <td><StatusPill value={segment.status} /></td>
                  <td>{segment.scraped_count || 0}</td>
                  <td>{segment.unique_count || 0}</td>
                  <td>{segment.duplicate_count || 0}</td>
                  <td>{segment.stop_reason || "-"}</td>
                  <td>
                    {segment.last_run_id ? (
                      <RunLink
                        filename={filename}
                        run={runs.find((run) => run.id === segment.last_run_id) || segment.last_run_id}
                      />
                    ) : "-"}
                  </td>
                  <td><button className="btn xs" onClick={() => handleRunSegment(segment.id)} disabled={sourceBusy}>Run</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
