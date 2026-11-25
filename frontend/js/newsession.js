import { api } from './api.js';
import { esc, explainError, icon, openModal, toast, toastError } from './ui.js';

let cache = null;

async function loadProfiles() {
  if (cache) return cache;
  const names = await api.profiles();
  const details = await Promise.all(names.map(async (name) => {
    try {
      return { name, data: await api.profile(name) };
    } catch {
      return { name, data: null };
    }
  }));
  cache = details;
  return cache;
}

export function invalidateProfileCache() {
  cache = null;
}

const MODES = [
  {
    id: 'demo', icon: 'link', title: '双端演示', tag: '推荐第一次使用',
    desc: '同时创建模拟设备端和主机端，并在本机自动互连。无需真实 MES 或机台。',
  },
  {
    id: 'equipment', icon: 'cpu', title: '模拟设备，等待 MES 连接',
    desc: 'FastSim 作为设备端监听端口，用于验证 MES / EAP 的 SECS/GEM 通讯。',
  },
  {
    id: 'host', icon: 'terminal', title: '连接真实设备或模拟器',
    desc: 'FastSim 作为主机端主动连接对端，用于查询变量、发送远程命令和采集事件。',
  },
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function equipmentProfile(profiles) {
  return profiles.find((p) => p.data?.connection?.mode !== 'ACTIVE') || profiles[0];
}

function uniqueBase(sessions) {
  const used = new Set((sessions || []).map((s) => s.id));
  let base = 'DEMO';
  let n = 1;
  while (used.has(`${base}-EQ`) || used.has(`${base}-HOST`)) {
    n += 1;
    base = `DEMO-${n}`;
  }
  return base;
}

export async function openNewSession(onCreated, initialMode = '') {
  let profiles;
  let sessions = [];
  try {
    profiles = await loadProfiles();
    sessions = await api.sessions().catch(() => []);
  } catch (e) {
    toastError(e);
    return;
  }
  if (!profiles.length) {
    toast('尚未发现机台配置，请先在“机台配置”中创建', 'warn');
    return;
  }
  if (initialMode === 'demo') {
    return expressDemo({ profiles, sessions, onCreated });
  }
  return advancedWizard({ profiles, sessions, onCreated, initialMode });
}

/* ------------------------------------------------------------------ express
   One click: free port -> equipment -> host -> communicate -> S1F1 verify.
   Every step is visible; failures say what happened and offer a fix. */
function expressDemo({ profiles, sessions, onCreated }) {
  const profile = equipmentProfile(profiles);
  const base = uniqueBase(sessions);
  const steps = [
    { id: 'port', label: '选择空闲端口' },
    { id: 'eq', label: `创建设备端 ${base}-EQ（模拟机台）` },
    { id: 'host', label: `创建主机端 ${base}-HOST（模拟 MES）` },
    { id: 'link', label: '建立双向通信' },
    { id: 'verify', label: '验证第一条消息（S1F1 → S1F2）' },
  ];
  const state = {
    status: {}, notes: {}, created: [], port: null,
    busy: true, error: null, closed: false, rtt: null, replySf: '',
  };

  const modal = openModal({
    title: '创建双端演示',
    subtitle: '自动选择端口并验证通信，无需任何配置',
    body: '<div id="ex-body"></div>',
    footer: '<div id="ex-footer" style="display:contents"></div>',
    onClose() { state.closed = true; },
    onMount(layer, close) {
      const body = layer.querySelector('#ex-body');
      const footer = layer.querySelector('#ex-footer');

      function mark(id, status, note = '') {
        state.status[id] = status;
        if (note) state.notes[id] = note;
        paint();
      }

      function paint() {
        if (state.closed || !layer.isConnected) return;
        body.innerHTML = `
          <ol class="setup-timeline" aria-label="创建进度">${steps.map(timelineRow).join('')}</ol>
          ${state.error ? errorBlock() : ''}
          ${!state.busy && !state.error ? successBlock() : ''}`;
        footer.innerHTML = state.busy
          ? '<button class="btn" data-close>关闭（后台继续）</button>'
          : state.error
            ? '<button class="btn" id="ex-advanced">自定义配置</button><button class="btn primary" id="ex-retry">换端口重试</button>'
            : '<button class="btn" data-close>完成</button><button class="btn primary" id="ex-enter">进入联调工作台</button>';
        footer.querySelector('#ex-retry')?.addEventListener('click', retry);
        footer.querySelector('#ex-advanced')?.addEventListener('click', () => {
          close();
          advancedWizard({ profiles, sessions, onCreated, initialMode: 'demo' });
        });
        footer.querySelector('#ex-enter')?.addEventListener('click', () => {
          const host = state.created[1];
          if (host) localStorage.setItem('fastsim.activeSession', host.id);
          close();
          if (host) location.hash = `#/sessions/${encodeURIComponent(host.id)}`;
        });
      }

      function timelineRow(step) {
        const st = state.status[step.id] || 'pending';
        const markHtml = st === 'done' ? `<span class="tl-mark ok">${icon('check', 12)}</span>`
          : st === 'doing' ? '<span class="tl-mark doing"><span class="tl-spin"></span></span>'
            : st === 'failed' ? `<span class="tl-mark bad">${icon('x', 12)}</span>`
              : '<span class="tl-mark idle"></span>';
        const note = state.notes[step.id];
        return `<li class="${st}">${markHtml}<div><b>${esc(step.label)}</b>${note ? `<small>${esc(note)}</small>` : ''}</div></li>`;
      }

      function errorBlock() {
        const { message, hint } = explainError(state.error);
        return `<div class="setup-fail">${icon('alert', 16)}<div><b>${esc(message)}</b>${hint ? `<span>${esc(hint)}</span>` : ''}</div></div>`;
      }

      function successBlock() {
        return `<div class="setup-success">${icon('check', 16)}<div>
          <b>双端演示已就绪</b>
          <span>${esc(base)}-EQ ⇄ ${esc(base)}-HOST · 端口 ${esc(state.port)} · S1F1 → ${esc(state.replySf)} 往返 ${esc(state.rtt)} ms</span>
          <span class="hint">下一步：在主机端工作台的“GEM 操作”里发送 START 命令，观察设备状态变化与事件上报。</span>
        </div></div>`;
      }

      async function collectIssue(...ids) {
        let fallback = null;
        for (const id of ids) {
          try {
            const d = await api.session(id);
            if (d.issue?.severity === 'error') return d.issue;
            if (d.issue && !fallback) fallback = d.issue;
          } catch { /* session may be gone */ }
        }
        return fallback;
      }

      async function waitCommunicating(sid, timeoutMs) {
        const deadline = Date.now() + timeoutMs;
        while (Date.now() < deadline && !state.closed) {
          try {
            const d = await api.session(sid);
            if (d.states?.communication === 'COMMUNICATING') return true;
            if (d.issue?.severity === 'error') {
              throw Object.assign(new Error(d.issue.message), { issue: d.issue });
            }
          } catch (e) {
            if (e.issue) throw e;
          }
          await sleep(400);
        }
        return false;
      }

      async function run(startPort) {
        state.busy = true;
        state.error = null;
        try {
          mark('port', 'doing');
          const start = startPort || profile.data?.connection?.port || 5000;
          const res = await api.freePort('127.0.0.1', start);
          state.port = res.port;
          mark('port', 'done', `使用端口 ${res.port}${res.port !== start ? `（${start} 已被占用，自动避让）` : ''}`);

          mark('eq', 'doing');
          const eq = await api.createSession({
            profile: profile.name, role: 'equipment', mode: 'PASSIVE',
            name: `${base}-EQ`, session_id: `${base}-EQ`, host: '127.0.0.1', port: state.port,
          });
          state.created.push(eq);
          mark('eq', 'done', `监听 127.0.0.1:${state.port}`);
          if (onCreated) onCreated(eq);

          mark('host', 'doing');
          const host = await api.createSession({
            profile: profile.name, role: 'host', mode: 'ACTIVE',
            name: `${base}-HOST`, session_id: `${base}-HOST`, host: '127.0.0.1', port: state.port,
          });
          state.created.push(host);
          rememberPair(eq.id, host.id);
          mark('host', 'done', '主动连接设备端');

          mark('link', 'doing');
          const ok = await waitCommunicating(host.id, 12000);
          if (!ok) {
            const issue = await collectIssue(eq.id, host.id);
            throw Object.assign(new Error(issue?.message || '通信未能建立'), { issue });
          }
          mark('link', 'done', 'HSMS 握手与 GEM 通信已建立');

          mark('verify', 'doing');
          const t0 = performance.now();
          const sent = await api.send(host.id, 'S1F1 W');
          state.rtt = Math.round(performance.now() - t0);
          state.replySf = sent.reply?.sf || '';
          if (!sent.reply) throw new Error('S1F1 已发送，但没有收到应答');
          mark('verify', 'done', `收到 ${state.replySf} · 往返 ${state.rtt} ms`);
          state.busy = false;
          paint();
          if (onCreated) onCreated(host);
        } catch (e) {
          const doing = steps.find((s) => state.status[s.id] === 'doing');
          if (doing) state.status[doing.id] = 'failed';
          state.error = e;
          state.busy = false;
          paint();
        }
      }

      async function retry() {
        for (const s of state.created) {
          try { await api.deleteSession(s.id); } catch { /* keep for inspection */ }
        }
        state.created = [];
        state.status = {};
        state.notes = {};
        paint();
        run(state.port ? state.port + 1 : undefined);
      }

      paint();
      run();
    },
  });
  return modal;
}

/* ----------------------------------------------------------------- advanced
   The full 3-step wizard for custom names / ports / real connections. */
function advancedWizard({ profiles, sessions, onCreated, initialMode }) {
  const ordered = [...profiles].sort((a, b) =>
    (a.data?.connection?.mode === 'ACTIVE') - (b.data?.connection?.mode === 'ACTIVE'));
  const state = {
    step: initialMode ? 2 : 1,
    mode: initialMode || 'demo',
    profile: equipmentProfile(profiles).name,
    name: uniqueBase(sessions),
    port: equipmentProfile(profiles).data?.connection?.port || 5000,
    host: equipmentProfile(profiles).data?.connection?.host || '127.0.0.1',
    created: [],
    peer: null,
    communication: '',
    busy: false,
    closed: false,
    portStatus: '', // '' | 'checking' | 'free' | 'busy'
  };
  let portCheckTimer = null;

  const modal = openModal({
    title: '新建联调',
    subtitle: '选择使用场景，连接方向由系统自动配置',
    wide: true,
    body: '<div id="ns-body"></div>',
    footer: '<div id="ns-footer" style="display:contents"></div>',
    onClose() { state.closed = true; clearTimeout(portCheckTimer); },
    onMount(layer, close) {
      const body = layer.querySelector('#ns-body');
      const footer = layer.querySelector('#ns-footer');

      function paint() {
        if (state.closed || !layer.isConnected) return;
        layer.querySelector('.modal-head p').textContent = state.step === 1
          ? '先选择要完成的任务，无需理解底层连接参数'
          : state.step === 2 ? '确认机台模型与地址，系统会自动设置主动 / 被动模式' : '会话已创建，按下面的步骤完成第一次验证';
        body.innerHTML = `${stepper(state.step)}${state.step === 1 ? modeStep() : state.step === 2 ? configStep() : resultStep()}`;
        footer.innerHTML = state.step === 1
          ? '<button class="btn" data-close>取消</button><button class="btn primary" id="ns-next">继续配置</button>'
          : state.step === 2
            ? '<button class="btn" id="ns-back">返回</button><button class="btn primary" id="ns-create">创建并连接</button>'
            : '<button class="btn" data-close>完成</button>';
        bind();
        if (state.step === 2) schedulePortCheck();
      }

      function bind() {
        body.querySelectorAll('[data-mode]').forEach((btn) => {
          btn.onclick = () => {
            state.mode = btn.dataset.mode;
            body.querySelectorAll('[data-mode]').forEach((item) => {
              const active = item === btn;
              item.classList.toggle('active', active);
              item.setAttribute('aria-checked', String(active));
            });
          };
        });
        footer.querySelector('#ns-next')?.addEventListener('click', () => {
          state.step = 2;
          paint();
        });
        footer.querySelector('#ns-back')?.addEventListener('click', () => {
          state.step = 1;
          paint();
        });
        body.querySelectorAll('[data-profile]').forEach((btn) => {
          btn.onclick = () => {
            state.profile = btn.dataset.profile;
            const selected = profiles.find((p) => p.name === state.profile);
            state.port = selected?.data?.connection?.port || state.port;
            state.host = selected?.data?.connection?.host || state.host;
            paint();
          };
        });
        ['name', 'port', 'host'].forEach((key) => {
          const input = body.querySelector(`#ns-${key}`);
          if (!input) return;
          input.oninput = () => {
            state[key] = input.value;
            // live preview without re-rendering the inputs (keeps focus)
            const preview = body.querySelector('#ns-preview');
            if (preview) preview.innerHTML = connectionPreview();
            if (key === 'port' || key === 'host') schedulePortCheck();
            if (key === 'name') {
              const hint = body.querySelector('#ns-name-hint');
              if (hint && state.mode === 'demo') {
                hint.textContent = `将创建 ${state.name || 'DEMO'}-EQ 与 ${state.name || 'DEMO'}-HOST`;
              }
            }
          };
        });
        const createBtn = footer.querySelector('#ns-create');
        if (createBtn) createBtn.onclick = create;
        body.querySelector('#ns-enter')?.addEventListener('click', () => {
          const target = state.peer || state.created[0];
          if (!target) return;
          localStorage.setItem('fastsim.activeSession', target.id);
          close();
          location.hash = `#/sessions/${encodeURIComponent(target.id)}`;
        });
        body.querySelector('#ns-test')?.addEventListener('click', verifyCommunication);
      }

      function listensLocally() {
        return state.mode === 'demo' || state.mode === 'equipment';
      }

      function schedulePortCheck() {
        clearTimeout(portCheckTimer);
        if (state.step !== 2 || !listensLocally()) return;
        const port = Number(state.port);
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          state.portStatus = '';
          paintPortStatus();
          return;
        }
        state.portStatus = 'checking';
        paintPortStatus();
        portCheckTimer = setTimeout(async () => {
          try {
            const res = await api.checkPort(state.host || '127.0.0.1', port);
            if (Number(state.port) !== port) return; // input changed meanwhile
            state.portStatus = res.free ? 'free' : 'busy';
          } catch {
            state.portStatus = '';
          }
          paintPortStatus();
        }, 350);
      }

      function paintPortStatus() {
        const el = body.querySelector('#ns-port-status');
        if (!el) return;
        if (state.portStatus === 'checking') {
          el.innerHTML = '<span class="port-status checking">检查中…</span>';
        } else if (state.portStatus === 'free') {
          el.innerHTML = `<span class="port-status ok">${icon('check', 11)} 端口可用</span>`;
        } else if (state.portStatus === 'busy') {
          el.innerHTML = `<span class="port-status busy">${icon('alert', 11)} 端口被占用</span><button class="btn sm" id="ns-port-auto" type="button">自动选择空闲端口</button>`;
          el.querySelector('#ns-port-auto').onclick = async () => {
            try {
              const res = await api.freePort(state.host || '127.0.0.1', Number(state.port) || 5000);
              state.port = res.port;
              const input = body.querySelector('#ns-port');
              if (input) input.value = res.port;
              const preview = body.querySelector('#ns-preview');
              if (preview) preview.innerHTML = connectionPreview();
              state.portStatus = 'free';
              paintPortStatus();
              toast(`已选择空闲端口 ${res.port}`);
            } catch (e) { toastError(e); }
          };
        } else {
          el.innerHTML = '';
        }
      }

      async function create() {
        if (state.busy) return;
        const port = Number(state.port);
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          toast('端口必须是 1–65535 之间的整数', 'warn');
          return;
        }
        if (listensLocally() && state.portStatus === 'busy') {
          toast('该端口已被占用，请点击“自动选择空闲端口”或换一个端口', 'warn');
          return;
        }
        const base = String(state.name || 'DEMO').trim().toUpperCase().replace(/[^A-Z0-9_-]+/g, '-').replace(/^-|-$/g, '') || 'DEMO';
        const host = String(state.host || '127.0.0.1').trim();
        state.busy = true;
        const btn = footer.querySelector('#ns-create');
        btn.disabled = true;
        btn.textContent = '正在创建会话…';
        const created = [];
        try {
          if (state.mode === 'demo') {
            created.push(await api.createSession({
              profile: state.profile, role: 'equipment', mode: 'PASSIVE',
              name: `${base}-EQ`, session_id: `${base}-EQ`, host, port,
            }));
            created.push(await api.createSession({
              profile: state.profile, role: 'host', mode: 'ACTIVE',
              name: `${base}-HOST`, session_id: `${base}-HOST`, host, port,
            }));
            state.peer = created[1];
            rememberPair(created[0].id, created[1].id);
          } else {
            const role = state.mode === 'host' ? 'host' : 'equipment';
            created.push(await api.createSession({
              profile: state.profile, role, mode: role === 'host' ? 'ACTIVE' : 'PASSIVE',
              name: base, session_id: base, host, port,
            }));
            state.peer = role === 'host' ? created[0] : null;
          }
          state.created = created;
          cache = null;
          if (onCreated) onCreated(created[0]);
          state.step = 3;
          state.busy = false;
          paint();
          if (state.peer) await waitForCommunication();
        } catch (e) {
          for (const session of created) {
            try { await api.deleteSession(session.id); } catch { /* keep partial session for inspection */ }
          }
          state.busy = false;
          btn.disabled = false;
          btn.textContent = '创建并连接';
          toastError(e);
        }
      }

      async function waitForCommunication() {
        const status = body.querySelector('#ns-connection');
        for (let i = 0; i < 20 && state.step === 3 && !state.closed; i += 1) {
          try {
            const detail = await api.session(state.peer.id);
            state.communication = detail.states?.communication || '';
            if (state.communication === 'COMMUNICATING') break;
            if (detail.issue?.severity === 'error') {
              state.issue = detail.issue;
              break;
            }
          } catch { /* session state will remain visible as pending */ }
          await sleep(450);
        }
        if (state.step !== 3 || !status || state.closed) return;
        const ok = state.communication === 'COMMUNICATING';
        status.className = `setup-result-status ${ok ? 'ok' : 'warn'}`;
        status.innerHTML = `<span class="dot ${ok ? 'ok' : 'warn'}"></span>${ok
          ? '双端已建立 GEM 通信，可以开始发送消息。'
          : esc(state.issue?.message || '会话已启动，但尚未完成通信。请进入工作台查看连接问题与解决办法。')}`;
        const test = body.querySelector('#ns-test');
        if (test) test.hidden = !ok;
      }

      async function verifyCommunication(event) {
        const btn = event.currentTarget;
        const output = body.querySelector('#ns-test-result');
        btn.disabled = true;
        btn.textContent = '正在验证…';
        try {
          const result = await api.send(state.peer.id, 'S1F1 W');
          output.className = 'inline-result ok';
          output.textContent = `验证成功：收到 ${result.reply?.sf || '响应'}，双端消息收发正常。`;
        } catch (e) {
          const { message, hint } = explainError(e);
          output.className = 'inline-result err';
          output.textContent = `验证失败：${message}${hint ? `。${hint}` : ''}`;
        } finally {
          btn.disabled = false;
          btn.textContent = '发送 S1F1 验证';
        }
      }

      function configStep() {
        const options = ordered.map((p, i) => {
          const meta = p.data?.profile || {};
          const recommended = i === 0 && p.data?.connection?.mode !== 'ACTIVE';
          return `<button type="button" class="profile-option ${p.name === state.profile ? 'active' : ''}" data-profile="${esc(p.name)}">
            <b>${esc(meta.name || meta.model || p.name)}${recommended ? ' <em class="rec-tag">推荐</em>' : ''}</b><span>${esc(p.name)}</span>
          </button>`;
        }).join('');
        const isDemo = state.mode === 'demo';
        return `<div class="field"><span class="field-label">1. 选择机台模型</span><div class="profile-picker">${options}</div>
          <span class="hint">Profile 只描述设备行为；主动 / 被动方向会根据使用场景自动设置。</span></div>
          <div class="form-row">
            <div class="field"><label for="ns-name">${isDemo ? '演示名称' : '会话名称'}</label><input class="input" id="ns-name" value="${esc(state.name)}" autocomplete="off"><span class="hint" id="ns-name-hint">${isDemo ? `将创建 ${esc(state.name || 'DEMO')}-EQ 与 ${esc(state.name || 'DEMO')}-HOST` : '用于在会话列表中识别'}</span></div>
            <div class="field"><label for="ns-port">${isDemo || state.mode === 'equipment' ? '监听端口' : '对端端口'}</label><input class="input mono" id="ns-port" type="number" min="1" max="65535" value="${esc(state.port)}"><span class="port-status-row" id="ns-port-status"></span></div>
          </div>
          ${!isDemo && state.mode === 'host' ? `<div class="field"><label for="ns-host">对端 IP 地址</label><input class="input mono" id="ns-host" value="${esc(state.host)}" autocomplete="off"><span class="hint">本机模拟器通常为 127.0.0.1；真实机台请填写其设备 IP。</span></div>` : ''}
          <div id="ns-preview">${connectionPreview()}</div>`;
      }

      function connectionPreview() {
        if (state.mode === 'demo') {
          return `<div class="connection-preview"><div><span class="endpoint-icon">${icon('cpu', 18)}</span><b>${esc(state.name || 'DEMO')}-EQ</b><small>设备端 · PASSIVE</small></div><span class="connection-arrow">${icon('link', 18)}<small>127.0.0.1:${esc(state.port)}</small></span><div><span class="endpoint-icon host">${icon('terminal', 18)}</span><b>${esc(state.name || 'DEMO')}-HOST</b><small>主机端 · ACTIVE</small></div></div>`;
        }
        const equipment = state.mode === 'equipment';
        return `<div class="state-note">${icon('info')}<span>${equipment ? `FastSim 将监听 ${esc(state.port)} 端口。请在 MES / EAP 中配置主动连接本机地址和该端口。` : `FastSim 将主动连接 ${esc(state.host)}:${esc(state.port)}。请确认对端已开启 HSMS Passive 监听；连不上时工作台会显示具体原因。`}</span></div>`;
      }

      function resultStep() {
        const isDemo = state.created.length === 2;
        return `<div class="setup-result-status warn" id="ns-connection"><span class="dot ${state.peer ? 'warn pulse' : 'ok'}"></span>${state.peer ? '会话已启动，正在确认 GEM 通信…' : '会话已创建并启动。'}</div>
          <div class="created-sessions">${state.created.map((s) => `<div><span class="badge role-${s.role}">${s.role === 'host' ? '主机端' : '设备端'}</span><b>${esc(s.name)}</b><code>${esc(s.connection.mode)} · ${esc(s.connection.host)}:${esc(s.connection.port)}</code></div>`).join('')}</div>
          <div class="next-guide"><b>下一步：验证第一条消息</b><ol><li>进入${isDemo ? '主机端' : '会话'}工作台</li><li>打开“发送消息”，选择 <code>S1F1</code></li><li>点击发送，在下方查看响应；再到“消息记录”检查完整报文</li></ol></div>
          ${state.peer ? '<button class="btn" id="ns-test" hidden>发送 S1F1 验证</button><div id="ns-test-result" aria-live="polite"></div>' : ''}
          <button class="btn primary block" id="ns-enter">进入联调工作台</button>`;
      }

      paint();
    },
  });
  return modal;
}

