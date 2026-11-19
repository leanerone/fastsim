/* FastSim frontend (vanilla JS, no build step) */
const API = '/api/v1';
let sessions = [];
let currentSession = null;
let ws = null;
let logLines = [];

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) {}
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
}

function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false }) }

function toast(msg, ok = true) {
  const el = $('#sml-result') || $('#rec-result');
  if (el) { el.textContent = msg; el.style.color = ok ? 'var(--ok)' : 'var(--err)'; }
}

/* ---------------- tabs ---------------- */
$$('nav#tabs button').forEach(b => b.onclick = () => {
  $$('nav#tabs button').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $$('.tab').forEach(t => t.classList.remove('active'));
  $('#tab-' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'dashboard') refreshDashboard();
  if (b.dataset.tab === 'session') refreshSessionTab();
  if (b.dataset.tab === 'scenario') refreshScenarioTab();
  if (b.dataset.tab === 'profiles') loadProfileEditor();
});
$$('.subtabs button').forEach(b => b.onclick = () => {
  $$('.subtabs button').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  $$('.subtab').forEach(t => t.classList.remove('active'));
  $('#sub-' + b.dataset.sub).classList.add('active');
});

/* ---------------- dashboard ---------------- */
async function refreshDashboard() {
  try {
    sessions = await api('/sessions');
    const profiles = await api('/profiles');
    renderCards(); fillProfileSelect(profiles); fillSessionSelects();
  } catch (e) { console.error(e); }
}

function renderCards() {
  const el = $('#session-cards');
  el.innerHTML = '';
  sessions.forEach(s => {
    const c = document.createElement('div');
    c.className = 'card';
    const st = s.states;
    c.innerHTML = `
      <div class="row"><h3>${s.name}</h3><span class="role ${s.role}">${s.role}</span></div>
      <div class="st">Profile: ${s.profile}</div>
      <div class="st">HSMS: <b>${st.hsms}</b> · 通信: <b>${st.communication}</b> · 控制: <b>${st.control}</b></div>
      <div class="toolbar">
        <button data-del="${s.id}">删除</button>
        <button data-open="${s.id}">打开详情</button>
      </div>`;
    c.querySelector('[data-open]').onclick = () => {
      $('#sel-session').value = s.id; selectSession(s.id);
      $$('nav#tabs button').find(x => x.dataset.tab === 'session').click();
    };
    c.querySelector('[data-del]').onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`删除会话 ${s.id}?`)) return;
      await api('/sessions/' + s.id, { method: 'DELETE' });
      refreshDashboard();
    };
    el.appendChild(c);
  });
}

function fillProfileSelect(profiles) {
  const sel = $('#dlg-profile');
  sel.innerHTML = profiles.map(p => `<option>${p}</option>`).join('');
}

async function newSessionDialog() {
  $('#dialog-new').classList.remove('hidden');
}
$('#btn-new-session').onclick = newSessionDialog;
$('#btn-refresh').onclick = refreshDashboard;
$('#dlg-cancel').onclick = () => $('#dialog-new').classList.add('hidden');
$('#dlg-create').onclick = async () => {
  const body = {
    profile: $('#dlg-profile').value,
    role: $('#dlg-role').value,
    name: $('#dlg-name').value || null,
    port: $('#dlg-port').value ? parseInt($('#dlg-port').value) : null,
  };
  try {
    await api('/sessions', { method: 'POST', body });
    $('#dialog-new').classList.add('hidden');
    refreshDashboard();
  } catch (e) { alert(e.message); }
};

/* ---------------- session tab ---------------- */
function fillSessionSelects() {
  const opts = sessions.map(s => `<option value="${s.id}">${s.name} [${s.role}]</option>`).join('');
  $('#sel-session').innerHTML = opts || '<option value="">(无会话)</option>';
  $('#sel-scenario-session').innerHTML = opts || '<option value="">(无会话)</option>';
  if (!currentSession && sessions.length) { $('#sel-session').value = sessions[0].id; selectSession(sessions[0].id); }
}

$('#sel-session').onchange = () => selectSession($('#sel-session').value);

function selectSession(id) {
  currentSession = id;
  connectWS();
  refreshSessionTab();
}

async function refreshSessionTab() {
  if (!currentSession) return;
  try {
    const s = await api('/sessions/' + currentSession);
    $('#sess-states').innerHTML = `HSMS: <b>${s.states.hsms}</b> 通信: <b>${s.states.communication}</b> 控制: <b>${s.states.control}</b>`;
    renderConnTable(s);
    renderGemPanel();
    loadMsgLib();
  } catch (e) { console.error(e); }
}

