import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getRun } from "../api";
import LeadTable from "./LeadTable";
import LiveLog from "./LiveLog";
import StatsCards from "./StatsCards";

const statusClass = (status = "") => status.toLowerCase();

function RunDetail() {
  const { id } = useParams();
  const [run, setRun] = useState(null);
  const [error, setError] = useState("");
  const shouldPoll = !run || run.status === "RUNNING";

  useEffect(() => {
    let mounted = true;
    let timer;

    const loadRun = async () => {
      try {
        const response = await getRun(id);
        if (mounted) setRun(response.data);
      } catch {
        if (mounted) setError("Run not found.");
      }
    };

    loadRun();
    if (shouldPoll) {
      timer = window.setInterval(loadRun, 3000);
    }

    return () => {
      mounted = false;
      if (timer) window.clearInterval(timer);
    };
  }, [id, shouldPoll]);

  if (error) {
    return (
      <section className="panel">
        <p className="form-error">{error}</p>
        <Link to="/" className="button secondary">
          Back to runs
        </Link>
      </section>
    );
  }

  if (!run) {
    return <p className="loading">Loading run...</p>;
  }

  return (
    <div className="run-detail">
      <div className="page-title">
        <div>
          <Link to="/" className="back-link">
            Runs
          </Link>
          <h1>Run {run.id.slice(0, 8)}</h1>
        </div>
        <span className={`status-badge ${statusClass(run.status)}`}>
          {run.status}
        </span>
      </div>

      <div className="detail-grid">
        <section className="panel stats-panel">
          <div className="panel-head">
            <h2>Progress</h2>
          </div>
          <StatsCards run={run} />
        </section>
        <LiveLog runId={run.id} />
      </div>

      <LeadTable runId={run.id} />
    </div>
  );
}

export default RunDetail;
