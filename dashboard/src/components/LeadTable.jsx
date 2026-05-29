import { useEffect, useState } from "react";
import { exportRun, getRunLeads } from "../api";

const LIMIT = 50;

const filters = [
  ["", "All"],
  ["warm", "Warm"],
  ["cold", "Cold"],
  ["no_email", "No Email"],
];

function LeadTable({ runId }) {
  const [leads, setLeads] = useState([]);
  const [segment, setSegment] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setLoading(true);
      try {
        const response = await getRunLeads(runId, {
          segment: segment || undefined,
          limit: LIMIT,
          offset,
        });
        if (mounted) {
          setLeads(response.data);
          setError("");
        }
      } catch {
        if (mounted) setError("Could not load leads.");
      } finally {
        if (mounted) setLoading(false);
      }
    };
    load();
    return () => {
      mounted = false;
    };
  }, [runId, segment, offset]);

  const changeSegment = (value) => {
    setSegment(value);
    setOffset(0);
  };

  const triggerExport = async () => {
    setExporting(true);
    try {
      const response = await exportRun(runId);
      window.alert(`Exported files:\n${response.data.files.join("\n")}`);
    } catch (err) {
      window.alert(err.response?.data?.detail || "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="panel lead-panel">
      <div className="panel-head table-head">
        <h2>Leads</h2>
        <div className="table-actions">
          <div className="segmented">
            {filters.map(([value, label]) => (
              <button
                key={value || "all"}
                className={segment === value ? "active" : ""}
                type="button"
                onClick={() => changeSegment(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            className="button primary"
            type="button"
            onClick={triggerExport}
            disabled={exporting}
          >
            {exporting ? "Exporting..." : "Export"}
          </button>
        </div>
      </div>

      <div className="table-wrap">
        {error && <p className="inline-error">{error}</p>}
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Title</th>
              <th>Company</th>
              <th>Email</th>
              <th>Confidence</th>
              <th>Segment</th>
              <th>LinkedIn</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead) => (
              <tr key={lead.id}>
                <td>{lead.full_name || "-"}</td>
                <td>{lead.title || "-"}</td>
                <td>{lead.company || "-"}</td>
                <td>{lead.email || "-"}</td>
                <td>
                  <span className="badge neutral">
                    {lead.email_confidence || "none"}
                  </span>
                </td>
                <td>
                  <span className={`badge ${lead.segment.toLowerCase()}`}>
                    {lead.segment}
                  </span>
                </td>
                <td>
                  {lead.linkedin_url ? (
                    <a
                      className="linkedin-link"
                      href={lead.linkedin_url}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Open LinkedIn profile for ${lead.full_name}`}
                    >
                      in
                    </a>
                  ) : (
                    "-"
                  )}
                </td>
              </tr>
            ))}
            {!loading && leads.length === 0 && (
              <tr>
                <td colSpan="7" className="empty-cell">
                  No leads found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="pagination">
        <button
          className="button secondary"
          type="button"
          onClick={() => setOffset(Math.max(0, offset - LIMIT))}
          disabled={offset === 0}
        >
          Previous
        </button>
        <span>
          {leads.length ? `${offset + 1}-${offset + leads.length}` : "0-0"}
        </span>
        <button
          className="button secondary"
          type="button"
          onClick={() => setOffset(offset + LIMIT)}
          disabled={leads.length < LIMIT}
        >
          Next
        </button>
      </div>
    </section>
  );
}

export default LeadTable;
