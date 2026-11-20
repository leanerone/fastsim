import { api } from '../api.js';
import {
  confirmDialog, esc, fmtClock, hydrateIcons, icon, stateLabel, summarizeSml, toast,
} from '../ui.js';

export async function render(ctx) {
  const view = document.getElementById('view');
  let data = await api.overview();
  let alive = true;
  let busy = false;

  paint();
  const timer = setInterval(() => { if (!document.hidden) refresh(false); }, 5000);

  async function refresh(showErrors = true) {
    if (busy) return;
    busy = true;
    try {
      data = await api.overview();
      if (alive && !document.hidden) paint();
    } catch (e) {
      if (showErrors) toast(e.message, 'err');
    } finally {
      busy = false;
    }
  }

  function paint() {
    if (!alive) return;
    const t = data.totals || {};
    const sessions = data.sessions || [];
    const recent = (data.recent || []).filter((entry) => entry.kind !== 'control').slice(0, 6);
    const hasLink = (t.communicating || 0) > 0;
    const hasMessages = (t.messages || 0) > 0;

    view.innerHTML = `
      <div class="page-head start-head">
        <div>
          <div class="eyebrow">SECS/GEM 联调工具</div>
          <h1 class="page-title">从一次双向联调开始</h1>
          <p class="page-sub">不需要先理解协议。创建一对模拟设备与主机，发送第一条消息，再逐步接入真实设备。</p>
        </div>
        <div class="page-actions">
          <a class="btn" href="#/docs">${icon('book', 14)}使用指南</a>
          <button class="btn" data-action="refresh" title="刷新数据">${icon('refresh', 14)}刷新</button>
        </div>
      </div>

      <section class="start-panel">
        <div class="start-primary">
          <span class="start-tag">推荐 · 无需真实设备</span>
          <h2>启动一套可互相通信的设备与主机</h2>
          <p>自动完成被动监听、主动连接和通信参数配置。创建后可直接发送 S1F1 验证双向消息。</p>
          <div class="start-actions">
            <button class="btn primary" data-action="new">${icon('plus', 15)}创建双端演示</button>
            <button class="btn" data-action="choose">选择其他使用场景</button>
          </div>
        </div>
        <ol class="start-progress">
          <li class="${sessions.length ? 'done' : 'active'}"><span>${sessions.length ? '✓' : '1'}</span><div><b>创建联调会话</b><small>${sessions.length ? `已有 ${sessions.length} 个会话` : '选择双端演示或真实连接'}</small></div></li>
          <li class="${hasLink ? 'done' : sessions.length ? 'active' : ''}"><span>${hasLink ? '✓' : '2'}</span><div><b>建立双向通信</b><small>${hasLink ? `${t.communicating} 个会话正在通信` : '等待 HSMS Select 与 GEM 通信'}</small></div></li>
          <li class="${hasMessages ? 'done' : hasLink ? 'active' : ''}"><span>${hasMessages ? '✓' : '3'}</span><div><b>发送并验证消息</b><small>${hasMessages ? `已记录 ${t.messages} 帧消息` : '推荐从 S1F1 链路测试开始'}</small></div></li>
        </ol>
      </section>

      <section class="status-strip" aria-label="运行状态">
        <div><span>会话</span><b>${t.sessions ?? 0}</b></div>
        <div><span>正在通信</span><b class="${t.communicating ? 'ok-text' : ''}">${t.communicating ?? 0}</b></div>
        <div><span>活动报警</span><b class="${t.alarms_active ? 'warn-text' : ''}">${t.alarms_active ?? 0}</b></div>
        <div><span>近 1 分钟消息</span><b>${t.messages_last_minute ?? 0}</b></div>
        <small>同步于 ${fmtClock(data.time)}</small>
      </section>

      <div class="section-head">
        <div class="section-title">我的联调会话 <span class="count">${sessions.length}</span></div>
        <a class="text-link" href="#/docs">不知道选哪个？查看场景说明 →</a>
      </div>
      ${sessions.length ? `<section class="panel session-list">${sessions.map(sessionRow).join('')}</section>` : compactEmpty()}

      <div class="section-head">
        <div class="section-title">最近业务报文</div>
        <div class="section-sub">已隐藏 Select / Linktest 等控制帧，进入工作台可查看全部</div>
      </div>
      <section class="panel">
        ${recent.length ? `<div class="feed">${recent.map(feedRow).join('')}</div>` : '<div class="feed-empty">还没有业务报文。进入会话后发送 S1F1，第一条响应会显示在这里。</div>'}
      </section>`;

    hydrateIcons(view);
    bind();
  }

  function bind() {
    view.querySelectorAll('[data-action="new"]').forEach((btn) => { btn.onclick = () => ctx.openNewSession('demo'); });
    view.querySelector('[data-action="choose"]').onclick = () => ctx.openNewSession();
    view.querySelector('[data-action="refresh"]').onclick = () => refresh(true);
    view.querySelectorAll('[data-open]').forEach((btn) => {
      btn.onclick = () => ctx.navigate(`#/sessions/${encodeURIComponent(btn.dataset.open)}`);
    });
    view.querySelectorAll('[data-delete]').forEach((btn) => {
      btn.onclick = async () => {
        const session = (data.sessions || []).find((s) => s.id === btn.dataset.delete);
        if (!session) return;
        const ok = await confirmDialog({
          title: '删除会话',
          message: `删除「${session.name}」将停止连接并清空内存日志。若它属于双端演示，对端会话会保留。`,
          confirmText: '删除会话',
        });
        if (!ok) return;
        try {
          await api.deleteSession(session.id);
          toast('会话已删除');
          await refresh();
        } catch (e) { toast(e.message, 'err'); }
      };
    });
    view.querySelectorAll('[data-feed]').forEach((row) => {
      row.onclick = () => ctx.navigate(`#/sessions/${encodeURIComponent(row.dataset.feed)}`);
    });
  }

  return {
    cleanup() { alive = false; clearInterval(timer); },
    refresh: () => refresh(true),
  };
}