async function renderConnTable(s) {
  const conn = s.connection || {};
  const cfg = conn.timeouts || {};
  $('#tbl-conn').innerHTML = `
    <tr><td>Profile</td><td>${s.profile}</td></tr>
    <tr><td>模式</td><td>${conn.mode}</td></tr>
    <tr><td>监听/连接</td><td>${conn.host}:${conn.port}</td></tr>
    <tr><td>Device ID</td><td>${conn.device_id}</td></tr>
    <tr><td>T3/T5/T6/T7/T8</td><td>${cfg.t3}/${cfg.t5}/${cfg.t6}/${cfg.t7}/${cfg.t8}</td></tr>
    <tr><td>Linktest</td><td>${cfg.linktest}s</td></tr>`;
}

$('#btn-connect').onclick = () => api(`/sessions/${currentSession}/connect`, { method: 'POST' }).then(refreshSessionTab).catch(e => alert(e.message));
$('#btn-disconnect').onclick = () => api(`/sessions/${currentSession}/disconnect`, { method: 'POST' }).then(refreshSessionTab).catch(e => alert(e.message));
$('#btn-linktest').onclick = () => api(`/sessions/${currentSession}/send`, { method: 'POST', body: { sml: 'S1F1 W' } }).then(j => toast('S1F2: ' + (j.reply ? j.reply.sf : 'no reply'))).catch(e => toast(e.message, false));
$('#btn-select').onclick = () => api(`/sessions/${currentSession}/send`, { method: 'POST', body: { sml: 'S1F13 W <L [2] <A "FASTSIM"> <A "1.0.0">>' } }).then(j => toast('S1F14: ' + (j.reply ? j.reply.sf : 'no reply'))).catch(e => toast(e.message, false));

/* ---------------- msg lib & SML sender ---------------- */
const MSG_LIB = [
  ['S1F1 W', 'Are You There'], ['S1F13 W', '建立通信'],
  ['S1F15 W', '请求离线'], ['S1F17 W', '请求在线'],
  ['S2F33 W', '定义报告'], ['S2F35 W', '链接事件'], ['S2F37 W', '使能事件'],
  ['S5F3 W', '报警使能'], ['S5F5 W', '查询报警'], ['S7F5 W', 'PP下载'],
  ['S7F19 W', 'PP列表'], ['S9F5 W', '未知功能'],
];
function loadMsgLib() {
  $('#msg-lib').innerHTML = MSG_LIB.map(([sf, desc]) =>
    `<span class="chip" data-sml="${sf}">${sf} · ${desc}</span>`).join('');
  $$('#msg-lib .chip').forEach(ch => ch.onclick = () => {
    $('#sml-input').value = ch.dataset.sml;
  });
}

$('#btn-send-sml').onclick = async () => {
  try {
    const j = await api(`/sessions/${currentSession}/send`, { method: 'POST', body: { sml: $('#sml-input').value } });
    $('#sml-result').textContent = '已发送 ' + j.sf + (j.reply ? ' | 应答: ' + j.reply.sf : ' | (无 W 位)');
    $('#sml-result').style.color = 'var(--ok)';
    if (j.reply && j.reply.sml) appendLog({ dir: 'reply', sf: j.reply.sf, sml: j.reply.sml, ts: Date.now() / 1000 });
  } catch (e) {
    $('#sml-result').textContent = e.message; $('#sml-result').style.color = 'var(--err)';
  }
};

