import { api } from '../api.js';
import { esc, hydrateIcons, icon, scenarioSteps, toast } from '../ui.js';

export async function render(ctx) {
  const view = document.getElementById('view');
  let alive = true;
  const [names, sessions] = await Promise.all([api.scenarios(), api.sessions()]);
  let cards = [];
  let report = null;
  let lastRun = '';
  let running = null;
  let selectedSession = localStorage.getItem('fastsim-run-session') || sessions[0]?.id || '';

  if (selectedSession && !sessions.some((s) => s.id === selectedSession)) {
    selectedSession = sessions[0]?.id || '';
  }

  if (names.length) {
    cards = await Promise.all(names.map(async (name) => {
      try {
        const res = await api.scenarioText(name);
        return { name, text: res.text, steps: scenarioSteps(res.text) };
      } catch {
        return { name, text: '', steps: [] };
      }
    }));
  }

  paint();

  async function paint() {
    if (!alive) return;
    view.innerHTML = `
      <div class="page-head">
        <div>
          <div class="eyebrow">AUTOMATION · REGRESSION</div>
          <h1 class="page-title">场景中心</h1>
          <p class="page-sub">把联调步骤固化为可重复执行的场景，一键回归 HSMS 通信、事件上报与报警流程。</p>
        </div>
        <div class="page-actions">
          <select class="select" id="run-session" style="max-width:220px" ${sessions.length ? '' : 'disabled'}>
            ${sessions.length
              ? sessions.map((s) => `<option value="${esc(s.id)}" ${s.id === selectedSession ? 'selected' : ''}>${esc(s.name)} · ${s.role === 'host' ? 'HOST' : 'EQUIP'}</option>`).join('')
              : '<option>暂无可用会话</option>'}
          </select>
          <button class="btn" id="scenarios-refresh">${icon('refresh', 14)}刷新</button>
        </div>
      </div>

      ${sessions.length ? '' : `<div class="state-note" style="margin-bottom:16px">${icon('alert')}<span>运行场景需要一个已连接的会话。请先到 <a href="#/overview" style="color:var(--accent)">运行总览</a> 创建并连接会话。</span></div>`}

      <div class="scenario-grid">
        ${cards.map(cardHtml).join('') || `<div class="empty" style="grid-column:1/-1">
          <div class="empty-graphic">${icon('play', 38)}</div>
          <h3>还没有场景文件</h3>
          <p>在 backend/scenarios 目录添加 YAML 场景后，刷新即可在此执行。</p>
        </div>`}
      </div>

      <div id="report-slot">${report ? reportHtml(report) : ''}</div>`;

    hydrateIcons(view);

    view.querySelector('#scenarios-refresh').onclick = () => ctx.refresh();
    const select = view.querySelector('#run-session');
    if (select) {
      select.onchange = (e) => {
        selectedSession = e.target.value;
        localStorage.setItem('fastsim-run-session', selectedSession);
      };
    }
    view.querySelectorAll('[data-run]').forEach((btn) => {
      btn.onclick = () => run(btn.dataset.run, btn);
    });
  }

  async function run(name, btn) {
    if (!selectedSession) {
      toast('请先创建并选择一个会话', 'warn');
      return;
    }
    if (running) return;
    running = name;
    const sessionName = sessions.find((s) => s.id === selectedSession)?.name || selectedSession;
    btn.disabled = true;
    btn.innerHTML = `${icon('refresh', 13)}执行中…`;
    try {
      report = await api.runScenario(selectedSession, name);
      lastRun = sessionName;
      toast(report.ok ? '场景执行通过' : '场景执行失败', report.ok ? 'ok' : 'err');
      const slot = view.querySelector('#report-slot');
      if (slot) {
        slot.innerHTML = reportHtml(report);
        slot.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    } catch (e) {
      toast(e.message, 'err');
    } finally {
      running = null;
      if (document.body.contains(btn)) {
        btn.disabled = false;
        btn.innerHTML = `${icon('playSmall', 13)}运行`;
      }
    }
  }

  function cardHtml(card) {
    const rawName = (card.text.match(/^\s{2,}name:\s*(.+)$/m) || [])[1] || card.name.replace(/\.yaml$/, '');
    const scenarioName = rawName.trim().replace(/^['"]|['"]$/g, '');
    return `<article class="card scenario-card">
      <div>
        <h3>${icon('play', 15)}${esc(scenarioName)}</h3>
        <div class="file">${esc(card.name)} · ${card.steps.length} 步</div>
      </div>
      <div class="scenario-steps">
        ${card.steps.map((s, i) => `<div class="step-line"><span class="idx">${String(i + 1).padStart(2, '0')}</span><span><span class="act">${esc(s.action)}</span>${s.detail ? ` · ${esc(s.detail)}` : ''}</span></div>`).join('') || '<span class="hint">未能解析步骤，请检查 YAML 格式</span>'}
      </div>
      <div class="scenario-foot">
        <button class="btn primary sm" data-run="${esc(card.name)}" title="在当前选中的会话上运行" ${sessions.length ? '' : 'disabled'}>${icon('playSmall', 13)}运行</button>
        ${sessions.length ? '' : '<span class="hint">需要先创建会话</span>'}
      </div>
    </article>`;
  }

  function reportHtml(r) {
    return `<section class="panel report">
      <div class="panel-head">
        <span class="panel-title">${icon('activity', 15)}执行报告 · ${esc(r.scenario)}</span>
        <div class="report-head">
          <span class="pill ${r.ok ? 'ok' : 'bad'}"><span class="dot ${r.ok ? 'ok' : 'bad'}"></span>${r.ok ? 'PASS' : 'FAIL'}</span>
          <span class="section-sub">${r.steps.length} 步 · ${r.duration}s · 会话 ${esc(lastRun)}</span>
        </div>
      </div>
      <div class="report-steps">
        ${r.steps.map((s) => `<div class="report-step">
          <div>
            <span class="status ${s.ok ? 'ok' : 'bad'}">${icon(s.ok ? 'check' : 'x', 11)}</span>
          </div>
          <div>
            <div class="act">${esc(s.action)}</div>
            <div class="detail">${esc(typeof s.detail === 'string' ? s.detail : JSON.stringify(s.detail, null, 2))}</div>
          </div>
          <span class="dur">${s.duration ?? 0}s</span>
        </div>`).join('')}
      </div>
    </section>`;
  }

  return {
    cleanup() { alive = false; },
    refresh: () => ctx.refresh(),
  };
}