function sessionRow(s) {
  const state = s.states || {};
  const communicating = state.communication === 'COMMUNICATING';
  return `<article class="session-row">
    <div class="session-role-icon ${s.role}">${icon(s.role === 'host' ? 'terminal' : 'cpu', 18)}</div>
    <div class="session-main"><div><h3>${esc(s.name)}</h3><span class="badge role-${esc(s.role)}">${s.role === 'host' ? '主机端' : '设备端'}</span></div><small>${esc(s.profile_meta?.name || s.profile)} · ${esc(s.connection?.mode)} ${esc(s.connection?.host)}:${esc(s.connection?.port)}</small></div>
    <div class="session-state"><span class="dot ${communicating ? 'ok' : state.hsms === 'SELECTED' ? 'warn' : 'idle'}"></span><div><b>${esc(stateLabel(communicating ? 'COMMUNICATING' : state.hsms))}</b><small>${communicating ? '双向通信正常' : '等待建立通信'}</small></div></div>
    <div class="session-numbers"><b>${s.message_count ?? 0}</b><small>消息</small></div>
    <div class="session-row-actions"><button class="btn sm primary" data-open="${esc(s.id)}">进入工作台</button><button class="icon-btn danger" data-delete="${esc(s.id)}" title="删除 ${esc(s.name)}" aria-label="删除 ${esc(s.name)}">${icon('trash', 14)}</button></div>
  </article>`;
}

function feedRow(entry) {
  const dir = entry.dir === 'in' ? '接收' : '发送';
  return `<button class="feed-item" data-feed="${esc(entry.session)}">
    <span class="feed-time">${fmtClock(entry.ts, true)}</span>
    <span class="feed-session">${esc(entry.session_name || entry.session || '')}</span>
    <span class="feed-direction ${entry.dir}">${dir}</span>
    <span class="feed-sf">${esc(entry.sf || '—')}${entry.w ? ' W' : ''}</span>
    <span class="feed-body">${esc(summarizeSml(entry) || '无消息体')}</span>
  </button>`;
}

function compactEmpty() {
  return `<div class="compact-empty">${icon('layers', 24)}<div><b>还没有会话</b><p>点击上方“创建双端演示”，系统会一次创建设备端和主机端。</p></div></div>`;
}
