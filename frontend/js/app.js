import { api } from './api.js';
import { hydrateIcons, icon, toast } from './ui.js';
import { openNewSession } from './newsession.js';
import * as overview from './views/overview.js';
import * as sessions from './views/session.js';
import * as scenarios from './views/scenarios.js';
import * as profiles from './views/profiles.js';

const ROUTES = {
  overview: { view: overview, title: '开始使用', section: '创建会话并完成第一次联调' },
  sessions: { view: sessions, title: '联调工作台', section: '双向消息与 GEM 操作' },
  scenarios: { view: scenarios, title: '自动化场景', section: '可复现的测试流程' },
  profiles: { view: profiles, title: '机台配置', section: '设备行为模型' },
  docs: { view: null, title: '使用指南', section: '从双端演示到真实设备接入' },
};

let activeView = null;
const $ = (selector) => document.querySelector(selector);

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [path] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  if (!parts.length) return { key: 'overview', params: [] };
  if (parts[0] === 'session' || parts[0] === 'sessions') return { key: 'sessions', params: parts.slice(1) };
  return ROUTES[parts[0]] ? { key: parts[0], params: parts.slice(1) } : { key: 'overview', params: [] };
}

function setNav(key) {
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.route === key));
}

function setPageMeta(key) {
  const meta = ROUTES[key];
  $('#page-title').textContent = meta.title;
  $('#page-section').textContent = meta.section;
  document.title = `${meta.title} · FastSim`;
}

async function renderRoute() {
  const { key, params } = parseRoute();
  setNav(key);
  setPageMeta(key);
  if (activeView?.cleanup) {
    try { activeView.cleanup(); } catch { /* view already gone */ }
  }
  activeView = null;
  const view = $('#view');
  view.innerHTML = loadingSkeleton(key);
  window.scrollTo({ top: 0 });
  const ctx = {
    navigate: (hash) => { location.hash = hash; },
    refresh: () => renderRoute(),
    params,
    openNewSession: (mode) => openNewSession(() => renderRoute(), mode),
  };
  try {
    if (key === 'docs') {
      view.innerHTML = docsPage();
      hydrateIcons(view);
      bindCopyButtons(view);
      view.querySelector('[data-doc-demo]').onclick = () => ctx.openNewSession('demo');
      activeView = { cleanup: () => {} };
      return;
    }
    activeView = await ROUTES[key].view.render(ctx);
  } catch (e) {
    view.innerHTML = errorState(e);
    hydrateIcons(view);
    activeView = { cleanup: () => {} };
  }
}

function loadingSkeleton(key) {
  if (key === 'overview') {
    return `<div class="page-head"><div><div class="eyebrow">SECS/GEM 联调工具</div><h1 class="page-title">正在准备工作区…</h1></div></div>
      <div class="skeleton" style="height:210px;margin-bottom:16px"></div><div class="skeleton" style="height:180px"></div>`;
  }
  return '<div class="skeleton" style="height:42px;width:260px;margin-bottom:20px"></div><div class="skeleton" style="height:360px"></div>';
}

function errorState(error) {
  return `<div class="empty"><div class="empty-graphic">${icon('alert', 34)}</div><h3>页面加载失败</h3><p>${String(error?.message || error)}</p><div class="empty-actions"><button class="btn primary" onclick="location.reload()">重新加载</button></div></div>`;
}

async function pollHealth() {
  try {
    const health = await api.health();
    $('#health-dot').className = 'dot ok pulse';
    $('#health-label').textContent = '服务运行正常';
    $('#health-meta').textContent = `v${health.version} · ${health.sessions} 个会话`;
    $('#live-badge').innerHTML = '<span class="dot ok"></span><span>实时数据</span>';
    const count = $('#nav-session-count');
    count.textContent = health.sessions;
    count.classList.toggle('show', health.sessions > 0);
  } catch (e) {
    $('#health-dot').className = 'dot bad';
    $('#health-label').textContent = '服务连接中断';
    $('#health-meta').textContent = '请检查后端是否已启动';
    $('#live-badge').innerHTML = '<span class="dot bad"></span><span>连接中断</span>';
  }
}

