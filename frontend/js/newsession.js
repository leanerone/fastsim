import { api } from './api.js';
import { esc, icon, openModal, toast } from './ui.js';

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

export async function openNewSession(onCreated, initialMode = '') {
  let profiles;
  try {
    profiles = await loadProfiles();
  } catch (e) {
    toast(`读取机台配置失败：${e.message}`, 'err');
    return;
  }
  if (!profiles.length) {
    toast('尚未发现机台配置，请先在“机台配置”中创建', 'warn');
    return;
  }

  const state = {
    step: initialMode ? 2 : 1,
    mode: initialMode || 'demo',
    profile: profiles[0].name,
    name: 'DEMO',
    port: profiles[0].data?.connection?.port || 5000,
    host: profiles[0].data?.connection?.host || '127.0.0.1',
    created: [],
    peer: null,
    communication: '',
    busy: false,
  };

  const modal = openModal({
    title: '新建联调',
    subtitle: '选择使用场景，连接方向由系统自动配置',
    wide: true,
    body: '<div id="ns-body"></div>',
    footer: '<div id="ns-footer" style="display:contents"></div>',
    onMount(layer, close) {
      const body = layer.querySelector('#ns-body');
      const footer = layer.querySelector('#ns-footer');

      function paint() {
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
          if (input) input.oninput = () => { state[key] = input.value; };
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

      async function create() {
        if (state.busy) return;
        const port = Number(state.port);
        if (!Number.isInteger(port) || port < 1 || port > 65535) {
          toast('端口必须是 1–65535 之间的整数', 'warn');
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
          toast(`创建失败：${e.message}`, 'err');
        }
      }

      async function waitForCommunication() {
        const status = body.querySelector('#ns-connection');
        for (let i = 0; i < 12 && state.step === 3; i += 1) {
          try {
            const detail = await api.session(state.peer.id);
            state.communication = detail.states?.communication || '';
            if (state.communication === 'COMMUNICATING') break;
          } catch { /* session state will remain visible as pending */ }
          await new Promise((resolve) => setTimeout(resolve, 450));
        }
        if (state.step !== 3 || !status) return;
        const ok = state.communication === 'COMMUNICATING';
        status.className = `setup-result-status ${ok ? 'ok' : 'warn'}`;
        status.innerHTML = `<span class="dot ${ok ? 'ok' : 'warn'}"></span>${ok ? '双端已建立 GEM 通信，可以开始发送消息。' : '会话已启动，但尚未完成通信。请进入工作台检查端口和对端状态。'}`;
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
          output.className = 'inline-result err';
          output.textContent = `验证失败：${e.message}`;
        } finally {
          btn.disabled = false;
          btn.textContent = '发送 S1F1 验证';
        }
      }

      function configStep() {
        const options = profiles.map((p) => {
          const meta = p.data?.profile || {};
          return `<button type="button" class="profile-option ${p.name === state.profile ? 'active' : ''}" data-profile="${esc(p.name)}">
            <b>${esc(meta.name || meta.model || p.name)}</b><span>${esc(p.name)}</span>
          </button>`;
        }).join('');
        const isDemo = state.mode === 'demo';
        return `<div class="field"><span class="field-label">1. 选择机台模型</span><div class="profile-picker">${options}</div>
          <span class="hint">Profile 只描述设备行为；主动 / 被动方向会根据使用场景自动设置。</span></div>
          <div class="form-row">
            <div class="field"><label for="ns-name">${isDemo ? '演示名称' : '会话名称'}</label><input class="input" id="ns-name" value="${esc(state.name)}" autocomplete="off"><span class="hint">${isDemo ? `将创建 ${esc(state.name || 'DEMO')}-EQ 与 ${esc(state.name || 'DEMO')}-HOST` : '用于在会话列表中识别'}</span></div>
            <div class="field"><label for="ns-port">${isDemo || state.mode === 'equipment' ? '监听端口' : '对端端口'}</label><input class="input mono" id="ns-port" type="number" min="1" max="65535" value="${esc(state.port)}"></div>
          </div>
          ${!isDemo && state.mode === 'host' ? `<div class="field"><label for="ns-host">对端 IP 地址</label><input class="input mono" id="ns-host" value="${esc(state.host)}" autocomplete="off"><span class="hint">本机模拟器通常为 127.0.0.1；真实机台请填写其设备 IP。</span></div>` : ''}
          ${connectionPreview()}`;
      }

      function connectionPreview() {
        if (state.mode === 'demo') {
          return `<div class="connection-preview"><div><span class="endpoint-icon">${icon('cpu', 18)}</span><b>${esc(state.name || 'DEMO')}-EQ</b><small>设备端 · PASSIVE</small></div><span class="connection-arrow">${icon('link', 18)}<small>127.0.0.1:${esc(state.port)}</small></span><div><span class="endpoint-icon host">${icon('terminal', 18)}</span><b>${esc(state.name || 'DEMO')}-HOST</b><small>主机端 · ACTIVE</small></div></div>`;
        }
        const equipment = state.mode === 'equipment';
        return `<div class="state-note">${icon('info')}<span>${equipment ? `FastSim 将监听 ${esc(state.port)} 端口。请在 MES / EAP 中配置主动连接本机地址和该端口。` : `FastSim 将主动连接 ${esc(state.host)}:${esc(state.port)}。请确认对端已开启 HSMS Passive 监听。`}</span></div>`;
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
