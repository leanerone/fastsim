const BASE = '/api/v1';

export class ApiError extends Error {
  constructor(status, message, info = null) {
    super(message);
    this.status = status;
    this.info = info; // {code, message, hint, raw} when the backend provided it
    this.code = info?.code || '';
  }
}

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = (data && data.detail) || data || res.statusText;
    if (detail && typeof detail === 'object') {
      throw new ApiError(res.status, detail.message || JSON.stringify(detail), detail);
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

export const api = {
  health: () => request('/health'),
  overview: () => request('/overview'),

  sessions: () => request('/sessions'),
  session: (id) => request(`/sessions/${encodeURIComponent(id)}`),
  createSession: (body) => request('/sessions', { method: 'POST', body }),
  deleteSession: (id) => request(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  connect: (id) => request(`/sessions/${encodeURIComponent(id)}/connect`, { method: 'POST' }),
  disconnect: (id) => request(`/sessions/${encodeURIComponent(id)}/disconnect`, { method: 'POST' }),

  freePort: (host = '127.0.0.1', start = 5000) =>
    request(`/ports/free?host=${encodeURIComponent(host)}&start=${start}`),
  checkPort: (host, port) =>
    request(`/ports/check?host=${encodeURIComponent(host)}&port=${port}`),

  logs: (id, params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null));
    return request(`/sessions/${encodeURIComponent(id)}/logs?${q}`);
  },
  send: (id, sml) => request(`/sessions/${encodeURIComponent(id)}/send`, { method: 'POST', body: { sml } }),

  variables: (id) => request(`/sessions/${encodeURIComponent(id)}/variables`),
  setVariable: (id, vid, value) => request(`/sessions/${encodeURIComponent(id)}/variables`, { method: 'PUT', body: { vid, value } }),
  setAlarm: (id, alid, on) => request(`/sessions/${encodeURIComponent(id)}/alarms/${encodeURIComponent(alid)}/${on ? 'set' : 'clear'}`, { method: 'POST' }),
  triggerEvent: (id, ceid, values) => request(`/sessions/${encodeURIComponent(id)}/events/${encodeURIComponent(ceid)}/trigger`, { method: 'POST', body: values ? { values } : {} }),
  controlState: (id, target) => request(`/sessions/${encodeURIComponent(id)}/control-state`, { method: 'POST', body: { target } }),
  remoteCommand: (id, rcmd, params) => request(`/sessions/${encodeURIComponent(id)}/remote-command`, { method: 'POST', body: { rcmd, params } }),
  querySv: (id, svids) => request(`/sessions/${encodeURIComponent(id)}/query-sv`, { method: 'POST', body: { svids } }),
  subscribe: (id, ceid, rptid, svids) => request(`/sessions/${encodeURIComponent(id)}/subscribe`, { method: 'POST', body: { ceid, rptid, svids } }),

  recordStart: (id) => request(`/sessions/${encodeURIComponent(id)}/record/start`, { method: 'POST' }),
  recordStop: (id) => request(`/sessions/${encodeURIComponent(id)}/record/stop`, { method: 'POST' }),
  replay: (id, recording, speed = 1) => request(`/sessions/${encodeURIComponent(id)}/replay`, { method: 'POST', body: { recording, speed } }),

  profiles: () => request('/profiles'),
  profile: (name) => request(`/profiles/${encodeURIComponent(name)}`),
  profileText: (name) => request(`/profiles/${encodeURIComponent(name)}/text`),
  saveProfile: (name, text) => request(`/profiles/${encodeURIComponent(name)}`, { method: 'PUT', body: { text } }),
  validateProfile: (text) => request('/profiles/validate', { method: 'POST', body: { text } }),

  scenarios: () => request('/scenarios'),
  scenarioManifest: () => request('/scenarios/manifest'),
  scenarioText: (name) => request(`/scenarios/${encodeURIComponent(name)}/text`),
  runScenario: (sid, name) => request(`/sessions/${encodeURIComponent(sid)}/scenario/${encodeURIComponent(name)}/run`, { method: 'POST', body: {} }),
};

export function openSessionSocket(sessionId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return new WebSocket(`${proto}://${location.host}/ws/${encodeURIComponent(sessionId)}`);
}

export function openGlobalSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return new WebSocket(`${proto}://${location.host}/ws`);
}