/* ---------------- logs & websocket ---------------- */
function connectWS() {
  if (ws) { ws.close(); ws = null; }
  if (!currentSession) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/${currentSession}`);
  ws.onopen = () => $('#ws-status').textContent = '● 实时连接';
  ws.onclose = () => $('#ws-status').textContent = '○ 已断开';
  ws.onmessage = (ev) => {
    const item = JSON.parse(ev.data);
    if (item.type === 'log') appendLog(item.payload);
    if (item.type === 'state') refreshSessionTab();
  };
}

function appendLog(entry) {
  logLines.push(entry);
  if (logLines.length > 2000) logLines.shift();
  renderLogLine(entry);
}

function renderLogLine(e) {
  const dirOk = !$('#log-filter-dir').value || e.dir === $('#log-filter-dir').value;
  const sfOk = !$('#log-filter-sf').value || (e.sf || '').startsWith($('#log-filter-sf').value);
  if (!dirOk || !sfOk) return;
  const el = $('#log-view');
  const div = document.createElement('div');
  const cls = e.dir === 'in' ? 'in' : e.dir === 'out' ? 'out' : 'ctrl';
  const arrow = e.dir === 'in' ? '← ' : e.dir === 'out' ? '→ ' : '· ';
  div.className = 'log-line ' + cls;
  div.textContent = `${arrow}${fmtTime(e.ts)} ${e.sf || e.desc || ''}${e.w ? ' W' : ''}\n${e.sml || ''}`;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
}

function rerenderLogs() {
  $('#log-view').innerHTML = '';
  logLines.forEach(renderLogLine);
}
$('#btn-clear-logs').onclick = () => { logLines = []; $('#log-view').innerHTML = ''; };
$('#log-filter-dir').onchange = rerenderLogs;
$('#log-filter-sf').oninput = rerenderLogs;

/* ---------------- GEM panel ---------------- */
async function renderGemPanel() {
  if (!currentSession) return;
  try {
    const vars = await api(`/sessions/${currentSession}/variables`);
    const s = sessions.find(x => x.id === currentSession) || await api('/sessions/' + currentSession);
    const prof = await api('/profiles/' + s.profile);
    // ---- all data fetched; now render atomically (avoid concurrent re-render dupes) ----
    // alarms
    const ap = $('#alarm-panel');
    ap.innerHTML = '';
    Object.entries(prof.alarms || {}).forEach(([alid, a]) => {
      const row = document.createElement('div');
      row.className = 'alarm-row';
      row.innerHTML = `<span class="mono">${alid}</span> <span>${a.name}</span>`;
      const b1 = mkBtn('SET', async () => { await api(`/sessions/${currentSession}/alarms/${alid}/set`, { method: 'POST' }); toast('已触发 ' + alid); });
      const b2 = mkBtn('CLR', async () => { await api(`/sessions/${currentSession}/alarms/${alid}/clear`, { method: 'POST' }); toast('已清除 ' + alid); });
      row.append(b1, b2);
      ap.appendChild(row);
    });
    // events
    const ep = $('#event-panel');
    ep.innerHTML = '';
    Object.entries(prof.collection_events || {}).forEach(([ceid, c]) => {
      const row = document.createElement('div');
      row.className = 'event-row';
      row.innerHTML = `<span class="mono">${ceid}</span> <span>${c.name || ''}</span>`;
      row.append(mkBtn('触发', async () => {
        await api(`/sessions/${currentSession}/events/${ceid}/trigger`, { method: 'POST', body: {} });
        toast('事件 ' + ceid + ' 已触发');
      }));
      ep.appendChild(row);
    });
    // variables table
    const vp = $('#var-panel');
    vp.innerHTML = '<table class="minitable"><tr><th>ID</th><th>名称</th><th>值</th><th></th></tr></table>';
    const tbl = vp.querySelector('table');
    const groups = [['SV', vars.status_variables], ['DV', vars.data_variables], ['EC', vars.equipment_constants]];
    groups.forEach(([g, map]) => {
      Object.entries(map || {}).forEach(([vid, v]) => {
        const tr = document.createElement('tr');
        const val = v.value === null ? '' : v.value;
        tr.innerHTML = `<td>${vid}</td><td>${g}:${v.def.name}</td>
          <td><input class="var-input" value="${String(val).replace(/"/g, '&quot;')}"></td><td></td>`;
        const inp = tr.querySelector('input');
        const btn = mkBtn('设值', async () => {
          let val = inp.value;
          if (v.def.type.startsWith('U') || v.def.type.startsWith('I')) val = Number(val);
          if (v.def.type.startsWith('F')) val = parseFloat(val);
          await api(`/sessions/${currentSession}/variables`, { method: 'PUT', body: { vid: vid, value: val } });
          toast(`${vid} = ${inp.value}`);
        });
        tr.lastElementChild.appendChild(btn);
        tbl.appendChild(tr);
      });
    });
    // control state + remote commands
    const cp = $('#ctrl-panel');
    cp.innerHTML = '<b>控制状态切换:</b><div class="toolbar" id="cs-btns"></div><b>远程命令 (S2F41):</b><div id="rc-area"></div>';
    ['EQUIPMENT_OFFLINE', 'ATTEMPT_ONLINE', 'HOST_OFFLINE', 'ONLINE_LOCAL', 'ONLINE_REMOTE'].forEach(t => {
      const b = mkBtn(t, async () => {
        await api(`/sessions/${currentSession}/control-state`, { method: 'POST', body: { target: t } });
        refreshSessionTab();
      });
      $('#cs-btns').appendChild(b);
    });
    const rca = cp.querySelector('#rc-area');
    Object.entries(prof.remote_commands || {}).forEach(([cmd, d]) => {
      const row = document.createElement('div');
      row.className = 'event-row';
      row.innerHTML = `<span class="mono">${cmd}</span> <span class="muted">${d.description || ''}</span>`;
      const inp = document.createElement('input');
      inp.className = 'var-input'; inp.placeholder = '参数 JSON';
      row.append(inp, mkBtn('发送', async () => {
        let params = {};
        try { params = inp.value ? JSON.parse(inp.value) : {}; } catch (e) { alert('参数需为 JSON'); return; }
        const j = await api(`/sessions/${currentSession}/remote-command`, { method: 'POST', body: { rcmd: cmd, params } });
        toast(`HCACK=${j.hcack}`, j.hcack === 0);
      }));
      rca.appendChild(row);
    });
  } catch (e) { console.error(e); }
}

