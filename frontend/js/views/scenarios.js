import { api } from '../api.js';
import { esc, hydrateIcons, icon, toast, toastError } from '../ui.js';

const ROLE_LABELS = { host: '主机端', equipment: '设备端', any: '任意会话' };

export async function render(ctx) {
  const view = document.getElementById('view');
  let alive = true;
  const [cards, sessions] = await Promise.all([
    api.scenarioManifest().catch(() => []),
    api.sessions(),
  ]);
  let report = null;
  let lastRun = '';
  let running = null;
  // per-scenario session choice, persisted across visits
  const choices = {};

  function matchingSessions(card) {
    if (!card.role || card.role === 'any') return sessions;
    return sessions.filter((s) => s.role === card.role);
  }

  function chosenSession(card) {
    const options = matchingSessions(card);
    if (!options.length) return '';
    const saved = choices[card.file];
    if (saved && options.some((s) => s.id === saved)) return saved;
    return options[0].id;
  }

  paint();

  function paint() {
    if (!alive) return;
    view.innerHTML = `
      <div class="page-head">
        <div>
          <div class="eyebrow">AUTOMATION · REGRESSION</div>
          <h1 class="page-title">场景中心</h1>
          <p class="page-sub">把联调步骤固化为可重复执行的场景，一键回归通信、事件上报与报警流程。每个场景会自动匹配正确角色的会话。</p>
        </div>
        <div class="page-actions">
          <button class="btn" id="scenarios-refresh">${icon('refresh', 14)}刷新</button>
        </div>
      </div>

      ${sessions.length ? '' : `<div class="state-note" style="margin-bottom:16px">${icon('alert')}<span>运行场景需要先创建会话。请到 <a href="#/overview" style="color:var(--accent)">开始使用</a> 一键创建双端演示。</span></div>`}

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
    view.querySelectorAll('[data-scenario-session]').forEach((select) => {
      select.onchange = (e) => { choices[e.target.dataset.scenarioSession] = e.target.value; };
    });
    view.querySelectorAll('[data-run]').forEach((btn) => {
      btn.onclick = () => run(btn.dataset.run, btn);
    });
  }

  function cardHtml(card) {
    const options = matchingSessions(card);
    const selected = chosenSession(card);
    const roleBadge = card.role && card.role !== 'any'
      ? `<span class="badge ${card.role === 'host' ? 'role-host' : 'role-equipment'}">${ROLE_LABELS[card.role]}场景</span>`
      : '<span class="badge neutral">任意会话</span>';
    return `<article class="card scenario-card" data-card="${esc(card.file)}">
      <div>
        <h3>${icon('play', 15)}${esc(card.name)} ${roleBadge}</h3>
        <div class="file">${esc(card.file)} · ${card.steps.length} 步</div>
        ${card.description ? `<p class="scenario-desc">${esc(card.description)}</p>` : ''}
        ${card.error ? `<div class="state-note">${icon('alert')}<span>场景文件解析失败：${esc(card.error)}</span></div>` : ''}
      </div>
      <div class="scenario-steps">
        ${card.steps.map((s, i) => `<div class="step-line"><span class="idx">${String(i + 1).padStart(2, '0')}</span><span>${esc(s.summary || s.action)}</span></div>`).join('') || '<span class="hint">没有可执行的步骤</span>'}
      </div>
      <div class="scenario-foot">
        ${options.length
          ? `<select class="select" data-scenario-session="${esc(card.file)}" aria-label="选择运行会话">
              ${options.map((s) => `<option value="${esc(s.id)}" ${s.id === selected ? 'selected' : ''}>${esc(s.name)} · ${ROLE_LABELS[s.role] || s.role}</option>`).join('')}
            </select>
            <button class="btn primary sm" data-run="${esc(card.file)}" title="在所选会话上运行">${icon('playSmall', 13)}运行</button>`
          : `<span class="hint">需要一个${ROLE_LABELS[card.role] || ''}会话 · <a href="#/overview" style="color:var(--accent)">去创建</a></span>`}
      </div>
    </article>`;
  }

  async function run(file, btn) {
    const card = cards.find((c) => c.file === file);
    const sid = card ? chosenSession(card) : '';
    if (!sid) {
      toast('请先创建并选择一个会话', 'warn');
      return;
    }
    if (running) return;
    running = file;
    const sessionName = sessions.find((s) => s.id === sid)?.name || sid;
    btn.disabled = true;
    btn.innerHTML = `${icon('refresh', 13)}执行中…`;
    try {
      report = await api.runScenario(sid, file);
      lastRun = sessionName;
      toast(report.ok ? '场景执行通过' : '场景执行失败', report.ok ? 'ok' : 'err');
      const slot = view.querySelector('#report-slot');
      if (slot) {
        slot.innerHTML = reportHtml(report);
        hydrateIcons(slot);
        slot.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    } catch (e) {
      toastError(e);
    } finally {
      running = null;
      if (document.body.contains(btn)) {
        btn.disabled = false;
        btn.innerHTML = `${icon('playSmall', 13)}运行`;
      }
    }
  }

  function reportHtml(r) {
    const failed = (r.steps || []).find((s) => !s.ok);
    const failDetail = failed?.detail || {};
    const mismatch = r.code === 'ROLE_MISMATCH';
    return `<section class="panel report">
      <div class="panel-head">
        <span class="panel-title">${icon('activity', 15)}执行报告 · ${esc(r.scenario)}</span>
        <div class="report-head">
          <span class="pill ${r.ok ? 'ok' : 'bad'}"><span class="dot ${r.ok ? 'ok' : 'bad'}"></span>${r.ok ? '通过' : '失败'}</span>
          <span class="section-sub">${(r.steps || []).length} 步 · ${r.duration}s · 会话 ${esc(lastRun)}</span>
        </div>
      </div>
      ${!r.ok ? `<div class="report-fail">
        ${icon('alert', 16)}
        <div>
          <b>${esc(failDetail.message || r.message || r.error || '执行失败')}</b>
          ${(failDetail.hint || r.hint) ? `<span>${esc(failDetail.hint || r.hint)}</span>` : ''}
          ${mismatch ? '<span>提示：场景卡片上的会话下拉框已按角色过滤，选择标注对应角色的会话即可。</span>' : ''}
          ${failDetail.expected != null ? `<div class="diff-row"><span class="diff-k">期望</span><code>${esc(JSON.stringify(failDetail.expected))}</code></div>` : ''}
          ${failDetail.actual != null ? `<div class="diff-row"><span class="diff-k">实际</span><code>${esc(JSON.stringify(failDetail.actual))}</code></div>` : ''}
        </div>
      </div>` : ''}
      <div class="report-steps">
        ${(r.steps || []).map((s) => `<div class="report-step">
          <div><span class="status ${s.ok ? 'ok' : 'bad'}">${icon(s.ok ? 'check' : 'x', 11)}</span></div>
          <div>
            <div class="act">${esc(s.summary || s.action)}</div>
            <div class="detail">${esc(stepDetailText(s))}</div>
          </div>
          <span class="dur">${s.duration ?? 0}s</span>
        </div>`).join('')}
      </div>
    </section>`;
  }

  function stepDetailText(s) {
    const d = s.detail;
    if (d == null) return '';
    if (typeof d === 'string') return d;
    if (!s.ok) return d.error || d.message || JSON.stringify(d);
    return JSON.stringify(d, null, 2);
  }

  return {
    cleanup() { alive = false; },
    refresh: () => ctx.refresh(),
  };
}
