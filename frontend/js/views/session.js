import { api, openSessionSocket } from '../api.js';
import {
  confirmDialog, debounce, downloadText, esc, explainError, fmtClock, fmtDateTime,
  hydrateIcons, icon, smlHighlight, stateLabel, statePills, toast, toastError,
} from '../ui.js';

/* Message library is role-aware: a host sends requests, an equipment sends
   unsolicited reports. Templates with `form` get a parameter form so users
   don't have to hand-edit SML. */
const MSG_LIB = [
  { code: 'S1F1 W', group: '通信建立', desc: '在线请求（Are You There）', roles: ['host'] },
  { code: 'S1F13 W', group: '通信建立', desc: '建立通信请求', roles: ['host'], body: '<L [2]\n  <A "FASTSIM">\n  <A "1.0.0">\n>' },
  { code: 'S1F15 W', group: '通信建立', desc: '请求离线', roles: ['host'] },
  { code: 'S1F17 W', group: '通信建立', desc: '请求在线', roles: ['host'] },
  { code: 'S1F3 W', group: '状态与变量', desc: '查询状态变量', roles: ['host'], form: 'svquery' },
  { code: 'S2F13 W', group: '状态与变量', desc: '读取设备常量', roles: ['host'], form: 'ecquery' },
  { code: 'S2F15 W', group: '状态与变量', desc: '写入设备常量', roles: ['host'], form: 'ecwrite' },
  { code: 'S2F17 W', group: '状态与变量', desc: '读取时钟', roles: ['host'] },
  { code: 'S2F31 W', group: '状态与变量', desc: '设置时钟', roles: ['host'], body: '<A "260101120000">' },
  { code: 'S2F33 W', group: '事件与报告', desc: '定义报告', roles: ['host'], body: '<L [2]\n  <U4 0>\n  <L [1]\n    <L [2]\n      <U4 7001>\n      <L [3]\n        <U4 1001>\n        <U4 1002>\n        <U4 1003>\n      >\n    >\n  >\n>' },
  { code: 'S2F35 W', group: '事件与报告', desc: '链接事件与报告', roles: ['host'], body: '<L [2]\n  <U4 0>\n  <L [1]\n    <L [2]\n      <U4 6001>\n      <L [1]\n        <L [2]\n          <U4 7001>\n          <L []>\n        >\n      >\n    >\n  >\n>' },
  { code: 'S2F37 W', group: '事件与报告', desc: '使能/禁用事件', roles: ['host'], body: '<L [3]\n  <U4 0>\n  <BOOLEAN TRUE>\n  <L [1]\n    <U4 6001>\n  >\n>' },
  { code: 'S6F15 W', group: '事件与报告', desc: '请求事件报告', roles: ['host'], form: 'ceidrequest' },
  { code: 'S2F41 W', group: '远程命令', desc: '远程命令', roles: ['host'], form: 'rcmd' },
  { code: 'S5F3 W', group: '报警', desc: '报警使能/禁用', roles: ['host'], form: 'alarmenable' },
  { code: 'S5F5 W', group: '报警', desc: '查询已设置报警', roles: ['host'], body: '<L [0]>' },
  { code: 'S5F7 W', group: '报警', desc: '查询已使能报警', roles: ['host'], body: '<L [0]>' },
  { code: 'S7F5 W', group: '配方管理', desc: 'PP 下载请求', roles: ['host'], body: '<L [1]\n  <A "RECIPE-X">\n>' },
  { code: 'S7F19 W', group: '配方管理', desc: 'PP 列表', roles: ['host'] },
  { code: 'S5F1 W', group: '设备主动上报', desc: '报警上报', roles: ['equipment'], body: '<L [3]\n  <B 0x81>\n  <U4 5001>\n  <A "CHAMBER PRESSURE HIGH">\n>' },
  { code: 'S6F11 W', group: '设备主动上报', desc: '采集事件上报', roles: ['equipment'], body: '<L [3]\n  <U4 0>\n  <U4 6003>\n  <L [0]>\n>' },
  { code: 'S10F1', group: '设备主动上报', desc: '终端显示消息', roles: ['equipment'], body: '<L [2]\n  <B 0x00>\n  <A "HELLO OPERATOR">\n>' },
];

const TABS = [
  { id: 'logs', label: '消息记录', iconName: 'terminal' },
  { id: 'messages', label: '发送消息', iconName: 'send' },
  { id: 'gem', label: 'GEM 操作', iconName: 'sliders' },
  { id: 'connection', label: '连接配置', iconName: 'link' },
  { id: 'record', label: '录制回放', iconName: 'record' },
];

const MESSAGE_NAMES = {
  S1F1: '在线请求', S1F2: '在线数据', S1F3: '状态变量请求', S1F4: '状态变量数据',
  S1F13: '建立通信请求', S1F14: '建立通信响应', S1F15: '请求离线', S1F16: '离线确认',
  S1F17: '请求在线', S1F18: '在线确认', S2F13: '设备常量请求', S2F14: '设备常量数据',
  S2F15: '设备常量更新', S2F16: '设备常量更新响应', S2F33: '定义报告', S2F34: '定义报告响应',
  S2F35: '链接事件与报告', S2F36: '事件报告链接响应', S2F37: '使能或禁用事件',
  S2F38: '事件使能响应', S2F41: '主机远程命令', S2F42: '远程命令响应',
  S5F1: '报警报告', S5F2: '报警响应', S5F5: '报警列表请求', S5F6: '报警列表数据',
  S6F11: '采集事件报告', S6F12: '采集事件响应', S7F1: '配方加载请求', S7F2: '配方加载响应',
  S7F5: '配方内容请求', S7F6: '配方内容数据', S9F1: '未知设备标识', S9F3: '未知消息流',
  S9F5: '未知消息功能', S9F7: '非法数据', S9F9: '事务超时', S10F3: '终端显示消息', S10F4: '终端显示响应',
};

const HCACK_TEXT = {
  0: '命令已接受并执行', 1: '命令不存在', 2: '当前无法执行',
  3: '参数不合法', 4: '已启动但未完成', 5: '命令被拒绝',
};
const S9_TEXT = {
  S9F1: '设备标识（Device ID）不匹配', S9F3: '未知消息流', S9F5: '未知消息功能',
  S9F7: '非法数据', S9F9: '对端事务超时',
};

const CONTROL_STATES = [
  { value: 'EQUIPMENT_OFFLINE', label: '设备离线' },
  { value: 'ATTEMPT_ONLINE', label: '尝试上线' },
  { value: 'HOST_OFFLINE', label: '主机离线' },
  { value: 'ONLINE_LOCAL', label: '本地联机' },
  { value: 'ONLINE_REMOTE', label: '远程联机' },
];

function logEntryKey(entry) {
  return `${entry.ts}|${entry.system_bytes ?? ''}|${entry.dir}|${entry.sf ?? ''}|${entry.kind}`;
}

function messageMeaning(sf) {
  return MESSAGE_NAMES[sf] || 'SECS-II 业务报文';
}

function fmtVal(v) {
  if (v == null) return '—';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  return String(v);
}

function toByte(v) {
  if (typeof v === 'number') return v;
  if (typeof v === 'string') return parseInt(v, 16);
  return NaN;
}