function mkBtn(text, fn) {
  const b = document.createElement('button');
  b.textContent = text; b.style.cssText = 'font-size:12px;padding:3px 10px;';
  b.onclick = fn;
  return b;
}

/* ---------------- scenario tab ---------------- */
async function refreshScenarioTab() {
  try {
    const scs = await api('/scenarios');
    $('#sel-scenario').innerHTML = scs.map(s => `<option>${s}</option>`).join('');
    fillSessionSelects();
  } catch (e) { console.error(e); }
}
$('#btn-run-scenario').onclick = async () => {
  const sid = $('#sel-scenario-session').value;
  const name = $('#sel-scenario').value;
  if (!sid || !name) return;
  $('#scenario-report').textContent = '运行中...';
  try {
    const rep = await api(`/sessions/${sid}/scenario/${name}/run`, { method: 'POST', body: {} });
    $('#scenario-report').textContent = JSON.stringify(rep, null, 2);
  } catch (e) { $('#scenario-report').textContent = '错误: ' + e.message; }
};

/* ---------------- profiles tab ---------------- */
async function loadProfileEditor() {
  const profiles = await api('/profiles');
  if (!profiles.length) return;
  const name = profiles[0];
  try {
    const p = await api('/profiles/' + name);
    $('#profile-text').value = yamlDump(p);
    $('#profile-text').dataset.name = name;
  } catch (e) { console.error(e); }
}
function yamlDump(obj) { /* best-effort simple dump via JSON for MVP editor */
  return JSON.stringify(obj, null, 2);
}
$('#btn-profile-validate').onclick = async () => {
  try {
    const j = await api('/profiles/validate', { method: 'POST', body: { text: $('#profile-text').value } });
    $('#profile-result').textContent = j.valid ? '✓ 校验通过' : '✗ ' + j.error;
    $('#profile-result').style.color = j.valid ? 'var(--ok)' : 'var(--err)';
  } catch (e) { $('#profile-result').textContent = e.message; }
};

/* ---------------- record / replay ---------------- */
$('#btn-rec-start').onclick = async () => {
  const j = await api(`/sessions/${currentSession}/record/start`, { method: 'POST' });
  $('#rec-result').textContent = '录制中: ' + j.recording;
};
$('#btn-rec-stop').onclick = async () => {
  const j = await api(`/sessions/${currentSession}/record/stop`, { method: 'POST' });
  $('#rec-result').textContent = `录制完成: ${j.frames} 帧 -> ${j.recording}`;
  $('#rec-result').dataset.path = j.recording;
};
$('#btn-replay').onclick = async () => {
  const p = $('#rec-result').dataset.path;
  if (!p) { alert('请先录制'); return; }
  const j = await api(`/sessions/${currentSession}/replay`, { method: 'POST', body: { recording: p, speed: 1.0 } });
  $('#rec-result').textContent = `回放: ${j.replayed}/${j.total} 帧`;
};

/* ---------------- init ---------------- */
refreshDashboard();
setInterval(async () => {
  if ($('#tab-dashboard').classList.contains('active')) refreshDashboard();
}, 5000);