function initTheme() {
  const saved = localStorage.getItem('fastsim-theme');
  const prefersLight = window.matchMedia?.('(prefers-color-scheme: light)').matches;
  const theme = saved === 'light' || saved === 'dark' ? saved : (prefersLight ? 'light' : 'dark');
  document.documentElement.dataset.theme = theme;
  updateThemeIcon(theme);
  $('#theme-toggle').onclick = () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('fastsim-theme', next);
    updateThemeIcon(next);
  };
}

function updateThemeIcon(theme) {
  $('#theme-toggle').innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
}

function initShell() {
  hydrateIcons();
  $('#btn-new-session').onclick = () => openNewSession(() => renderRoute());
  $('#btn-refresh').onclick = () => {
    if (activeView?.refresh) activeView.refresh();
    else renderRoute();
    toast('已刷新');
  };
  const sidebar = $('#sidebar');
  const scrim = $('#scrim');
  const closeDrawer = () => {
    sidebar.classList.remove('open');
    scrim.classList.remove('show');
  };
  $('#menu-btn').onclick = () => {
    sidebar.classList.add('open');
    scrim.classList.add('show');
  };
  scrim.onclick = closeDrawer;
  document.querySelectorAll('.nav-item').forEach((item) => item.addEventListener('click', closeDrawer));
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
}

