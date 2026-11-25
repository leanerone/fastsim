/* Shared UI primitives: icons, formatting, modals, toasts, SML rendering. */

const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  terminal: '<path d="m5 7 4 5-4 5"/><path d="M13 17h6"/>',
  play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h8M16 18h4"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="14" cy="18" r="2"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5v-15Z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H20v3H6.5A2.5 2.5 0 0 1 4 20.5Z"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 6.3"/><path d="M20 4v7h-7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  plug: '<path d="M9 3v6M15 3v6M6 9h12v3a6 6 0 0 1-12 0V9ZM12 18v3"/>',
  unplug: '<path d="M9 3v6M15 3v6M6 9h12v3a6 6 0 0 1-12 0V9ZM12 18v3"/><path d="m3 3 18 18"/>',
  trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13M10 11v5M14 11v5"/>',
  check: '<path d="m5 13 4 4L19 7"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  alert: '<path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v5M12 17.2v.1"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.1"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
  save: '<path d="M5 3h11l3 3v15H5V3Z"/><path d="M8 3v6h8V3M8 21v-6h8v6"/>',
  record: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  activity: '<path d="M3 12h4l2.5-7 5 14 2.5-7H21"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
  file: '<path d="M6 2h8l4 4v16H6V2Z"/><path d="M14 2v5h5"/>',
  external: '<path d="M14 4h6v6M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  zap: '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/>',
  box: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  send: '<path d="M21 3 10.5 13.5M21 3l-6.5 18-4-7.5L3 9.5 21 3Z"/>',
  link: '<path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5"/>',
  wave: '<path d="M2 12h3l2-5 3 10 3-14 3 18 2-9h4"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  playSmall: '<path d="m8 5 11 7-11 7V5Z"/>',
};

export function icon(name, size = 16) {
  const body = ICONS[name] || ICONS.info;
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}

export function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((node) => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const pad = (n, len = 2) => String(n).padStart(len, '0');

export function fmtClock(ts, withMs = false) {
  if (!ts) return '--:--:--';
  const d = new Date(ts * 1000);
  const base = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  return withMs ? `${base}.${pad(d.getMilliseconds(), 3)}` : base;
}

export function fmtDate(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function fmtDateTime(ts) {
  if (!ts) return '—';
  return `${fmtDate(ts)} ${fmtClock(ts)}`;
}

export function fmtRelative(ts) {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - ts;
  if (diff < 5) return '刚刚';
  if (diff < 60) return `${Math.floor(diff)} 秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return fmtDate(ts);
}

export const STATE_LABELS = {
  hsms: {
    NOT_CONNECTED: '未连接',
    CONNECTED_NOT_SELECTED: '已连接 · 等待握手',
    SELECTED: '链路已建立',
  },
  communication: {
    DISABLED: '通信关闭',
    NOT_COMMUNICATING: '未建立通信',
    WAIT_CRA: '等待建立通信',
    WAIT_DELAY: '等待延迟',
    COMMUNICATING: '通信中',
  },
  control: {
    EQUIPMENT_OFFLINE: '设备离线',
    ATTEMPT_ONLINE: '尝试上线',
    HOST_OFFLINE: '主机离线',
    ONLINE_LOCAL: '本地联机',
    ONLINE_REMOTE: '远程联机',
    ONLINE: '联机',
  },
};

const STATE_KIND_TITLES = {
  hsms: 'HSMS 链路状态',
  communication: 'GEM 通信状态',
  control: 'GEM 控制状态',
};

export function stateTone(kind, value) {
  if (kind === 'hsms') {
    if (value === 'SELECTED') return 'ok';
    if (value === 'CONNECTED_NOT_SELECTED') return 'warn';
    return 'idle';
  }
  if (kind === 'communication') {
    if (value === 'COMMUNICATING') return 'ok';
    if (value === 'WAIT_CRA') return 'warn';
    return 'idle';
  }
  if (value === 'ONLINE_REMOTE' || value === 'ONLINE') return 'ok';
  if (value === 'ONLINE_LOCAL') return 'info';
  if (value === 'ATTEMPT_ONLINE') return 'warn';
  return 'idle';
}

export function stateLabel(kind, value) {
  return STATE_LABELS[kind]?.[value] || value || '—';
}

export function statePills(states = {}) {
  const rows = [
    ['hsms', states.hsms],
    ['communication', states.communication],
    ['control', states.control],
  ];
  return rows.map(([kind, value]) => {
    const tone = stateTone(kind, value);
    return `<span class="pill ${tone === 'info' ? 'ok' : tone}" title="${esc(STATE_KIND_TITLES[kind] || kind)}：${esc(value || '—')}">
      <span class="dot ${tone === 'idle' ? 'idle' : tone}"></span>${esc(stateLabel(kind, value))}
    </span>`;
  }).join('');
}

/** Turn any thrown error into a readable message + fix hint for the user. */
export function explainError(err) {
  if (err?.info?.message) {
    return { message: err.info.message, hint: err.info.hint || '', code: err.info.code || '' };
  }
  if (err?.issue?.message) {
    return { message: err.issue.message, hint: err.issue.hint || '', code: err.issue.code || '' };
  }
  const text = String(err?.message || err || '未知错误');
  if (/failed to fetch|networkerror|load failed|fetch failed/i.test(text)) {
    return { message: '无法连接后端服务', hint: '请确认 FastSim 后端已启动（run.bat / run.sh），然后刷新页面。', code: 'BACKEND_DOWN' };
  }
  return { message: text, hint: '', code: '' };
}

/** Toast an error with its hint as a second line. */
export function toastError(err, timeout = 5200) {
  const { message, hint } = explainError(err);
  toast(message, 'err', timeout, hint);
}

const TOKEN_RE = /<([A-Z]\w*)|("(?:[^"\\]|\\.)*")|(\b\d+(?:\.\d+)?\b)|([<>\[\]])/g;

export function smlHighlight(text) {
  if (!text) return '';
  return String(text).split('\n').map((line) => {
    if (/^\s*S\d+F\d+/.test(line)) return `<span class="hdr">${esc(line)}</span>`;
    let out = '';
    let last = 0;
    let match;
    TOKEN_RE.lastIndex = 0;
    while ((match = TOKEN_RE.exec(line))) {
      out += esc(line.slice(last, match.index));
      if (match[1]) out += `<span class="tag">&lt;${esc(match[1])}</span>`;
      else if (match[2]) out += `<span class="str">${esc(match[2])}</span>`;
      else if (match[3]) out += `<span class="num">${esc(match[3])}</span>`;
      else out += `<span class="br">${esc(match[4])}</span>`;
      last = match.index + match[0].length;
    }
    out += esc(line.slice(last));
    return out;
  }).join('\n');
}

export function summarizeSml(log) {
  if (!log) return '';
  if (log.kind === 'control') return log.desc || '控制帧';
  const body = (log.sml || '').replace(/\s+/g, ' ').trim();
  return body.length > 150 ? `${body.slice(0, 150)}…` : body;
}

export function toast(message, kind = 'ok', timeout = 3200, hint = '') {
  const stack = document.getElementById('toasts');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.innerHTML = `${icon(kind === 'err' ? 'alert' : kind === 'warn' ? 'info' : 'check', 14)}<span>${esc(message)}${hint ? `<small class="toast-hint">${esc(hint)}</small>` : ''}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .2s, transform .2s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    setTimeout(() => el.remove(), 220);
  }, timeout);
}