function stepper(step) {
  return `<ol class="wizard-steps" aria-label="创建进度">${['选择场景', '配置连接', '开始验证'].map((label, i) => `<li class="${step === i + 1 ? 'active' : step > i + 1 ? 'done' : ''}"><span>${step > i + 1 ? '✓' : i + 1}</span>${label}</li>`).join('')}</ol>`;
}

function modeStep() {
  return `<div class="mode-options" role="radiogroup" aria-label="使用场景">${MODES.map((mode) => `<button type="button" role="radio" aria-checked="${mode.id === 'demo'}" class="mode-option ${mode.id === 'demo' ? 'active' : ''}" data-mode="${mode.id}"><span class="mode-icon">${icon(mode.icon, 20)}</span><span><b>${mode.title}</b>${mode.tag ? `<em>${mode.tag}</em>` : ''}<small>${mode.desc}</small></span></button>`).join('')}</div>`;
}

function rememberPair(equipmentId, hostId) {
  let pairs = {};
  try { pairs = JSON.parse(localStorage.getItem('fastsim.pairs') || '{}'); } catch { pairs = {}; }
  pairs[equipmentId] = hostId;
  pairs[hostId] = equipmentId;
  localStorage.setItem('fastsim.pairs', JSON.stringify(pairs));
}