function docsPage() {
  return `
    <div class="page-head"><div><div class="eyebrow">QUICK START & FIELD GUIDE</div><h1 class="page-title">第一次使用，从这里开始</h1><p class="page-sub">先在本机跑通双端消息，再替换为真实 MES / EAP 或真实机台。每一步都能看到明确的连接和响应结果。</p></div></div>
    <section class="guide-hero">
      <div><span class="start-tag">约 30 秒跑通</span><h2>本机双端演示</h2><p>一键创建 Passive 设备端与 Active 主机端：自动选择空闲端口、自动建立通信、自动发送 S1F1 验证，无需手动修改 YAML。</p><button class="btn primary" data-doc-demo>${icon('zap', 14)}一键创建双端演示</button></div>
      <ol class="guide-steps"><li><b>一键创建</b><span>系统自动挑选空闲端口，生成 EQ / HOST 两个会话并互连。</span></li><li><b>自动通信</b><span>HSMS Select 与 GEM 建链自动完成，进度实时可见。</span></li><li><b>自动验证</b><span>自动发送 S1F1 并确认收到 S1F2，成功后即可进入工作台。</span></li></ol>
    </section>

    <div class="section-head"><div class="section-title">看见命令的效果</div><div class="section-sub">行为引擎：命令 → 状态变化 → 事件上报</div></div>
    <section class="panel guide-log-help">
      <div class="guide-legend" style="margin-top:0"><p>在<b>主机端</b>工作台的“GEM 操作”里发送 <b>START</b> 远程命令：系统会自动用 S1F3 重新查询设备状态，高亮显示变化（如 PROCESS_STATE: IDLE → RUNNING），并列出设备上报的事件。设备端的“实时动态”也会同步显示收到的命令与变量变化。</p></div>
    </section>

    <div class="section-head"><div class="section-title">接入真实系统时怎么选</div></div>
    <section class="guide-mode-grid">
      <article><span class="badge role-equipment">设备端</span><h3>验证 MES / EAP</h3><p>选择“模拟设备，等待 MES 连接”。FastSim 使用 PASSIVE 监听，MES / EAP 使用 ACTIVE 发起连接。</p><dl><div><dt>FastSim</dt><dd>0.0.0.0 / 本机 IP : 端口</dd></div><div><dt>MES / EAP</dt><dd>目标 IP = FastSim 所在机器 IP</dd></div></dl></article>
      <article><span class="badge role-host">主机端</span><h3>验证真实机台或模拟器</h3><p>选择“连接真实设备或模拟器”。FastSim 使用 ACTIVE，对端必须提前开启 PASSIVE 监听。</p><dl><div><dt>FastSim</dt><dd>对端 IP + 对端端口</dd></div><div><dt>设备</dt><dd>HSMS-SS Passive · 相同 Device ID</dd></div></dl></article>
    </section>

    <div class="section-head"><div class="section-title">看懂消息记录</div><div class="section-sub">默认隐藏控制帧，避免 Linktest 心跳淹没业务消息</div></div>
    <section class="panel guide-log-help">
      <div class="guide-log-sample"><time>11:45:20.120</time><span class="log-dir in">↓ 接收</span><div><b>S1F14 <small>建立通信响应</small></b><span>对端返回建链结果与设备型号</span></div></div>
      <div class="guide-legend"><p><b>接收</b>：对端发给当前会话；<b>发送</b>：当前会话发给对端。</p><p>点击消息可展开原始 SML。需要排查 Select、Linktest 时，再勾选“显示 HSMS 控制帧与心跳”。</p></div>
    </section>

    <div class="section-head"><div class="section-title">连不上时按顺序检查</div></div>
    <section class="troubleshoot-grid">
      <article><b>1. 地址与端口</b><p>双端演示两侧端口必须相同。真实连接使用对端实际 IP，不要把设备 IP 填成本机监听地址。</p></article>
      <article><b>2. 主动与被动</b><p>一端必须是 ACTIVE，另一端必须是 PASSIVE。新建向导已自动设置，无需手动改 Profile。</p></article>
      <article><b>3. 通信状态</b><p>先达到 SELECTED，再等待 COMMUNICATING。未通信时不要连续发送业务报文，先查看控制帧。</p></article>
      <article><b>4. 防火墙与占用</b><p>端口被占用时，一键演示会自动换用空闲端口；手动创建会提示占用并提供“自动选择空闲端口”。跨机器联调需放行对应 TCP 端口。</p></article>
    </section>

    <details class="advanced-guide"><summary>开发者接入：REST / WebSocket / MCP 与启动命令</summary><div class="docs-grid">
      <section class="card docs-card"><h3>${icon('link')} REST 与实时流</h3><div class="code-block"><button class="icon-btn copy" data-copy="#c1">${icon('copy', 13)}</button><span id="c1">curl http://127.0.0.1:8000/api/v1/overview</span></div><div class="code-block"><span id="c2">ws://127.0.0.1:8000/ws/{session_id}</span></div><p>REST 用于会话、消息、GEM 与场景操作；WebSocket 推送 log / state / event。</p></section>
      <section class="card docs-card"><h3>${icon('cpu')} MCP 与启动</h3><p>在 MCP 客户端中将 <code>python -m fastsim.mcp_server</code> 配置为 stdio Server，工作目录设为 <code>backend</code>。</p><div class="code-block"><button class="icon-btn copy" data-copy="#c3">${icon('copy', 13)}</button><span id="c3">pip install -r backend/requirements.txt
cd backend
python -m fastsim.app --host 127.0.0.1 --port 8000</span></div><p>Windows 也可运行 <code>run.bat</code>，Linux / Git Bash 使用 <code>run.sh</code>。</p></section>
    </div></details>`;
}

function bindCopyButtons(root) {
  root.querySelectorAll('[data-copy]').forEach((btn) => {
    btn.onclick = async () => {
      const text = root.querySelector(btn.dataset.copy)?.textContent || '';
      try { await navigator.clipboard.writeText(text); toast('已复制'); }
      catch { toast('复制失败', 'err'); }
    };
  });
}

initTheme();
initShell();
pollHealth();
setInterval(pollHealth, 15000);
window.addEventListener('hashchange', renderRoute);
renderRoute();