export function openModal({ title, subtitle = '', body = '', footer = '', wide = false, onMount, onClose }) {
  const root = document.getElementById('modal-root');
  const layer = document.createElement('div');
  layer.className = 'modal-layer';
  layer.innerHTML = `
    <div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <div><h3>${esc(title)}</h3>${subtitle ? `<p>${esc(subtitle)}</p>` : ''}</div>
        <button class="icon-btn" data-close aria-label="关闭">${icon('x')}</button>
      </div>
      <div class="modal-body">${body}</div>
      ${footer ? `<div class="modal-foot">${footer}</div>` : ''}
    </div>`;
  root.appendChild(layer);
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    layer.remove();
    document.removeEventListener('keydown', onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  layer.addEventListener('click', (e) => {
    if (e.target === layer || e.target.closest('[data-close]')) close();
  });
  if (onMount) onMount(layer, close);
  setTimeout(() => layer.querySelector('input, select, textarea, button')?.focus(), 30);
  return close;
}

export function confirmDialog({ title, message, confirmText = '确认', danger = true }) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    openModal({
      title,
      body: `<p style="color:var(--text-soft);font-size:13px;line-height:1.7">${esc(message)}</p>`,
      footer: `<button class="btn" data-cancel>取消</button>
               <button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(confirmText)}</button>`,
      onClose: () => finish(false),
      onMount(layer, dismiss) {
        layer.querySelector('[data-cancel]').onclick = () => { finish(false); dismiss(); };
        layer.querySelector('[data-ok]').onclick = () => { finish(true); dismiss(); };
      },
    });
  });
}

export function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function scenarioSteps(text) {
  const steps = [];
  const lines = String(text || '').split('\n');
  let current = null;
  for (const line of lines) {
    const m = line.match(/^\s*-\s+action:\s*([\w-]+)/);
    if (m) {
      current = { action: m[1], detail: '' };
      steps.push(current);
      continue;
    }
    if (!current) continue;
    const kv = line.match(/^\s{6,}([\w-]+):\s*(.+)$/);
    if (kv && current.detail.length < 70) {
      const value = kv[2].trim();
      const short = value.length > 34 ? `${value.slice(0, 34)}…` : value;
      current.detail += `${current.detail ? ' · ' : ''}${kv[1]}=${short}`;
    }
  }
  return steps;
}

export function debounce(fn, wait = 180) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}
