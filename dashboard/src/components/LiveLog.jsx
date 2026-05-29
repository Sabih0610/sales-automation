import { useEffect, useRef, useState } from "react";
import { getRunEvents, openWS } from "../api";

const summarize = (payload = {}) => {
  const text = JSON.stringify(payload);
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
};

const timeOnly = (value) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value.slice(11, 19) : date.toTimeString().slice(0, 8);
};

function LiveLog({ runId }) {
  const [events, setEvents] = useState([]);
  const [wsReady, setWsReady] = useState(false);
  const wsReadyRef = useRef(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    let mounted = true;
    let ws;

    const loadEvents = async () => {
      try {
        const response = await getRunEvents(runId);
        if (mounted) {
          setEvents(response.data.slice().reverse().slice(-20));
        }
      } catch {
        if (mounted) setWsReady(false);
      }
    };

    loadEvents();
    ws = openWS(runId, (event) => {
      setEvents((current) => [...current, event].slice(-20));
    });
    ws.onopen = () => {
      wsReadyRef.current = true;
      if (mounted) setWsReady(true);
    };
    ws.onerror = () => {
      wsReadyRef.current = false;
      if (mounted) setWsReady(false);
    };
    ws.onclose = () => {
      wsReadyRef.current = false;
      if (mounted) setWsReady(false);
    };

    const fallback = window.setInterval(() => {
      if (!wsReadyRef.current) loadEvents();
    }, 5000);

    return () => {
      mounted = false;
      window.clearInterval(fallback);
      ws?.close();
    };
  }, [runId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [events]);

  return (
    <section className="panel live-log">
      <div className="panel-head">
        <h2>Live log</h2>
        <span className={`dot ${wsReady ? "online" : "offline"}`} />
      </div>
      <div className="log-list">
        {events.length === 0 && <p className="empty">No events yet.</p>}
        {events.map((event, index) => (
          <div className="log-row" key={`${event.timestamp}-${index}`}>
            <time>{timeOnly(event.timestamp)}</time>
            <strong>{event.agent_name}</strong>
            <span>{event.event_type}</span>
            <small>{summarize(event.payload)}</small>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}

export default LiveLog;
