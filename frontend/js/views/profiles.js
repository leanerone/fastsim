import { api } from '../api.js';
import { confirmDialog, esc, hydrateIcons, icon, toast } from '../ui.js';
import { invalidateProfileCache } from '../newsession.js';

export async function render(ctx) {
  const view = document.getElementById('view');
  let alive = true;
  const names = await api.profiles();
  const entries = await Promise.all(names.map(async (name) => {
    const [text, data] = await Promise.all([
      api.profileText(name).then((r) => r.text).catch(() => ''),
      api.profile(name).catch(() => null),
    ]);
    return { name, text, data, dirty: false };
  }));

  let selected = localStorage.getItem('fastsim-profile') || entries[0]?.name || '';
  if (!entries.some((e) => e.name === selected)) selected = entries[0]?.name || '';
  let status = null;

  paint();

  function current() {
    return entries.find((e) => e.name === selected) || null;
  }

  function paint() {
    if (!alive) return;
    const entry = current();
    view.innerHTML = `
      <div class="page-head">
        <div>
          <div class="eyebrow">EQUIPMENT PROFILES</div>
          <h1 class="page-title">机台 Profile</h1>
          <p class="page-sub">维护 SECS/GEM 数据字典：状态变量、设备常量、报警、事件与远程命令。保存前会执行完整校验。</p>
        </div>
        <div class="page-actions">
          <button class="btn" id="profile-reload">${icon('refresh', 14)}重新加载</button>
        </div>
      </div>

      <div class="profile-layout">
        <aside class="panel">
          <div class="panel-head">
            <span class="panel-title">${icon('box', 15)}机台列表</span>
            <span class="section-sub">${entries.length}</span>
          </div>
          <div class="profile-list" id="profile-list">
            ${entries.map((e) => {
              const meta = e.data?.profile || {};
              const s = e.data?.status_variables || {};
              return `<button class="profile-item ${e.name === selected ? 'active' : ''}" data-profile="${esc(e.name)}">
                <span class="pname">${esc(meta.name || meta.model || e.name)}${e.dirty ? ' <span class="dot warn" style="display:inline-block"></span>' : ''}</span>
                <span class="pmeta">${esc(e.name)} · ${esc(meta.model || '未知机型')}</span>
                <span class="pcount">${Object.keys(s).length} SV · ${e.data?.connection?.mode || '—'}</span>
              </button>`;
            }).join('') || '<div class="feed-empty">暂无 Profile</div>'}
          </div>
        </aside>

        ${entry ? editorHtml(entry) : '<div class="empty"><h3>没有可编辑的 Profile</h3><p>在 backend/profiles 目录添加 YAML 文件后重新加载。</p></div>'}
      </div>`;

    hydrateIcons(view);
    view.querySelector('#profile-reload').onclick = () => ctx.refresh();
    view.querySelectorAll('[data-profile]').forEach((btn) => {
      btn.onclick = async () => {
        if (btn.dataset.profile === selected) return;
        const cur = current();
        if (cur?.dirty) {
          const ok = await confirmDialog({
            title: '放弃未保存修改？',
            message: `「${cur.name}」有未保存的修改，切换后这些内容会丢失。`,
            confirmText: '放弃并切换',
          });
          if (!ok) return;
        }
        selected = btn.dataset.profile;
        localStorage.setItem('fastsim-profile', selected);
        status = null;
        paint();
      };
    });

    if (!entry) return;
    const editor = view.querySelector('#profile-text');
    editor.oninput = () => {
      entry.dirty = editor.value !== entry.text;
      const listItem = view.querySelector(`[data-profile="${CSS.escape(entry.name)}"]`);
      const statusEl = view.querySelector('#editor-status');
      if (listItem) {
        const dot = listItem.querySelector('.dot');
        if (entry.dirty && !dot) listItem.querySelector('.pname').insertAdjacentHTML('beforeend', ' <span class="dot warn" style="display:inline-block"></span>');
        if (!entry.dirty && dot) dot.remove();
      }
      if (statusEl) {
        statusEl.className = 'editor-status';
        statusEl.innerHTML = entry.dirty ? '<span class="dot warn"></span> 有未保存的修改' : '<span class="dot ok"></span> 与磁盘一致';
      }
    };

    view.querySelector('#profile-validate').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      status = null;
      try {
        const res = await api.validateProfile(editor.value);
        if (res.valid) {
          status = { ok: true, text: '校验通过，可以保存' };
          toast('Profile 校验通过');
        } else {
          status = { ok: false, text: res.error || '校验失败' };
          toast('校验失败', 'err');
        }
      } catch (err) {
        status = { ok: false, text: err.message };
        toast(err.message, 'err');
      } finally {
        btn.disabled = false;
        paintStatus();
      }
    };

    view.querySelector('#profile-save').onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        const check = await api.validateProfile(editor.value);
        if (!check.valid) {
          status = { ok: false, text: check.error || '校验失败，未保存' };
          paintStatus();
          toast('校验失败，未保存', 'err');
          return;
        }
        await api.saveProfile(entry.name, editor.value);
        entry.text = editor.value;
        entry.dirty = false;
        entry.data = await api.profile(entry.name).catch(() => entry.data);
        invalidateProfileCache();
        status = { ok: true, text: '已保存到磁盘' };
        paintStatus();
        toast('Profile 已保存');
        paint();
      } catch (err) {
        status = { ok: false, text: err.message };
        paintStatus();
        toast(err.message, 'err');
      } finally {
        btn.disabled = false;
      }
    };

    view.querySelector('#profile-copy').onclick = async () => {
      try {
        await navigator.clipboard.writeText(editor.value);
        toast('已复制 Profile 原文');
      } catch {
        toast('复制失败', 'err');
      }
    };

    if (status) paintStatus();

    function paintStatus() {
      const el = view.querySelector('#editor-status');
      if (!el || !status) return;
      el.className = `editor-status ${status.ok ? 'ok' : 'bad'}`;
      el.innerHTML = `${icon(status.ok ? 'check' : 'alert', 13)} ${esc(status.text)}`;
    }
  }

  function editorHtml(entry) {
    const d = entry.data || {};
    const counts = [
      ['SV', Object.keys(d.status_variables || {}).length],
      ['DV', Object.keys(d.data_variables || {}).length],
      ['EC', Object.keys(d.equipment_constants || {}).length],
      ['ALID', Object.keys(d.alarms || {}).length],
      ['CEID', Object.keys(d.collection_events || {}).length],
      ['RCMD', Object.keys(d.remote_commands || {}).length],
    ];
    const meta = d.profile || {};
    return `<section class="panel profile-editor">
      <div class="panel-head">
        <span class="panel-title">${icon('file', 15)}${esc(entry.name)}</span>
        <div class="page-actions">
          <button class="icon-btn" id="profile-copy" title="复制原文">${icon('copy', 15)}</button>
        </div>
      </div>
      <div class="panel-body profile-editor">
        <div class="chip-row">
          ${counts.map(([k, v]) => `<span class="stat-chip">${k} <b>${v}</b></span>`).join('')}
          <span class="stat-chip">${esc(meta.model || '未知机型')}</span>
          <span class="stat-chip">${esc(meta.location || '未设置位置')}</span>
        </div>
        <textarea class="textarea code-editor" id="profile-text" spellcheck="false" aria-label="Profile YAML">${esc(entry.text)}</textarea>
        <div class="page-actions" style="justify-content:space-between">
          <div class="editor-status" id="editor-status"><span class="dot ${entry.dirty ? 'warn' : 'ok'}"></span>${entry.dirty ? '有未保存的修改' : '与磁盘一致'}</div>
          <div class="page-actions">
            <button class="btn" id="profile-validate">${icon('check', 14)}校验</button>
            <button class="btn primary" id="profile-save">${icon('save', 14)}保存 Profile</button>
          </div>
        </div>
        <div class="state-note">${icon('info')}<span>保存会直接写入 <code>backend/profiles/${esc(entry.name)}</code>。修改连接参数后，已有会话需重建才会生效。</span></div>
      </div>
    </section>`;
  }

  return {
    cleanup() { alive = false; },
    refresh: () => ctx.refresh(),
  };
}
