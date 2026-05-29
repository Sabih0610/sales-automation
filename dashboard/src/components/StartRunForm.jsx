import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { startRun } from "../api";

const parseList = (value) =>
  value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

function StartRunForm({ onClose }) {
  const navigate = useNavigate();
  const [titles, setTitles] = useState(
    "CTO, CIO, CXO, Head of Data, VP Engineering"
  );
  const [keywords, setKeywords] = useState("Microsoft Fabric");
  const [maxLeads, setMaxLeads] = useState(1000);
  const [geos, setGeos] = useState("");
  const [industries, setIndustries] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await startRun({
        titles: parseList(titles),
        keywords,
        max_leads: Number(maxLeads) || 1000,
        geos: parseList(geos),
        industries: parseList(industries),
        company_sizes: [],
      });
      onClose?.();
      navigate(`/run/${response.data.id}`);
    } catch (err) {
      if (err.response?.status === 409) {
        setError("A pipeline run is already active.");
      } else {
        setError(err.response?.data?.detail || "Could not start the run.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="run-form" onSubmit={submit}>
      <label>
        Titles
        <textarea
          rows="3"
          value={titles}
          onChange={(event) => setTitles(event.target.value)}
        />
      </label>

      <label>
        Keywords
        <input
          type="text"
          value={keywords}
          onChange={(event) => setKeywords(event.target.value)}
        />
      </label>

      <div className="form-grid">
        <label>
          Max leads
          <input
            type="number"
            min="1"
            value={maxLeads}
            onChange={(event) => setMaxLeads(event.target.value)}
          />
        </label>
        <label>
          Geos
          <input
            type="text"
            value={geos}
            onChange={(event) => setGeos(event.target.value)}
            placeholder="United States, Canada"
          />
        </label>
      </div>

      <label>
        Industries
        <input
          type="text"
          value={industries}
          onChange={(event) => setIndustries(event.target.value)}
          placeholder="Software, IT Services"
        />
      </label>

      {error && <p className="form-error">{error}</p>}

      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="button primary" disabled={submitting}>
          {submitting ? "Starting..." : "Start run"}
        </button>
      </div>
    </form>
  );
}

export default StartRunForm;
