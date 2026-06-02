import axios from "axios";

const BASE = "http://localhost:8000/api";

export const startRun = (body) => axios.post(`${BASE}/runs/start`, body);
export const getRuns = () => axios.get(`${BASE}/runs`);
export const getRun = (id) => axios.get(`${BASE}/runs/${id}`);
export const getRunLeads = (id, params) =>
  axios.get(`${BASE}/runs/${id}/leads`, { params });
export const getRunEvents = (id) => axios.get(`${BASE}/runs/${id}/events`);
export const exportRun = (id) => axios.get(`${BASE}/runs/${id}/leads/export`);
export const getCampaigns = () => axios.get(`${BASE}/campaigns`);
export const getKnowledgeBases = () => axios.get(`${BASE}/knowledge-bases`);
export const personaliseRun = (runId, campaign) =>
  axios.post(`${BASE}/runs/${runId}/personalise`, { campaign });

export const openWS = (run_id, onMsg) => {
  const ws = new WebSocket(`ws://localhost:8000/ws/runs/${run_id}`);
  ws.onmessage = (event) => onMsg(JSON.parse(event.data));
  return ws;
};