export async function render(ctx) {
  const view = document.getElementById('view');
  const requested = ctx.params[0] ? decodeURIComponent(ctx.params[0]) : '';
  let alive = true;
  let socket = null;
  let reconnectTimer = null;
  let refreshTimer = null;
  let wsBackoff = 1000;

  let sessionsList = await api.sessions();
  if (!sessionsList.length) {
    paintEmpty();
    return { cleanup() { alive = false; } };
  }

  const savedId = localStorage.getItem('fastsim.activeSession') || '';
  let currentId = sessionsList.some((s) => s.id === requested) ? requested
    : sessionsList.some((s) => s.id === savedId) ? savedId : sessionsList[0].id;
  if (requested !== currentId) history.replaceState(null, '', `#/sessions/${encodeURIComponent(currentId)}`);
  localStorage.setItem('fastsim.activeSession', currentId);

  let detail = null;
  let profile = null;
  let variables = null;
  let tab = 'logs';
  let logs = [];
  let logKeys = new Set();
  let kindCounts = { data: 0, control: 0 };
  let paused = false;
  let autoScroll = true;
  let showControl = false;
  let expandedLogs = new Set();
  let unseen = 0;
  let wsState = 'connecting';
  let composerText = 'S1F1 W';
  let lastResult = null;
  let recording = null;
  let activeForm = null;      // form type of the selected template
  let deviceState = null;     // host: values queried from the equipment (S1F3)
  let deviceStatePrev = null;
  let effectFeed = [];        // recent commands / alarms / events for the GEM tab
  const subscribedEvents = new Set();

  paintShell();
  await loadDetail();
  renderTab();
  connectSocket();
  refreshTimer = setInterval(() => {
    if (!document.hidden) patchStates(false);
  }, 8000);

  /* ------------------------------------------------------------ bootstrap */
  function paintEmpty() {
    view.innerHTML = `<div class="empty">
      <div class="empty-graphic">${icon('terminal', 40)}</div>
      <h3>没有可用的模拟会话</h3>
      <p>会话工作台用于收发 SML、观察实时链路与 GEM 事件。先创建一个会话开始联调。</p>
      <div class="empty-actions">
        <button class="btn primary" data-empty-new>${icon('plus', 14)}新建会话</button>
        <a class="btn" href="#/overview">返回总览</a>
      </div>
    </div>`;
    hydrateIcons(view);
    view.querySelector('[data-empty-new]').onclick = () => ctx.openNewSession();
  }

  function paintShell() {
    view.innerHTML = `
      <div class="page-head">
        <div>
          <div class="eyebrow">SESSION WORKBENCH</div>
          <h1 class="page-title">联调工作台</h1>
          <p class="page-sub">先确认通信状态，再发送消息。接收表示对端发来，发送表示当前会话发出。</p>
        </div>
      </div>
      <div class="session-top">
        <div class="session-identity">
          <h2 id="sess-name">…</h2>
          <span class="badge neutral" id="sess-role">—</span>
          <select class="select session-switch" id="session-switch" aria-label="切换会话"></select>
        </div>
        <div class="session-states" id="session-states"></div>
        <div class="session-actions">
          <button class="btn" id="btn-linktest">${icon('zap', 14)}S1F1 测试</button>
          <button class="btn ghost" id="btn-connect">${icon('plug', 14)}<span>启动链路</span></button>
          <button class="icon-btn" id="btn-reload" title="重新加载会话数据">${icon('refresh', 15)}</button>
        </div>
      </div>
      <div class="session-guide" id="session-guide"></div>
      <div class="tabs" id="tabs" role="tablist">
        ${TABS.map((t) => `<button class="tab" role="tab" data-tab="${t.id}">${icon(t.iconName, 14)}<span>${t.label}</span><span class="tab-count" data-count="${t.id}"></span></button>`).join('')}
      </div>
      <div id="tab-content"></div>`;
    hydrateIcons(view);

    view.querySelector('#session-switch').onchange = (e) => {
      ctx.navigate(`#/sessions/${encodeURIComponent(e.target.value)}`);
    };
    view.querySelectorAll('#tabs .tab').forEach((btn) => {
      btn.onclick = () => switchTab(btn.dataset.tab);
    });
    view.querySelector('#btn-connect').onclick = (e) => toggleConnect(e.currentTarget);
    view.querySelector('#btn-linktest').onclick = linktest;
    view.querySelector('#btn-reload').onclick = async () => {
      await loadDetail();
      renderTab();
      toast('会话数据已刷新');
    };
  }

  async function loadDetail() {
    try {
      detail = await api.session(currentId);
      const [vars, prof] = await Promise.all([
        api.variables(currentId),
        api.profile(detail.profile),
      ]);
      variables = vars;
      profile = prof;
      patchHeader();
      await loadLogs();
      if (detail.role === 'host' && detail.states?.communication === 'COMMUNICATING') {
        queryDeviceState(false);
      }
    } catch (e) {
      toastError(e);
    }
  }

  async function loadLogs() {
    const [dataRows, controlRows] = await Promise.all([
      api.logs(currentId, { kind: 'data', tail: 600 }),
      api.logs(currentId, { kind: 'control', tail: 100 }),
    ]);
    if (!alive) return;
    logs = [];
    logKeys = new Set();
    kindCounts = { data: 0, control: 0 };
    [...dataRows, ...controlRows]
      .sort((a, b) => (a.ts || 0) - (b.ts || 0))
      .forEach(addLogLocal);
    if (tab === 'logs') paintLogRows();
    updateCounts();
  }

  function patchHeader() {
    if (!detail) return;
    const el = view.querySelector('#sess-name');
    if (el) el.textContent = detail.name;
    const role = view.querySelector('#sess-role');
    if (role) {
      role.textContent = detail.role === 'host' ? '主机端' : '设备端';
      role.className = `badge role-${detail.role}`;
    }
    const sw = view.querySelector('#session-switch');
    if (sw) {
      sw.innerHTML = sessionsList.map((s) =>
        `<option value="${esc(s.id)}" ${s.id === currentId ? 'selected' : ''}>${esc(s.name)} · ${s.role === 'host' ? '主机端' : '设备端'}</option>`).join('');
    }
    const states = view.querySelector('#session-states');
    if (states) states.innerHTML = statePills(detail.states);
    const connect = view.querySelector('#btn-connect');
    if (connect) {
      const connected = detail.states?.hsms !== 'NOT_CONNECTED';
      connect.querySelector('span').textContent = connected ? '重启链路' : '启动链路';
      connect.title = connected ? '断开并重新启动监听/连接（会短暂断链）' : '启动 HSMS 链路';
    }
    patchGuide();
  }

  function patchGuide() {
    const guide = view.querySelector('#session-guide');
    if (!guide || !detail) return;
    const communicating = detail.states?.communication === 'COMMUNICATING';
    const issue = detail.issue && detail.issue.severity !== 'info' ? detail.issue : null;
    let peerId = '';
    try { peerId = JSON.parse(localStorage.getItem('fastsim.pairs') || '{}')[currentId] || ''; } catch { peerId = ''; }

    if (!communicating) {
      if (issue) {
        guide.className = `session-guide ${issue.severity === 'error' ? 'bad' : 'warn'}`;
        const action = (issue.code === 'PEER_UNREACHABLE' || issue.code === 'CONNECT_FAILED')
          ? '<button class="btn sm" data-guide-reconnect>重启链路</button>'
          : '<a class="btn sm" href="#/docs">排查步骤</a>';
        guide.innerHTML = `${icon('alert', 16)}<div><b>${esc(issue.message)}</b><span>${esc(issue.hint || '')}</span></div>${action}`;
        guide.querySelector('[data-guide-reconnect]')?.addEventListener('click', () => toggleConnect(null));
        return;
      }
      guide.className = 'session-guide warn';
      guide.innerHTML = `${icon('alert', 16)}<div><b>尚未建立 GEM 通信</b><span>检查对端是否已启动、IP 与端口是否一致；主机端应为主动连接，设备端应为被动监听。</span></div><a class="btn sm" href="#/docs">查看排查步骤</a>`;
      return;
    }

    guide.className = 'session-guide';
    if (detail.role === 'host') {
      const userSent = logs.some((l) => l.kind === 'data' && l.dir === 'out' && l.w && l.sf !== 'S1F13');
      if (!userSent) {
        guide.innerHTML = `${icon('check', 16)}<div><b>通信正常，可以开始验证</b><span>先发送 S1F1 确认链路，响应会显示在编辑器下方。</span></div><button class="btn sm" data-guide-send>去发送 S1F1</button>`;
      } else if (!deviceState) {
        guide.innerHTML = `${icon('check', 16)}<div><b>链路已验证</b><span>查询设备状态，了解机台当前的变量取值。</span></div><button class="btn sm" data-guide-query>查询设备状态</button>`;
      } else {
        guide.innerHTML = `${icon('check', 16)}<div><b>试试发送远程命令</b><span>在 GEM 操作里发送 START，观察设备状态变化与事件上报。</span></div><button class="btn sm" data-guide-gem>打开 GEM 操作</button>`;
      }
      guide.querySelector('[data-guide-send]')?.addEventListener('click', () => {
        composerText = 'S1F1 W';
        activeForm = null;
        switchTab('messages');
      });
      guide.querySelector('[data-guide-query]')?.addEventListener('click', () => {
        switchTab('gem');
        queryDeviceState(true);
      });
    } else {
      guide.innerHTML = `${icon('check', 16)}<div><b>设备端通信正常</b><span>触发报警或采集事件，观察主机端接收结果；收到的远程命令会显示在“实时动态”。</span></div>${peerId ? `<button class="btn sm" data-guide-peer="${esc(peerId)}">切换到配套主机端</button>` : '<button class="btn sm" data-guide-gem>打开 GEM 操作</button>'}`;
      guide.querySelector('[data-guide-peer]')?.addEventListener('click', (e) => {
        ctx.navigate(`#/sessions/${encodeURIComponent(e.currentTarget.dataset.guidePeer)}`);
      });
    }
    guide.querySelector('[data-guide-gem]')?.addEventListener('click', () => switchTab('gem'));
  }

  async function patchStates(showError = true) {
    try {
      const fresh = await api.session(currentId);
      detail = fresh;
      const idx = sessionsList.findIndex((s) => s.id === currentId);
      if (idx >= 0) sessionsList[idx] = { ...sessionsList[idx], ...fresh };
      patchHeader();
    } catch (e) {
      if (showError) toastError(e);
    }
  }

  /* ------------------------------------------------------------------ tabs */
  function switchTab(next) {
    if (tab === next) return;
    tab = next;
    if (next === 'logs') unseen = 0;
    renderTab();
  }

  function renderTab() {
    const content = view.querySelector('#tab-content');
    if (!content || !detail) return;
    view.querySelectorAll('#tabs .tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    updateCounts();
    if (tab === 'logs') renderLogsTab(content);
    else if (tab === 'messages') renderMessagesTab(content);
    else if (tab === 'gem') renderGemTab(content);
    else if (tab === 'connection') renderConnectionTab(content);
    else renderRecordTab(content);
  }

  function updateCounts() {
    const logCount = view.querySelector('[data-count="logs"]');
    const visibleTotal = showControl ? logs.length : kindCounts.data;
    if (logCount) logCount.textContent = unseen > 0 && tab !== 'logs' ? `+${unseen}` : (visibleTotal || '');
  }

  /* ------------------------------------------------------------------ logs */
  function renderLogsTab(content) {
    content.innerHTML = `
      <div class="log-toolbar">
        <div class="seg" id="dir-seg" aria-label="消息方向">
          <button data-dir="" class="active">全部</button>
          <button data-dir="in">接收</button>
          <button data-dir="out">发送</button>
        </div>
        <input class="input search" id="log-text" placeholder="搜索 SxFy、中文含义或报文内容" autocomplete="off">
        <input class="input mono" id="log-sf" placeholder="SxFy" aria-label="按消息编号筛选" autocomplete="off">
        <span class="spacer"></span>
        <button class="icon-btn" id="export-logs" title="导出全部原始日志" aria-label="导出全部原始日志">${icon('download', 15)}</button>
        <button class="btn sm" id="clear-logs">${icon('trash', 13)}清屏</button>
      </div>
      <div class="log-options">
        <label class="filter-check"><input type="checkbox" id="show-control" ${showControl ? 'checked' : ''}>显示 HSMS 控制帧与心跳</label>
        <span>默认只显示业务报文，点击任意消息可展开原始 SML</span>
        <span class="spacer"></span>
        <label class="filter-check"><input type="checkbox" id="pause-logs" ${paused ? 'checked' : ''}>暂停接收</label>
        <label class="filter-check"><input type="checkbox" id="autoscroll" ${autoScroll ? 'checked' : ''}>自动滚动</label>
      </div>
      <div class="terminal-wrap">
        <div class="terminal" id="log-view" aria-label="SECS/GEM 消息记录"></div>
        <div class="terminal-foot">
          <span id="ws-status"><span class="dot idle"></span> 正在连接实时通道…</span>
          <span id="log-count">0 条</span>
          <span>业务 600 条 · 控制帧 100 条 · 导出包含已隐藏控制帧</span>
        </div>
      </div>`;

    content.querySelectorAll('#dir-seg button').forEach((btn) => {
      btn.onclick = () => {
        content.querySelectorAll('#dir-seg button').forEach((b) => b.classList.toggle('active', b === btn));
        paintLogRows();
      };
    });
    content.querySelector('#log-text').oninput = debounce(paintLogRows, 120);
    content.querySelector('#log-sf').oninput = debounce(paintLogRows, 150);
    content.querySelector('#show-control').onchange = (e) => {
      showControl = e.target.checked;
      paintLogRows();
      updateCounts();
    };
    content.querySelector('#log-view').onclick = (e) => {
      const toggle = e.target.closest('[data-log-key]');
      if (!toggle) return;
      const key = toggle.dataset.logKey;
      if (expandedLogs.has(key)) expandedLogs.delete(key);
      else expandedLogs.add(key);
      paintLogRows(true);
    };
    content.querySelector('#pause-logs').onchange = (e) => {
      paused = e.target.checked;
      const status = content.querySelector('#ws-status');
      if (paused) status.innerHTML = '<span class="dot warn"></span> 实时流已暂停';
      else { paintLogRows(); setWsStatus(); }
    };
    content.querySelector('#autoscroll').onchange = (e) => { autoScroll = e.target.checked; };
    content.querySelector('#clear-logs').onclick = () => {
      logs = [];
      logKeys = new Set();
      kindCounts = { data: 0, control: 0 };
      expandedLogs = new Set();
      unseen = 0;
      paintLogRows();
      updateCounts();
      toast('日志已清空');
    };
    content.querySelector('#export-logs').onclick = () => {
      if (!logs.length) { toast('暂无可导出的日志', 'warn'); return; }
      downloadText(`fastsim-${currentId}-${Date.now()}.jsonl`, logs.map((l) => JSON.stringify(l)).join('\n'));
    };
    paintLogRows();
    setWsStatus();
  }

  function paintLogRows(preserveScroll = false) {
    const el = view.querySelector('#log-view');
    const previousTop = el?.scrollTop || 0;
    if (!el || tab !== 'logs') return;
    const rows = filteredLogs();
    el.innerHTML = rows.length
      ? rows.map(logRow).join('')
      : `<div class="log-empty">${icon('terminal', 26)}<b>${logs.length ? '当前筛选条件下没有消息' : '等待第一条业务报文'}</b><p>${logs.length && !showControl ? '控制帧默认已隐藏，可勾选上方“显示 HSMS 控制帧与心跳”。' : '发送 S1F1 或触发一个 GEM 事件后，消息会显示在这里。'}</p></div>`;
    const count = view.querySelector('#log-count');
    if (count) {
      count.textContent = rows.length === logs.length
        ? `${rows.length} 条`
        : `显示 ${rows.length} 条 / 共 ${logs.length} 条（含 ${kindCounts.control} 条控制帧）`;
    }
    hydrateIcons(el);
    el.scrollTop = preserveScroll ? previousTop : autoScroll ? el.scrollHeight : previousTop;
    setWsStatus();
  }

  function filteredLogs() {
    const dirEl = view.querySelector('#dir-seg button.active');
    const dir = dirEl ? dirEl.dataset.dir : '';
    const sf = (view.querySelector('#log-sf')?.value || '').trim().toUpperCase();
    const text = (view.querySelector('#log-text')?.value || '').trim().toLowerCase();
    return logs.filter((l) => {
      if (!showControl && l.kind === 'control') return false;
      if (dir && l.dir !== dir) return false;
      if (sf && !(l.sf || '').toUpperCase().startsWith(sf)) return false;
      if (text) {
        const hay = `${l.sml || ''} ${l.desc || ''} ${l.sf || ''} ${messageMeaning(l.sf)}`.toLowerCase();
        if (!hay.includes(text)) return false;
      }
      return true;
    });
  }

  function logRow(l) {
    const dir = l.dir === 'in' ? 'in' : l.dir === 'out' ? 'out' : 'ctrl';
    const key = logEntryKey(l);
    const expanded = expandedLogs.has(key);
    const control = l.kind === 'control';
    const label = control ? (l.desc || 'Control') : (l.sf || '—');
    const meaning = control ? 'HSMS 控制帧' : messageMeaning(l.sf);
    const preview = String(l.sml || '').replace(/\s+/g, ' ').trim();
    const raw = control ? (l.desc || '') : `${l.sf || ''}${l.w ? ' W' : ''}${l.sml ? `\n${l.sml}` : ''}`;
    return `<article class="log-row ${dir} ${control ? 'control' : 'data'} ${expanded ? 'expanded' : ''}" data-kind="${control ? 'control' : 'data'}">
      <button class="log-toggle" data-log-key="${esc(key)}" aria-expanded="${expanded}" title="${expanded ? '收起原始报文' : '展开原始报文'}">
        <time class="log-time">${fmtClock(l.ts, true)}</time>
        <span class="log-dir">${dir === 'in' ? '↓ 接收' : dir === 'out' ? '↑ 发送' : '· 系统'}</span>
        <span class="log-content">
          <span class="log-title"><b>${esc(label)}</b>${l.w ? '<span class="wflag">W</span>' : ''}<span>${esc(meaning)}</span></span>
          ${preview ? `<span class="log-preview">${esc(preview)}</span>` : ''}
        </span>
        <span class="log-chevron" aria-hidden="true">${expanded ? '−' : '+'}</span>
      </button>
      ${expanded ? `<div class="log-detail"><div class="log-detail-head">原始 ${control ? '控制帧' : 'SML'} <span>SystemBytes ${esc(l.system_bytes ?? '—')}</span></div><pre class="sml">${control ? esc(raw) : smlHighlight(raw)}</pre></div>` : ''}
    </article>`;
  }

  function setWsStatus() {
    if (paused) return;
    const el = view.querySelector('#ws-status');
    if (!el) return;
    const map = {
      open: ['ok pulse', '实时通道已连接'],
      connecting: ['warn', '正在连接实时通道…'],
      closed: ['bad', '实时通道已断开，重连中'],
    };
    const [tone, text] = map[wsState] || map.connecting;
    el.innerHTML = `<span class="dot ${tone}"></span> ${text}`;
  }

  function addLogLocal(entry, fromLive = false) {
    const key = logEntryKey(entry);
    if (logKeys.has(key)) return false;
    logKeys.add(key);
    const kind = entry.kind === 'control' ? 'control' : 'data';
    const limit = kind === 'control' ? 100 : 600;
    if (kindCounts[kind] >= limit) {
      const index = logs.findIndex((item) => (item.kind === 'control' ? 'control' : 'data') === kind);
      if (index >= 0) {
        const [dropped] = logs.splice(index, 1);
        logKeys.delete(logEntryKey(dropped));
        kindCounts[kind] -= 1;
      }
    }
    logs.push(entry);
    kindCounts[kind] += 1;
    if (fromLive) {
      if (tab === 'logs' && !paused && passesCurrentFilter(entry)) {
        const el = view.querySelector('#log-view');
        if (el) {
          if (el.querySelector('.log-empty')) el.innerHTML = '';
          el.insertAdjacentHTML('beforeend', logRow(entry));
          while (el.children.length > 700) el.firstElementChild.remove();
          if (autoScroll) el.scrollTop = el.scrollHeight;
          const count = view.querySelector('#log-count');
          if (count) count.textContent = `${filteredLogs().length} 条`;
        }
      } else if (tab !== 'logs' && entry.kind !== 'control') {
        unseen += 1;
      }
      updateCounts();
      if (tab === 'messages' || tab === 'gem') patchGuide();
    }
    return true;
  }

  function passesCurrentFilter(entry) {
    const dirEl = view.querySelector('#dir-seg button.active');
    const dir = dirEl ? dirEl.dataset.dir : '';
    if (!showControl && entry.kind === 'control') return false;
    if (dir && entry.dir !== dir) return false;
    const sf = (view.querySelector('#log-sf')?.value || '').trim().toUpperCase();
    if (sf && !(entry.sf || '').toUpperCase().startsWith(sf)) return false;
    const text = (view.querySelector('#log-text')?.value || '').trim().toLowerCase();
    if (text && !`${entry.sml || ''} ${entry.desc || ''} ${messageMeaning(entry.sf)}`.toLowerCase().includes(text)) return false;
    return true;
  }

  /* -------------------------------------------------------------- messages */
  function libForRole() {
    const role = detail?.role === 'host' ? 'host' : 'equipment';
    return MSG_LIB.map((m, i) => ({ ...m, i })).filter((m) => m.roles.includes(role));
  }

  function renderMessagesTab(content) {
    const lib = libForRole();
    const groups = [...new Set(lib.map((m) => m.group))];
    const isHost = detail.role === 'host';
    content.innerHTML = `
      <div class="composer-layout">
        <aside class="panel msg-lib">
          <div class="panel-head">
            <span class="panel-title">${icon('book', 15)}${isHost ? '标准消息库' : '设备上报消息'}</span>
            <span class="section-sub">${lib.length}</span>
          </div>
          <div style="padding:8px 10px;border-bottom:1px solid var(--line)">
            <input class="input search" id="lib-search" placeholder="搜索 SxFy 或名称…" autocomplete="off" style="height:30px;min-height:30px;font-size:12px">
          </div>
          <div class="panel-body" id="lib-body">
            ${groups.map((g) => `<div data-group="${esc(g)}">
              <div class="msg-group-label">${esc(g)}</div>
              ${lib.filter((m) => m.group === g).map((m) => `
                <button class="msg-item" data-lib="${m.i}">
                  <span class="sf">${esc(m.code.replace(' W', ''))}</span>
                  <span class="desc">${esc(m.desc)}</span>
                </button>`).join('')}
            </div>`).join('')}
          </div>
        </aside>

        <section class="panel">
          <div class="panel-head">
            <span class="panel-title">${icon('send', 15)}SML 报文编辑器</span>
            <span class="section-sub">Ctrl / Cmd + Enter 发送</span>
          </div>
          <div class="panel-body composer">
            ${isHost
              ? '<div class="composer-guide"><span><b>1</b>从左侧选择消息模板</span><span><b>2</b>用表单填写参数（自动生成 SML）</span><span><b>3</b>发送后在下方查看解读</span></div>'
              : `<div class="state-note">${icon('info')}<span>设备端通常被动应答主机请求。触发报警 / 事件建议用“GEM 操作”（会同步更新设备状态）；此处可直接发送原始 SML。</span></div>`}
            <div id="msg-form"></div>
            <div class="editor-shell">
              <textarea class="textarea" id="sml-input" spellcheck="false" aria-label="SML 输入">${esc(composerText)}</textarea>
            </div>
            <div class="editor-bar">
              <button class="btn primary" id="btn-send">${icon('send', 14)}发送消息</button>
              <span class="hint">W 表示等待应答；快捷键 Ctrl / Cmd + Enter</span>
              <span class="spacer" style="flex:1"></span>
              <button class="btn sm ghost" id="btn-format">整理缩进</button>
              <button class="btn sm ghost" id="btn-clear-sml">清空</button>
            </div>
            <div id="send-result">${lastResult ? resultCard(lastResult) : '<div class="result-empty">发送结果与应答解读会显示在这里。</div>'}</div>
          </div>
        </section>
      </div>`;

    content.querySelector('#lib-search').oninput = (e) => {
      const q = e.target.value.trim().toLowerCase();
      content.querySelectorAll('#lib-body [data-group]').forEach((group) => {
        let visible = 0;
        group.querySelectorAll('.msg-item').forEach((item) => {
          const text = item.textContent.toLowerCase();
          const show = !q || text.includes(q);
          item.style.display = show ? '' : 'none';
          if (show) visible += 1;
        });
        group.style.display = visible ? '' : 'none';
      });
    };
    content.querySelectorAll('[data-lib]').forEach((btn) => {
      btn.onclick = () => {
        const msg = MSG_LIB[Number(btn.dataset.lib)];
        const input = content.querySelector('#sml-input');
        input.value = msg.body ? `${msg.code}\n${msg.body}` : msg.code;
        composerText = input.value;
        activeForm = msg.form && profile ? msg.form : null;
        renderForm(content);
        input.focus();
      };
    });
    const input = content.querySelector('#sml-input');
    input.oninput = () => {
      composerText = input.value;
      if (activeForm) { activeForm = null; renderForm(content); }
    };
    input.onkeydown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        send();
      }
    };
    content.querySelector('#btn-send').onclick = send;
    content.querySelector('#btn-clear-sml').onclick = () => { input.value = ''; composerText = ''; activeForm = null; renderForm(content); input.focus(); };
    content.querySelector('#btn-format').onclick = () => {
      input.value = formatSml(input.value);
      composerText = input.value;
    };
    renderForm(content);

    async function send() {
      const text = input.value.trim();
      if (!text) { toast('请输入 SML 报文', 'warn'); return; }
      const btn = content.querySelector('#btn-send');
      btn.disabled = true;
      const started = performance.now();
      try {
        const res = await api.send(currentId, text);
        lastResult = {
          ok: true,
          sf: res.sf,
          reply: res.reply,
          sentText: text,
          rtt: Math.round(performance.now() - started),
          at: Date.now() / 1000,
        };
        content.querySelector('#send-result').innerHTML = resultCard(lastResult);
        toast(`已发送 ${res.sf}${res.reply ? ` · 应答 ${res.reply.sf}` : ''}`);
        patchGuide();
      } catch (e) {
        lastResult = { ok: false, sf: text.split('\n')[0], error: e.message, errorObj: e, at: Date.now() / 1000 };
        content.querySelector('#send-result').innerHTML = resultCard(lastResult);
        toastError(e);
      } finally {
        btn.disabled = false;
      }
    }
  }

  /* ---- parameter forms: fill fields, SML is generated automatically ---- */
  function varDefs(group) {
    if (!profile) return {};
    return group === 'SV' ? (profile.status_variables || {})
      : group === 'DV' ? (profile.data_variables || {})
        : (profile.equipment_constants || {});
  }

  function varName(id) {
    for (const g of ['SV', 'DV', 'EC']) {
      const d = varDefs(g)[id];
      if (d) return d.name || '';
    }
    return '';
  }

  function renderForm(content) {
    const slot = content.querySelector('#msg-form');
    if (!slot) return;
    if (!activeForm || !profile) { slot.innerHTML = ''; return; }
    slot.innerHTML = `<div class="msg-form"><div class="mf-head">${icon('sliders', 13)} 参数表单 <span class="hint">修改后自动生成 SML；直接编辑下方文本将关闭表单</span></div>${formBody(activeForm)}</div>`;
    bindForm(content);
    syncFormToEditor(content);
  }

  function formBody(type) {
    const sv = varDefs('SV');
    const dv = varDefs('DV');
    const ec = varDefs('EC');
    if (type === 'svquery' || type === 'ecquery') {
      const defs = type === 'svquery' ? { ...sv, ...dv } : ec;
      const ids = Object.keys(defs);
      const defaultId = type === 'svquery' && defs['1002'] ? '1002' : ids[0];
      return `<div class="mf-chips">${ids.map((id) => `<label class="chip-toggle"><input type="checkbox" data-mf-id="${esc(id)}" ${id === defaultId ? 'checked' : ''}><span>${esc(id)} ${esc(defs[id].name || '')}</span></label>`).join('') || '<span class="hint">Profile 未定义变量</span>'}</div>`;
    }
    if (type === 'ecwrite') {
      const ids = Object.keys(ec);
      const first = ids[0];
      const d = ec[first] || {};
      return `<div class="mf-row"><label>常量</label><select class="input" data-mf-ec>${ids.map((id) => `<option value="${esc(id)}">${esc(id)} ${esc(ec[id].name || '')}</option>`).join('')}</select></div>
        <div class="mf-row"><label>新值</label><input class="input mono" data-mf-value value="${esc(d.default ?? '')}"></div>`;
    }
    if (type === 'rcmd') {
      const cmds = profile.remote_commands || {};
      const names = Object.keys(cmds);
      return `<div class="mf-row"><label>命令</label><select class="input" data-mf-rcmd>${names.map((c) => `<option value="${esc(c)}">${esc(c)}${cmds[c].description ? ` · ${esc(cmds[c].description)}` : ''}</option>`).join('') || '<option>（Profile 未定义命令）</option>'}</select></div><div data-mf-params></div>`;
    }
    if (type === 'alarmenable') {
      const alarms = profile.alarms || {};
      const ids = Object.keys(alarms);
      return `<div class="mf-row"><label>报警</label><select class="input" data-mf-alid>${ids.map((id) => `<option value="${esc(id)}">${esc(id)} ${esc(alarms[id].name || '')}</option>`).join('')}</select></div>
        <div class="mf-row"><label>操作</label><select class="input" data-mf-enable><option value="1">使能（允许上报）</option><option value="0">禁用</option></select></div>`;
    }
    if (type === 'ceidrequest') {
      const events = profile.collection_events || {};
      const ids = Object.keys(events);
      return `<div class="mf-row"><label>事件</label><select class="input" data-mf-ceid>${ids.map((id) => `<option value="${esc(id)}">${esc(id)} ${esc(events[id].name || '')}</option>`).join('')}</select></div>`;
    }
    return '';
  }

  function bindForm(content) {
    const slot = content.querySelector('#msg-form');
    if (!slot) return;
    slot.querySelectorAll('input, select').forEach((el) => {
      el.oninput = () => syncFormToEditor(content);
      el.onchange = () => {
        if (el.hasAttribute('data-mf-rcmd')) renderRcmdParams(content);
        syncFormToEditor(content);
      };
    });
    if (activeForm === 'rcmd') renderRcmdParams(content);
  }

  function renderRcmdParams(content) {
    const slot = content.querySelector('[data-mf-params]');
    const sel = content.querySelector('[data-mf-rcmd]');
    if (!slot || !sel) return;
    const def = (profile.remote_commands || {})[sel.value] || {};
    const params = Object.entries(def.params || {});
    slot.innerHTML = params.length
      ? params.map(([name, p]) => `<div class="mf-row"><label>${esc(name)}${p.required ? ' *' : ''}</label><input class="input mono" data-mf-param="${esc(name)}" value="${name === 'RECIPE' ? 'R-1' : ''}" placeholder="${esc(p.type || 'A')}"></div>`).join('')
      : '<div class="hint" style="padding:4px 0">该命令无参数</div>';
    slot.querySelectorAll('input').forEach((el) => { el.oninput = () => syncFormToEditor(content); });
  }

  function syncFormToEditor(content) {
    const input = content.querySelector('#sml-input');
    if (!input || !activeForm) return;
    const sml = buildFormSml(content, activeForm);
    if (sml != null) {
      input.value = sml;
      composerText = sml;
    }
  }

  function buildFormSml(content, type) {
    const q = (sel) => content.querySelector(sel);
    if (type === 'svquery' || type === 'ecquery') {
      const ids = [...content.querySelectorAll('[data-mf-id]:checked')].map((el) => el.dataset.mfId);
      const code = type === 'svquery' ? 'S1F3 W' : 'S2F13 W';
      const body = ids.length ? `<L [${ids.length}]\n${ids.map((id) => `  <U4 ${id}>`).join('\n')}\n>` : '<L [0]>';
      return `${code}\n${body}`;
    }
    if (type === 'ecwrite') {
      const id = q('[data-mf-ec]')?.value;
      const val = q('[data-mf-value]')?.value ?? '';
      if (!id) return null;
      const t = (varDefs('EC')[id] || {}).type || 'A';
      const encoded = /^(A|J)$/.test(t) ? `<A "${val}">` : `<${t} ${val || 0}>`;
      return `S2F15 W\n<L [1]\n  <L [2]\n    <U4 ${id}>\n    ${encoded}\n  >\n>`;
    }
    if (type === 'rcmd') {
      const rcmd = q('[data-mf-rcmd]')?.value;
      if (!rcmd) return null;
      const params = [...content.querySelectorAll('[data-mf-param]')].map((el) => [el.dataset.mfParam, el.value]);
      const pairs = params.map(([n, v]) => `    <L [2]\n      <A "${n}">\n      <A "${v}">\n    >`).join('\n');
      const paramList = params.length ? `<L [${params.length}]\n${pairs}\n  >` : '<L [0]>';
      return `S2F41 W\n<L [2]\n  <A "${rcmd}">\n  ${paramList}\n>`;
    }
    if (type === 'alarmenable') {
      const alid = q('[data-mf-alid]')?.value;
      const enable = q('[data-mf-enable]')?.value === '1';
      if (!alid) return null;
      return `S5F3 W\n<L [2]\n  <B ${enable ? '0x80' : '0x00'}>\n  <U4 ${alid}>\n>`;
    }
    if (type === 'ceidrequest') {
      const ceid = q('[data-mf-ceid]')?.value;
      if (!ceid) return null;
      return `S6F15 W\n<L [2]\n  <U4 0>\n  <U4 ${ceid}>\n>`;
    }
    return null;
  }

  function resultCard(r) {
    if (!r) return '';
    if (!r.ok) {
      const { message, hint } = explainError(r.errorObj || { message: r.error });
      return `<div class="result-card err">
        <div class="result-head">${icon('alert', 14)}<b>发送失败</b><span class="result-meta">${fmtClock(r.at, true)}</span></div>
        <div class="result-explain bad">${esc(message)}</div>
        ${hint ? `<div class="result-hint">${esc(hint)}</div>` : ''}
      </div>`;
    }
    const reply = r.reply;
    const ex = reply ? explainReply(r.sf, reply, r.sentText) : null;
    const tone = ex ? (ex.ok ? 'ok' : 'warn') : 'ok';
    return `<div class="result-card ${tone}">
      <div class="result-head">${icon('check', 14)}<b>${esc(r.sf)} 已发送</b>
        <span class="pill ${ex ? (ex.ok ? 'ok' : 'warn') : 'idle'}" style="height:20px">${reply ? `应答 ${esc(reply.sf)}` : '无 W 位'}</span>
        <span class="result-meta">${r.rtt} ms · ${fmtClock(r.at, true)}</span>
      </div>
      ${ex ? `<div class="result-explain ${ex.ok ? 'ok' : 'warn'}">${esc(ex.text)}</div>` : ''}
      ${reply?.sml
        ? `<details class="raw-sml"><summary>查看原始 SML</summary><div class="result-body sml">${smlHighlight(reply.sml)}</div></details>`
        : `<div class="result-empty">${reply ? '应答无消息体' : '该报文未设置 W 位，不等待应答。'}</div>`}
    </div>`;
  }

  function explainReply(sentSf, reply, sentText) {
    const sf = reply.sf;
    const d = reply.data;
    const arr = Array.isArray(d) ? d : (d == null ? [] : [d]);
    const sentIds = [...String(sentText || '').matchAll(/<U4\s+(\d+)>/g)].map((m) => m[1]);
    switch (sf) {
      case 'S1F2': return { ok: true, text: `设备在线 · 型号 ${fmtVal(arr[0])} · 软件版本 ${fmtVal(arr[1])}` };
      case 'S1F14': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '通信建立成功（COMMACK=0）' : `设备拒绝建立通信（COMMACK=${c}）` }; }
      case 'S1F16': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '设备已接受离线请求（ONLACK=0）' : `离线请求被拒绝（ONLACK=${c}）` }; }
      case 'S1F18': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '设备已接受在线请求（ONLACK=0）' : `在线请求被拒绝（ONLACK=${c}）` }; }
      case 'S1F4':
      case 'S2F14': {
        const parts = arr.map((v, i) => {
          const id = sentIds[i];
          const name = varName(id);
          return `${name || id || `值${i + 1}`} = ${fmtVal(v)}`;
        });
        return { ok: true, text: parts.length ? parts.join(' · ') : '（空应答）' };
      }
      case 'S2F16': {
        const eacs = arr.map(toByte);
        const ok = eacs.length > 0 && eacs.every((v) => v === 0);
        return { ok, text: ok ? '设备常量全部写入成功（EAC=0）' : `部分常量写入被拒绝：${eacs.map((v, i) => `第${i + 1}项 EAC=${v}`).join('，')}` };
      }
      case 'S2F32': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '时钟设置成功（ACKC2=0）' : `时钟设置被拒绝（ACKC2=${c}）` }; }
      case 'S2F34': { const c = toByte(arr[1]); return { ok: c === 0, text: c === 0 ? '报告定义成功（LRACK=0）' : `报告定义被拒绝（LRACK=${c}）` }; }
      case 'S2F36': { const c = toByte(arr[1]); return { ok: c === 0, text: c === 0 ? '事件与报告链接成功' : `链接被拒绝（ACK=${c}）` }; }
      case 'S2F38': { const c = toByte(arr[1]); return { ok: c === 0, text: c === 0 ? '事件使能设置成功（DRACK=0）' : `事件使能被拒绝（DRACK=${c}）` }; }
      case 'S2F42': {
        const hcack = toByte(arr[0]);
        const paramAcks = (arr[1] || []).map((p) => `${p[0]}: ACKC=${toByte(p[1])}`);
        return { ok: hcack === 0, text: `HCACK=${hcack} · ${HCACK_TEXT[hcack] || '未知应答码'}${paramAcks.length ? ` · ${paramAcks.join('，')}` : ''}` };
      }
      case 'S5F4': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '报警使能设置成功（ACKC5=0）' : `设置被拒绝（ACKC5=${c}）` }; }
      case 'S5F6': return { ok: true, text: `当前已设置报警 ${arr.length} 个` };
      case 'S5F8': return { ok: true, text: `当前已使能报警 ${arr.length} 个` };
      case 'S6F16': return { ok: true, text: '收到请求的事件报告' };
      case 'S7F2': { const c = toByte(arr[0]); return { ok: c === 0, text: c === 0 ? '配方已存在（PGRPN=0）' : '配方不存在（PGRPN=1）' }; }
      case 'S7F6': return { ok: true, text: `收到配方内容（约 ${Math.ceil(String(arr[1] || '').length / 2)} 字节）` };
      case 'S7F20': return { ok: true, text: `设备配方列表：${arr.length ? arr.join('、') : '（空）'}` };
      case 'S10F4': return { ok: true, text: '终端消息已确认' };
      default:
        if (/^S9F/.test(sf)) return { ok: false, text: `设备返回错误报文 ${sf}：${S9_TEXT[sf] || '协议错误'}` };
        return null;
    }
  }

  function formatSml(text) {
    const lines = text.split('\n');
    let depth = 0;
    return lines.map((line) => {
      const trimmed = line.trim();
      if (!trimmed) return '';
      if (trimmed.startsWith('>')) depth = Math.max(0, depth - 1);
      const out = trimmed.startsWith('<A ') || trimmed.startsWith('<L ') || trimmed.startsWith('<U') ||
        trimmed.startsWith('<B ') || trimmed.startsWith('<BOOLEAN') || trimmed.startsWith('<F')
        ? `${'  '.repeat(depth)}${trimmed}` : trimmed;
      const opens = (trimmed.match(/</g) || []).length;
      const closes = (trimmed.match(/>/g) || []).length;
      const net = opens - closes;
      const endsOpen = net > 0 && !trimmed.endsWith('>');
      if (endsOpen) depth += 1;
      return out;
    }).join('\n');
  }

  /* ------------------------------------------------------------------- GEM */
  function renderGemTab(content) {
    if (!profile) {
      content.innerHTML = '<div class="empty"><p>Profile 尚未加载完成。</p></div>';
      return;
    }
    if (detail.role === 'host') renderGemHost(content);
    else renderGemEquipment(content);
  }

  function pushFeed(entry) {
    effectFeed.unshift({ ts: Date.now() / 1000, ...entry });
    if (effectFeed.length > 30) effectFeed.length = 30;
    if (tab === 'gem') paintEffectFeed();
  }

  function paintEffectFeed() {
    const el = view.querySelector('#effect-feed');
    if (!el) return;
    el.innerHTML = effectFeed.length
      ? effectFeed.map((f) => `<div class="feed-line ${f.tone || ''}"><time>${fmtClock(f.ts, true)}</time><span>${esc(f.text)}</span></div>`).join('')
      : '<div class="feed-empty">暂无动态。发送远程命令、触发报警或事件后会显示在这里。</div>';
  }

  function feedPanel() {
    return `<section class="panel span-2">
      <div class="panel-head"><span class="panel-title">${icon('activity', 15)}实时动态</span><span class="section-sub">命令 / 报警 / 事件</span></div>
      <div class="effect-feed" id="effect-feed"></div>
    </section>`;
  }

  /* ---- equipment: simulate the machine (alarms, events, variables) ---- */
  function renderGemEquipment(content) {
    const alarms = profile.alarms || {};
    const events = profile.collection_events || {};
    const active = new Set((detail.alarms_active || []).map(String));
    const state = detail.states || {};

    content.innerHTML = `
      <div class="gem-grid">
        <section class="panel">
          <div class="panel-head">
            <span class="panel-title">${icon('alert', 15)}报警 ALID <span class="count">${Object.keys(alarms).length}</span></span>
            <span class="section-sub" id="alarm-active-count">${active.size} 个活动</span>
          </div>
          <div class="list list-scroll">
            ${Object.entries(alarms).map(([alid, a]) => `
              <div class="list-row" data-alarm-row="${esc(alid)}">
                <span class="alarm-led ${active.has(String(alid)) ? 'on' : ''}"></span>
                <span class="id">${esc(alid)}</span>
                <span class="name" title="${esc(a.text || a.name)}">${esc(a.name)}</span>
                <span class="badge neutral">CAT ${esc(a.category ?? 0)}</span>
                <span class="actions">
                  <button class="btn sm" data-alarm-set="${esc(alid)}" ${active.has(String(alid)) ? 'disabled' : ''}>触发</button>
                  <button class="btn sm" data-alarm-clear="${esc(alid)}" ${active.has(String(alid)) ? '' : 'disabled'}>清除</button>
                </span>
              </div>`).join('') || '<div class="feed-empty">Profile 未定义报警。</div>'}
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <span class="panel-title">${icon('activity', 15)}采集事件 CEID <span class="count">${Object.keys(events).length}</span></span>
          </div>
          <div class="list list-scroll">
            ${Object.entries(events).map(([ceid, ev]) => `
              <div class="list-row">
                <span class="id">${esc(ceid)}</span>
                <span class="name">${esc(ev.name || '—')}</span>
                <span class="section-sub">RPT ${(ev.reports || []).join(', ') || '—'}</span>
                <span class="actions"><button class="btn sm" data-event="${esc(ceid)}">触发上报</button></span>
              </div>`).join('') || '<div class="feed-empty">Profile 未定义事件。</div>'}
          </div>
        </section>

        <section class="panel span-2">
          <div class="panel-head">
            <span class="panel-title">${icon('sliders', 15)}变量字典 SVID / DV / EC</span>
            <input class="input search" id="var-search" placeholder="筛选变量…" style="height:28px;min-height:28px;width:180px;font-size:11.5px" autocomplete="off">
          </div>
          <div class="table-scroll">
            <table class="table" id="var-table">
              <thead><tr><th>ID</th><th>类型</th><th>名称</th><th>当前值</th><th></th></tr></thead>
              <tbody>${variableRows()}</tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('cpu', 15)}控制状态</span></div>
          <div class="panel-body control-block">
            <div class="control-current">
              <span class="lbl">当前控制状态</span>
              <b>${esc(stateLabel('control', state.control))}</b>
            </div>
            <div class="control-grid">
              ${CONTROL_STATES.map((s) => `<button class="btn sm ${state.control === s.value ? 'primary' : ''}" data-control="${s.value}" ${state.control === s.value ? 'disabled' : ''}>${s.label}</button>`).join('')}
            </div>
          </div>
        </section>

        ${feedPanel()}
      </div>`;

    hydrateIcons(content);
    paintEffectFeed();

    content.querySelectorAll('[data-alarm-set]').forEach((btn) => {
      btn.onclick = () => runAlarm(btn.dataset.alarmSet, true);
    });
    content.querySelectorAll('[data-alarm-clear]').forEach((btn) => {
      btn.onclick = () => runAlarm(btn.dataset.alarmClear, false);
    });
    content.querySelectorAll('[data-event]').forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const res = await api.triggerEvent(currentId, btn.dataset.event, {});
          if (res.sent) {
            toast(`事件 ${btn.dataset.event} 已触发上报`);
            pushFeed({ kind: 'event', tone: 'ok', text: `触发采集事件 ${btn.dataset.event} ${eventName(btn.dataset.event)}` });
          } else {
            toast(`事件 ${btn.dataset.event} 未上报：需先由主机订阅并使能（或链路未建立）`, 'warn');
          }
        } catch (e) { toastError(e); }
        finally { btn.disabled = false; }
      };
    });
    content.querySelectorAll('[data-control]').forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const states = await api.controlState(currentId, btn.dataset.control);
          detail.states = states;
          patchHeader();
          renderGemTab(content);
          toast(`控制状态已切换为 ${stateLabel('control', states.control)}`);
        } catch (e) { toastError(e); btn.disabled = false; }
      };
    });
    content.querySelectorAll('[data-var-save]').forEach((btn) => {
      btn.onclick = () => saveVariable(btn, content);
    });
    content.querySelector('#var-search').oninput = (e) => {
      const q = e.target.value.trim().toLowerCase();
      content.querySelectorAll('#var-table tbody tr').forEach((tr) => {
        tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    };

    async function runAlarm(alid, on) {
      try {
        await api.setAlarm(currentId, alid, on);
        const set = new Set((detail.alarms_active || []).map(String));
        if (on) set.add(String(alid)); else set.delete(String(alid));
        detail.alarms_active = [...set];
        toast(`报警 ${alid} ${on ? '已触发' : '已清除'}`, on ? 'warn' : 'ok');
        pushFeed({ kind: 'alarm', tone: on ? 'warn' : 'ok', text: `报警 ${alid} ${alarmName(alid)} ${on ? '触发' : '清除'}` });
        patchAlarmRow(alid);
      } catch (e) { toastError(e); }
    }
  }

  function alarmName(alid) {
    return (profile?.alarms || {})[alid]?.name || '';
  }

  function eventName(ceid) {
    return (profile?.collection_events || {})[ceid]?.name || '';
  }

  function patchAlarmRow(alid) {
    const content = view.querySelector('#tab-content');
    if (!content || tab !== 'gem') return;
    const active = new Set((detail.alarms_active || []).map(String));
    const row = content.querySelector(`[data-alarm-row="${CSS.escape(String(alid))}"]`);
    if (row) {
      const on = active.has(String(alid));
      row.querySelector('.alarm-led')?.classList.toggle('on', on);
      const setBtn = row.querySelector('[data-alarm-set]');
      const clearBtn = row.querySelector('[data-alarm-clear]');
      if (setBtn) setBtn.disabled = on;
      if (clearBtn) clearBtn.disabled = !on;
    }
    const count = content.querySelector('#alarm-active-count');
    if (count) count.textContent = `${active.size} 个活动`;
  }

  /* ---- host: drive the equipment (commands, queries, subscriptions) ---- */
  function renderGemHost(content) {
    const commands = profile.remote_commands || {};
    const events = profile.collection_events || {};
    const alarms = profile.alarms || {};

    content.innerHTML = `
      <div class="gem-grid">
        <section class="panel span-2">
          <div class="panel-head"><span class="panel-title">${icon('send', 15)}远程命令 S2F41</span><span class="section-sub">发送后自动查询设备状态变化</span></div>
          <div class="panel-body" style="padding-top:6px">
            ${Object.entries(commands).map(([cmd, def]) => {
              const params = Object.entries(def.params || {});
              return `<div class="cmd-row" data-cmd-row="${esc(cmd)}">
                <div>
                  <div class="cmd">${esc(cmd)}</div>
                  <div class="cmd-desc">${esc(def.description || '')}</div>
                </div>
                <div class="cmd-params">
                  ${params.length ? params.map(([name, p]) => `<input class="input cmd-param" data-param="${esc(name)}" data-required="${p.required ? '1' : '0'}" placeholder="${esc(name)}${p.required ? ' *' : ''}" value="${name === 'RECIPE' ? 'R-1' : ''}">`).join('') : '<span class="hint">无参数</span>'}
                </div>
                <button class="btn sm primary" data-rcmd="${esc(cmd)}">发送</button>
              </div>`;
            }).join('') || '<div class="feed-empty">Profile 未定义远程命令。</div>'}
            <div id="cmd-effect"></div>
          </div>
        </section>

        <section class="panel span-2">
          <div class="panel-head">
            <span class="panel-title">${icon('sliders', 15)}设备状态</span>
            <button class="btn sm" id="query-state">${icon('refresh', 13)}刷新（S1F3）</button>
          </div>
          <div class="table-scroll">
            <table class="table" id="device-state-table">
              <thead><tr><th>ID</th><th>类型</th><th>名称</th><th>设备当前值</th></tr></thead>
              <tbody id="device-state-body"></tbody>
            </table>
          </div>
          <div class="panel-foot hint">通过 S1F3 向设备查询的真实值；发送远程命令后自动刷新并高亮变化。</div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('activity', 15)}事件订阅</span><button class="btn sm" id="subscribe-all">一键订阅全部</button></div>
          <div class="list list-scroll">
            ${Object.entries(events).map(([ceid, ev]) => `
              <div class="list-row">
                <span class="id">${esc(ceid)}</span>
                <span class="name">${esc(ev.name || '—')}</span>
                <span class="actions"><button class="btn sm" data-subscribe="${esc(ceid)}" ${subscribedEvents.has(String(ceid)) ? 'disabled' : ''}>${subscribedEvents.has(String(ceid)) ? '已订阅' : '订阅'}</button></span>
              </div>`).join('') || '<div class="feed-empty">Profile 未定义事件。</div>'}
          </div>
          <div class="panel-foot hint">订阅 = S2F33 定义报告 + S2F35 链接 + S2F37 使能，之后设备触发的事件会上报到本机。</div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('cpu', 15)}报警与上下线</span></div>
          <div class="panel-body control-block">
            <div class="control-grid">
              <button class="btn sm" id="enable-alarms">使能全部报警（S5F3）</button>
              <button class="btn sm" id="go-online">请求上线（S1F17）</button>
              <button class="btn sm" id="go-offline">请求离线（S1F15）</button>
            </div>
            <div class="hint">使能报警后，设备触发报警时才会向主机上报 S5F1。</div>
          </div>
        </section>

        ${feedPanel()}
      </div>`;

    hydrateIcons(content);
    paintEffectFeed();
    paintDeviceState();

    content.querySelector('#query-state').onclick = () => queryDeviceState(true);
    content.querySelectorAll('[data-rcmd]').forEach((btn) => {
      btn.onclick = () => runRemoteCommand(btn);
    });
    content.querySelectorAll('[data-subscribe]').forEach((btn) => {
      btn.onclick = () => subscribeEvent(btn.dataset.subscribe, btn);
    });
    content.querySelector('#subscribe-all').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      for (const ceid of Object.keys(events)) {
        if (!subscribedEvents.has(String(ceid))) await subscribeEvent(ceid, null);
      }
      btn.disabled = false;
      toast('已订阅全部事件');
    };
    content.querySelector('#enable-alarms').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        for (const alid of Object.keys(alarms)) {
          await api.send(currentId, `S5F3 W\n<L [2]\n  <B 0x80>\n  <U4 ${alid}>\n>`);
        }
        toast('已使能全部报警');
        pushFeed({ kind: 'alarm', tone: 'ok', text: '使能全部报警（S5F3）' });
      } catch (err) { toastError(err); }
      finally { btn.disabled = false; }
    };
    content.querySelector('#go-online').onclick = () => quickSend('S1F17 W', '请求上线');
    content.querySelector('#go-offline').onclick = () => quickSend('S1F15 W', '请求离线');
  }

  async function quickSend(sml, label) {
    try {
      const res = await api.send(currentId, sml);
      const ex = res.reply ? explainReply(sml.split(' ')[0], res.reply, sml) : null;
      toast(ex ? `${label}：${ex.text}` : `${label} 已发送`, ex && !ex.ok ? 'warn' : 'ok');
      pushFeed({ kind: 'cmd', tone: ex && !ex.ok ? 'warn' : 'ok', text: `${label} · ${ex ? ex.text : '已发送'}` });
      await patchStates(false);
    } catch (e) { toastError(e); }
  }

  async function subscribeEvent(ceid, btn) {
    const ev = (profile.collection_events || {})[ceid] || {};
    const rptid = (ev.reports || [])[0];
    const svids = rptid != null ? ((profile.reports || {})[rptid]?.variables || []) : [];
    if (rptid == null) {
      toast(`事件 ${ceid} 未关联报告，无法订阅`, 'warn');
      return;
    }
    if (btn) btn.disabled = true;
    try {
      await api.subscribe(currentId, ceid, rptid, svids);
      subscribedEvents.add(String(ceid));
      if (btn) btn.textContent = '已订阅';
      pushFeed({ kind: 'event', tone: 'ok', text: `订阅事件 ${ceid} ${eventName(ceid)}（报告 ${rptid}）` });
    } catch (e) {
      toastError(e);
      if (btn) btn.disabled = false;
    }
  }

  async function runRemoteCommand(btn) {
    const row = btn.closest('[data-cmd-row]');
    const rcmd = btn.dataset.rcmd;
    const params = {};
    let missing = '';
    row.querySelectorAll('[data-param]').forEach((inp) => {
      if (!inp.value && inp.dataset.required === '1' && !missing) missing = inp.dataset.param;
      if (inp.value !== '') params[inp.dataset.param] = inp.value;
    });
    if (missing) {
      toast(`命令 ${rcmd} 缺少必填参数 ${missing}`, 'warn');
      return;
    }
    btn.disabled = true;
    const before = deviceState ? { ...deviceState } : null;
    const started = performance.now();
    const cmdTs = Date.now() / 1000;
    try {
      const res = await api.remoteCommand(currentId, rcmd, params);
      // give the equipment a moment to apply behavior + emit events, then re-query
      await new Promise((r) => setTimeout(r, 350));
      await queryDeviceState(false);
      const changes = diffStates(before, deviceState);
      const events = effectFeed.filter((f) => f.kind === 'event' && f.ts >= cmdTs && /收到事件/.test(f.text));
      showCmdEffect({ rcmd, params, hcack: res.hcack, rtt: Math.round(performance.now() - started), changes, events });
      pushFeed({ kind: 'rcmd', tone: res.hcack === 0 ? 'ok' : 'warn', text: `发送远程命令 ${rcmd} · HCACK=${res.hcack}` });
      patchGuide();
    } catch (e) {
      toastError(e);
      showCmdEffect({ rcmd, params, error: e });
    } finally {
      btn.disabled = false;
    }
  }

  function diffStates(before, after) {
    if (!before || !after) return [];
    const out = [];
    for (const [id, val] of Object.entries(after)) {
      const old = before[id];
      if (String(old ?? '') !== String(val ?? '')) {
        out.push({ id, name: varName(id), from: old, to: val });
      }
    }
    return out;
  }

  function showCmdEffect({ rcmd, params, hcack, rtt, changes, events, error }) {
    const slot = view.querySelector('#cmd-effect');
    if (!slot) return;
    if (error) {
      const { message, hint } = explainError(error);
      slot.innerHTML = `<div class="effect-card bad"><div class="effect-head">${icon('alert', 14)}<b>${esc(rcmd)} 发送失败</b></div><div class="effect-line">${esc(message)}</div>${hint ? `<div class="effect-hint">${esc(hint)}</div>` : ''}</div>`;
      return;
    }
    const ok = hcack === 0;
    const paramText = Object.entries(params || {}).map(([k, v]) => `${k}=${v}`).join('，');
    slot.innerHTML = `<div class="effect-card ${ok ? 'ok' : 'warn'}">
      <div class="effect-head">${icon(ok ? 'check' : 'alert', 14)}<b>${esc(rcmd)}${paramText ? `（${esc(paramText)}）` : ''}</b>
        <span class="pill ${ok ? 'ok' : 'warn'}" style="height:20px">HCACK=${esc(hcack)} · ${esc(HCACK_TEXT[hcack] || '未知')}</span>
        <span class="result-meta">${rtt != null ? `${rtt} ms` : ''}</span></div>
      ${changes && changes.length
        ? `<div class="effect-line"><b>设备状态变化</b></div>${changes.map((c) => `<div class="effect-change"><span class="mono">${esc(c.id)}</span> ${esc(c.name || '')}：<span class="from">${esc(fmtVal(c.from))}</span> → <span class="to">${esc(fmtVal(c.to))}</span></div>`).join('')}`
        : '<div class="effect-hint">设备状态无变化（该命令可能未配置行为联动，或设备未连接）。</div>'}
      ${events && events.length ? `<div class="effect-line"><b>设备上报</b></div>${events.map((e) => `<div class="effect-change">${esc(e.text)}</div>`).join('')}` : ''}
    </div>`;
  }

  async function queryDeviceState(showToast) {
    if (!profile || detail?.role !== 'host') return;
    const ids = [...Object.keys(profile.status_variables || {}), ...Object.keys(profile.data_variables || {})];
    if (!ids.length) return;
    try {
      const vals = await api.querySv(currentId, ids.map(Number));
      deviceStatePrev = deviceState;
      deviceState = vals;
      if (tab === 'gem') paintDeviceState();
      if (showToast) toast('设备状态已更新（S1F3）');
    } catch (e) {
      if (showToast) toastError(e);
    }
  }

  function paintDeviceState() {
    const body = view.querySelector('#device-state-body');
    if (!body) return;
    if (!deviceState) {
      body.innerHTML = '<tr><td colspan="4" class="feed-empty">尚未查询。点击“刷新（S1F3）”获取设备当前值。</td></tr>';
      return;
    }
    const groups = [['SV', profile.status_variables || {}], ['DV', profile.data_variables || {}]];
    const rows = [];
    groups.forEach(([tag, defs]) => {
      Object.entries(defs).forEach(([id, def]) => {
        const val = deviceState[id];
        const prev = deviceStatePrev ? deviceStatePrev[id] : undefined;
        const changed = deviceStatePrev && String(prev ?? '') !== String(val ?? '');
        rows.push(`<tr class="${changed ? 'var-changed' : ''}">
          <td class="mono">${esc(id)}</td>
          <td><span class="var-group-tag">${tag}</span><span class="mono">${esc(def.type || 'A')}</span></td>
          <td class="vname">${esc(def.name || '')}${def.unit ? ` <span class="section-sub">${esc(def.unit)}</span>` : ''}</td>
          <td class="mono device-val">${esc(fmtVal(val))}</td>
        </tr>`);
      });
    });
    body.innerHTML = rows.join('') || '<tr><td colspan="4" class="feed-empty">Profile 未定义变量</td></tr>';
  }

  function variableRows() {
    if (!variables) return '<tr><td colspan="5" class="feed-empty">变量尚未加载</td></tr>';
    const groups = [
      ['SV', variables.status_variables],
      ['DV', variables.data_variables],
      ['EC', variables.equipment_constants],
    ];
    const rows = [];
    groups.forEach(([tag, map]) => {
      Object.entries(map || {}).forEach(([vid, item]) => {
        const def = item.def || {};
        const value = item.value ?? '';
        const type = def.type || 'A';
        let control;
        if (Array.isArray(def.enum) && def.enum.length) {
          control = `<select class="input var-input" data-var-input="${esc(vid)}">${def.enum.map((v) => `<option ${String(v) === String(value) ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>`;
        } else {
          const inputType = /^(U|I|F)\d/.test(type) ? 'number' : 'text';
          control = `<input class="input var-input" data-var-input="${esc(vid)}" type="${inputType}" value="${esc(value)}" ${inputType === 'number' ? 'step="any"' : ''}>`;
        }
        rows.push(`<tr data-var-row="${esc(vid)}">
          <td class="mono">${esc(vid)}</td>
          <td><span class="var-group-tag">${tag}</span><span class="mono">${esc(type)}</span></td>
          <td class="vname">${esc(def.name || '')}${def.unit ? ` <span class="section-sub">${esc(def.unit)}</span>` : ''}</td>
          <td>${control}</td>
          <td><button class="btn sm" data-var-save="${esc(vid)}" data-var-type="${esc(type)}">设值</button></td>
        </tr>`);
      });
    });
    return rows.join('') || '<tr><td colspan="5" class="feed-empty">Profile 未定义变量</td></tr>';
  }

  function applyVariableChanges(changes) {
    if (!variables || !changes) return;
    const groups = { SV: variables.status_variables, DV: variables.data_variables, EC: variables.equipment_constants };
    for (const [vid, ch] of Object.entries(changes)) {
      const map = groups[ch.group] || groups.SV;
      if (map && map[vid]) map[vid].value = ch.to;
    }
    if (tab === 'gem' && detail?.role === 'equipment') {
      for (const [vid, ch] of Object.entries(changes)) {
        const input = view.querySelector(`[data-var-input="${CSS.escape(vid)}"]`);
        if (input) {
          input.value = ch.to ?? '';
          const row = input.closest('tr');
          if (row) {
            row.classList.remove('var-changed');
            void row.offsetWidth; // restart animation
            row.classList.add('var-changed');
          }
        }
      }
    }
  }

  async function saveVariable(btn, content) {
    const vid = btn.dataset.varSave;
    const input = content.querySelector(`[data-var-input="${CSS.escape(vid)}"]`);
    if (!input) return;
    let value = input.value;
    const type = btn.dataset.varType || 'A';
    if (/^(U|I)\d/.test(type)) value = Number(value);
    if (/^F\d/.test(type)) value = parseFloat(value);
    btn.disabled = true;
    try {
      await api.setVariable(currentId, vid, value);
      toast(`${vid} = ${input.value}`);
    } catch (e) {
      toastError(e);
    } finally {
      btn.disabled = false;
    }
  }

  /* ------------------------------------------------------------ connection */
  function renderConnectionTab(content) {
    const conn = detail.connection || {};
    const t = conn.timeouts || {};
    const meta = detail.profile_meta || {};
    const rows = [
      ['Profile', detail.profile],
      ['角色', detail.role === 'host' ? '主机端 Host' : '设备端 Equipment'],
      ['模式', conn.mode],
      ['监听 / 连接', `${conn.host}:${conn.port}`],
      ['Device ID', conn.device_id],
      ['初始控制状态', stateLabel('control', conn.initial_control_state)],
      ['创建时间', fmtDateTime(detail.created_at)],
    ];
    const timeouts = [
      ['T3', t.t3, '应答超时'],
      ['T5', t.t5, '连接分离超时'],
      ['T6', t.t6, '控制事务超时'],
      ['T7', t.t7, '未选择超时'],
      ['T8', t.t8, '帧字符间隔'],
      ['Linktest', t.linktest, '保活探测间隔'],
    ];
    const max = Math.max(...timeouts.map(([, v]) => Number(v) || 0), 60);
    const issue = detail.issue && detail.issue.severity !== 'info' ? detail.issue : null;

    content.innerHTML = `
      <div class="gem-grid">
        ${issue ? `<section class="panel span-2"><div class="panel-body"><div class="session-guide ${issue.severity === 'error' ? 'bad' : 'warn'}" style="margin:0">${icon('alert', 16)}<div><b>${esc(issue.message)}</b><span>${esc(issue.hint || '')}</span></div></div></div></section>` : ''}
        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('link', 15)}HSMS 链路参数</span><span class="pill ${detail.states.hsms === 'SELECTED' ? 'ok' : 'idle'}"><span class="dot ${detail.states.hsms === 'SELECTED' ? 'ok' : 'idle'}"></span>${esc(stateLabel('hsms', detail.states.hsms))}</span></div>
          <table class="kv-table">${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')}</table>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('clock', 15)}超时参数</span><span class="section-sub">单位：秒</span></div>
          <div class="panel-body">
            ${timeouts.map(([k, v, desc]) => `
              <div class="timeout-row" title="${esc(desc)}">
                <span class="k">${esc(k)}</span>
                <span class="timeout-bar"><span style="width:${Math.min(100, (Number(v) / max) * 100)}%"></span></span>
                <span class="v">${esc(v)}s</span>
              </div>`).join('')}
            <div class="state-note" style="margin-top:12px">${icon('info')}<span>T3 为事务应答超时；T8 仅限制帧内字符间隔，长应答不会被误杀。</span></div>
          </div>
        </section>

        <section class="panel span-2">
          <div class="panel-head"><span class="panel-title">${icon('box', 15)}机台信息</span><span class="section-sub">来自 Profile</span></div>
          <div class="panel-body">
            <div class="gem-grid" style="grid-template-columns:repeat(3,minmax(0,1fr))">
              ${[['机台名称', meta.name], ['厂商', meta.vendor], ['型号', meta.model],
                 ['位置', meta.location], ['MDLN', meta.mdln], ['SOFTREV', meta.softrev]]
                .map(([k, v]) => `<div class="field"><span class="field-label">${esc(k)}</span><span style="font-size:13px">${esc(v || '—')}</span></div>`).join('')}
            </div>
          </div>
        </section>
      </div>`;
    hydrateIcons(content);
  }

  /* ---------------------------------------------------------------- record */
  function renderRecordTab(content) {
    content.innerHTML = `
      <div class="gem-grid">
        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('record', 15)}会话录制</span></div>
          <div class="panel-body" style="display:flex;flex-direction:column;gap:12px">
            <p class="hint">录制当前会话的全部收发帧为 JSONL，可用于回归回放与黄金文件比对。</p>
            <div class="page-actions">
              <button class="btn primary" id="rec-start">${icon('record', 14)}开始录制</button>
              <button class="btn" id="rec-stop">${icon('stop', 14)}停止录制</button>
            </div>
            <div class="result-card" id="rec-result" style="min-height:90px">
              <div class="result-head">${icon('info', 14)}<b>状态</b></div>
              <div class="result-body" id="rec-status">当前未录制。点击“开始录制”后，收发日志会实时写入文件。</div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><span class="panel-title">${icon('play', 15)}回放</span></div>
          <div class="panel-body" style="display:flex;flex-direction:column;gap:12px">
            <div class="field">
              <label for="rec-speed">回放倍速</label>
              <input class="input mono" id="rec-speed" type="number" min="0.1" max="20" step="0.1" value="1">
            </div>
            <button class="btn" id="rec-replay">${icon('playSmall', 14)}回放最近录制</button>
            <div class="result-card" id="replay-result" style="display:none"></div>
            <div class="state-note">${icon('info')}<span>回放会把录制的帧重新注入当前会话，适用于对端回归或演示。</span></div>
          </div>
        </section>
      </div>`;

    const result = content.querySelector('#rec-result');
    const status = content.querySelector('#rec-status');
    if (recording) {
      result.classList.add('ok');
      status.innerHTML = `录制文件：<b>${esc(recording.path)}</b><br>已写入 ${recording.frames ?? '…'} 帧`;
    }

    content.querySelector('#rec-start').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const res = await api.recordStart(currentId);
        recording = { path: res.recording, frames: 0 };
        result.classList.add('ok');
        status.innerHTML = `录制中：<b>${esc(res.recording)}</b>`;
        toast('开始录制');
      } catch (err) { toastError(err); }
      finally { btn.disabled = false; }
    };
    content.querySelector('#rec-stop').onclick = async (e) => {
      if (!recording) { toast('当前没有进行中的录制', 'warn'); return; }
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const res = await api.recordStop(currentId);
        recording = { path: res.recording, frames: res.frames };
        status.innerHTML = `录制完成：<b>${esc(res.recording)}</b><br>共 ${res.frames} 帧`;
        toast(`录制完成，共 ${res.frames} 帧`);
      } catch (err) { toastError(err); }
      finally { btn.disabled = false; }
    };
    content.querySelector('#rec-replay').onclick = async (e) => {
      if (!recording?.path) { toast('请先完成一次录制', 'warn'); return; }
      const btn = e.currentTarget;
      const speed = Number(content.querySelector('#rec-speed').value) || 1;
      btn.disabled = true;
      try {
        const res = await api.replay(currentId, recording.path, speed);
        const box = content.querySelector('#replay-result');
        box.style.display = '';
        box.className = 'result-card ok';
        box.innerHTML = `<div class="result-head">${icon('check', 14)}<b>回放完成</b><span class="result-meta">${speed}x</span></div>
          <div class="result-body">${esc(res.replayed)} / ${esc(res.total)} 帧已注入会话</div>`;
        toast('回放完成');
      } catch (err) { toastError(err); }
      finally { btn.disabled = false; }
    };
  }

  /* ---------------------------------------------------------------- socket */
  function connectSocket() {
    if (socket) { try { socket.close(); } catch { /* ignore */ } }
    wsState = 'connecting';
    setWsStatus();
    try {
      socket = openSessionSocket(currentId);
    } catch {
      wsState = 'closed';
      scheduleReconnect();
      return;
    }
    socket.onopen = () => {
      wsState = 'open';
      wsBackoff = 1000;
      setWsStatus();
      patchStates(false);
    };
    socket.onclose = () => {
      wsState = 'closed';
      setWsStatus();
      scheduleReconnect();
    };
    socket.onerror = () => { wsState = 'closed'; setWsStatus(); };
    socket.onmessage = (event) => {
      let item;
      try { item = JSON.parse(event.data); } catch { return; }
      const p = item.payload || {};
      if (item.type === 'log') {
        addLogLocal(p, true);
      } else if (item.type === 'state') {
        if (!detail) return;
        detail.states = { ...detail.states, ...(p.states || {}) };
        patchHeader();
      } else if (item.type === 'issue') {
        if (!detail) return;
        detail.issue = p.severity === 'info' ? null : p;
        patchHeader();
        if (tab === 'connection') renderTab();
      } else if (item.type === 'variables_changed') {
        applyVariableChanges(p.changes);
      } else if (item.type === 'alarm') {
        applyAlarmEvent(p);
      } else if (item.type === 'collection_event') {
        if (detail?.role === 'host') {
          pushFeed({ kind: 'event', tone: 'ok', text: `收到事件 ${p.ceid} ${eventName(p.ceid)}` });
        }
      } else if (item.type === 'remote_command') {
        if (detail?.role === 'equipment') {
          pushFeed({ kind: 'rcmd', tone: p.hcack === 0 ? 'ok' : 'warn', text: `收到远程命令 ${p.rcmd} · HCACK=${p.hcack}` });
          toast(`收到远程命令 ${p.rcmd}（HCACK=${p.hcack}）`, p.hcack === 0 ? 'ok' : 'warn');
        }
      } else if (item.type === 'session_destroyed') {
        toast('会话已被删除', 'warn');
        ctx.navigate('#/overview');
      }
    };
  }

  function applyAlarmEvent(p) {
    if (!detail) return;
    const alid = String(p.alid);
    const set = new Set((detail.alarms_active || []).map(String));
    if (p.set) set.add(alid); else set.delete(alid);
    detail.alarms_active = [...set];
    if (detail.role === 'host') {
      pushFeed({ kind: 'alarm', tone: p.set ? 'warn' : 'ok', text: `收到设备报警 ${alid}${p.text ? `：${p.text}` : ''}（${p.set ? '触发' : '清除'}）` });
      toast(`设备报警 ${alid} ${p.set ? '触发' : '清除'}`, p.set ? 'warn' : 'ok');
    } else {
      patchAlarmRow(alid);
    }
  }

  function scheduleReconnect() {
    if (!alive || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      wsBackoff = Math.min(wsBackoff * 2, 15000);
      if (alive) connectSocket();
    }, wsBackoff);
  }

  /* -------------------------------------------------------------- actions */
  async function toggleConnect(btn) {
    if (!detail) return;
    const connected = detail.states.hsms !== 'NOT_CONNECTED';
    if (connected) {
      const ok = await confirmDialog({
        title: '重启链路',
        message: '将短暂断开当前连接并重新启动监听 / 连接，对端会看到一次断链。确定继续？',
        confirmText: '重启链路',
        danger: false,
      });
      if (!ok) return;
    }
    if (btn) btn.disabled = true;
    try {
      if (!connected) {
        await api.connect(currentId);
        toast('链路已启动');
      } else {
        await api.disconnect(currentId);
        toast('已断开并重新启动链路', 'warn');
      }
      await patchStates(false);
    } catch (err) {
      toastError(err);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function linktest() {
    try {
      const res = await api.send(currentId, 'S1F1 W');
      toast(res.reply ? `S1F1 链路正常，应答 ${res.reply.sf}` : 'S1F1 已发送，未收到应答', res.reply ? 'ok' : 'warn');
      patchGuide();
    } catch (err) {
      toastError(err);
    }
  }

  return {
    cleanup() {
      alive = false;
      clearInterval(refreshTimer);
      clearTimeout(reconnectTimer);
      if (socket) { try { socket.close(); } catch { /* ignore */ } }
    },
    refresh: async () => {
      sessionsList = await api.sessions();
      await loadDetail();
      renderTab();
    },
  };
}
