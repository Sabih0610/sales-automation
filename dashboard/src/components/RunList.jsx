import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getRuns } from "../api";
import StartRunForm from "./StartRunForm";

const formatDate = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

function RunList() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  useEffect(() => {
    let mounted = true;
    getRuns()
      .then((response) => {
        if (mounted) {
          setRuns(response.data);
          setError("");
        }
      })
      .catch(() => {
        if (mounted) setError("Could not reach the API at localhost:8000.");
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div>
      <div className="page-title">
        <div>
          <h1>Pipeline runs</h1>
        </div>
        <button
          className="button primary"
          type="button"
          onClick={() => setShowForm(true)}
        >
          New Run
        </button>
      </div>

      <section className="panel">
        {error && <p className="inline-error">{error}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Started</th>
                <th>Status</th>
                <th>Scraped</th>
                <th>Warm</th>
                <th>Cold</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td className="mono">{run.id.slice(0, 8)}</td>
                  <td>{formatDate(run.started_at)}</td>
                  <td>
                    <span className={`status-badge ${run.status.toLowerCase()}`}>
                      {run.status}
                    </span>
                  </td>
                  <td>{run.total_scraped}</td>
                  <td>{run.total_warm}</td>
                  <td>{run.total_cold}</td>
                  <td>
                    <Link className="table-link" to={`/run/${run.id}`}>
                      View
                    </Link>
                  </td>
                </tr>
              ))}
              {!loading && runs.length === 0 && (
                <tr>
                  <td colSpan="7" className="empty-cell">
                    No runs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {showForm && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal" role="dialog" aria-modal="true">
            <div className="panel-head">
              <h2>Start run</h2>
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowForm(false)}
                aria-label="Close"
              >
                x
              </button>
            </div>
            <StartRunForm onClose={() => setShowForm(false)} />
          </section>
        </div>
      )}
    </div>
  );
}

export default RunList;
