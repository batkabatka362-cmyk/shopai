/* ── Vault tab ───────────────────────────────────────
 *
 * Reads /api/vault and renders:
 *   • metrics row: total notes, wins, errors, learned patterns
 *   • banner: configured path / "not configured" empty state
 *   • 3-column grid: recent wins / errors / decisions
 *   • auto-exported patterns from ShopAI/Learned
 *
 * Auto-refreshes every 10s while the tab is visible.
 */

const Vault = {
  _timer: null,
  _clickBound: false,
  _searchBound: false,
  _searchTimer: null,

  async refresh() {
    this._bindClicks();
    this._bindSearch();
    const data = await App.fetch('/api/vault');
    this.render(data || {});
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'vault') return;
      const fresh = await App.fetch('/api/vault');
      this.render(fresh || {});
    }, 10000);
  },

  // ── Search bar ────────────────────────────────────

  _bindSearch() {
    if (this._searchBound) return;
    const input = document.getElementById('vault-search-input');
    const select = document.getElementById('vault-search-type');
    if (!input || !select) return;
    this._searchBound = true;
    // Debounce so we don't hammer the server on every keystroke.
    const trigger = () => {
      if (this._searchTimer) clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => this._doSearch(), 200);
    };
    input.addEventListener('input', trigger);
    select.addEventListener('change', () => this._doSearch());
  },

  async _doSearch() {
    const input = document.getElementById('vault-search-input');
    const select = document.getElementById('vault-search-type');
    const resultsEl = document.getElementById('vault-search-results');
    const countEl = document.getElementById('vault-search-count');
    if (!input || !resultsEl) return;
    const q = input.value.trim();
    const type = select ? select.value : '';
    // Empty query with "All folders" selected reverts to the idle hint.
    if (!q && !type) {
      resultsEl.innerHTML = `
        <div class="empty-state muted">
          Start typing to search the vault —
          title hits outrank body hits.
        </div>`;
      if (countEl) countEl.textContent = '—';
      return;
    }
    const params = new URLSearchParams();
    params.set('q', q);
    if (type) params.set('type', type);
    params.set('limit', '30');
    let data;
    try {
      const r = await fetch('/api/vault/search?' + params.toString());
      data = await r.json();
    } catch (e) {
      resultsEl.innerHTML =
        `<div class="empty-state muted">Search offline.</div>`;
      return;
    }
    this._renderSearchResults(data);
  },

  _renderSearchResults(data) {
    const resultsEl = document.getElementById('vault-search-results');
    const countEl = document.getElementById('vault-search-count');
    if (!resultsEl) return;
    if (!data.configured) {
      resultsEl.innerHTML = `
        <div class="empty-state muted">
          Vault not configured. Set <code>OBSIDIAN_VAULT_PATH</code>.
        </div>`;
      if (countEl) countEl.textContent = '0';
      return;
    }
    const rows = data.results || [];
    if (countEl) countEl.textContent = String(data.total ?? rows.length);
    if (!rows.length) {
      resultsEl.innerHTML = `
        <div class="empty-state muted">
          No matches${data.query ? ` for “${this._esc(data.query)}”` : ''}.
        </div>`;
      return;
    }
    resultsEl.innerHTML = rows.map(r => `
      <div class="vault-search-row-card vault-note-clickable"
           data-path="${this._esc(r.path)}">
        <div class="vault-search-head">
          <span class="vault-search-title">${this._esc(r.title)}</span>
          <span class="vault-search-folder">${this._esc(r.folder)}</span>
        </div>
        ${r.snippet ? `<div class="vault-search-snippet muted">${this._esc(r.snippet)}</div>` : ''}
        ${(r.tags || []).length
          ? `<div class="vault-tags">${r.tags.slice(0, 6).map(t =>
              `<span class="vault-tag">${this._esc(t)}</span>`).join('')}</div>`
          : ''}
      </div>
    `).join('');
  },

  render(data) {
    this._renderBanner(data);
    this._renderMetrics(data);
    this._renderColumn('vault-wins', data.recent_wins || [], 'No wins recorded yet.');
    this._renderColumn('vault-errors', data.recent_errors || [], 'No errors recorded yet.');
    this._renderColumn('vault-decisions', data.recent_decisions || [], 'No decisions recorded yet.');
    this._renderLearned(data.recent_learned || []);
  },

  // ── Note detail modal ─────────────────────────────

  _bindClicks() {
    if (this._clickBound) return;
    this._clickBound = true;
    // Delegated listener — notes are re-rendered every 10s so we can't
    // attach per-card.
    document.addEventListener('click', (e) => {
      const card = e.target.closest('.vault-note-clickable');
      if (!card || !card.dataset.path) return;
      // Learned-card also carries data-path in the future; gate for now.
      this._openNote(card.dataset.path);
    });
  },

  async _openNote(path) {
    const modal = this._ensureModal();
    const title = modal.querySelector('.vault-modal-title');
    const meta = modal.querySelector('.vault-modal-meta');
    const body = modal.querySelector('.vault-modal-body');
    title.textContent = path;
    meta.textContent = 'loading…';
    body.innerHTML = '';
    modal.classList.add('open');

    let resp;
    try {
      resp = await fetch('/api/vault/note?path=' + encodeURIComponent(path));
    } catch (e) {
      meta.textContent = 'network error';
      return;
    }
    const data = await resp.json();
    if (!resp.ok || data.error) {
      meta.textContent = data.error || 'failed to load';
      return;
    }
    title.textContent = data.title;
    meta.textContent = `${data.path} · ${this._relTime(data.mtime)}`;
    body.innerHTML = this._renderMarkdown(data.body || '');
  },

  _ensureModal() {
    let modal = document.getElementById('vault-modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'vault-modal';
    modal.className = 'vault-modal';
    modal.innerHTML = `
      <div class="vault-modal-card">
        <div class="vault-modal-head">
          <div>
            <div class="vault-modal-title">note</div>
            <div class="vault-modal-meta muted"></div>
          </div>
          <button class="vault-modal-close" aria-label="close">✕</button>
        </div>
        <div class="vault-modal-body"></div>
      </div>`;
    document.body.appendChild(modal);
    const close = () => modal.classList.remove('open');
    modal.querySelector('.vault-modal-close').addEventListener('click', close);
    modal.addEventListener('click', (e) => {
      if (e.target === modal) close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
    return modal;
  },

  _renderMarkdown(src) {
    // Minimal renderer: escape HTML, then apply headings, bold, italic,
    // inline code, fenced code, wikilinks, and line breaks. We avoid
    // a full Markdown lib to keep the dashboard zero-dep.
    const esc = (s) => String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
    // Pull fenced code blocks out first so inline rules don't touch them.
    const fences = [];
    let safe = esc(src).replace(/```([\s\S]*?)```/g, (_m, code) => {
      fences.push(code);
      return `__FENCE_${fences.length - 1}__`;
    });
    safe = safe
      .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^### (.+)$/gm, '<h3>$1</h3>')
      .replace(/^## (.+)$/gm, '<h2>$1</h2>')
      .replace(/^# (.+)$/gm, '<h1>$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
        (_m, target, label) => `<span class="wikilink">${esc(label || target)}</span>`)
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>');
    safe = `<p>${safe}</p>`;
    // Re-inject fenced blocks.
    safe = safe.replace(/__FENCE_(\d+)__/g,
      (_m, i) => `<pre><code>${fences[Number(i)]}</code></pre>`);
    return safe;
  },

  _renderBanner(data) {
    const el = document.getElementById('vault-banner');
    if (!el) return;
    if (!data.configured) {
      el.innerHTML = `
        <div class="empty-state">
          <p><strong>Obsidian vault not configured.</strong></p>
          <p class="muted">
            Set <code>OBSIDIAN_VAULT_PATH=./vault</code> in your environment,
            then restart the dashboard.
            ${data.path ? `<br>Path <code>${this._esc(data.path)}</code> is not a directory.` : ''}
          </p>
        </div>`;
      return;
    }
    el.innerHTML = `
      <div class="vault-banner-ok">
        <div>
          <strong>Vault online.</strong>
          <span class="muted">at <code>${this._esc(data.path)}</code></span>
        </div>
        <div class="muted vault-banner-hint">
          Open the folder in Obsidian to see the graph view.
        </div>
      </div>`;
  },

  _renderMetrics(data) {
    const el = document.getElementById('vault-metrics');
    if (!el) return;
    const totals = data.totals || {};
    if (!data.configured) {
      el.innerHTML = this._metric('Status', 'offline', 'red');
      return;
    }
    el.innerHTML = [
      this._metric('Total Notes', totals.total ?? 0, 'accent',
        `${Object.keys(totals).length - 1} folders`),
      this._metric('Recent Wins', totals.Wins ?? 0, 'green'),
      this._metric('Recent Errors', totals.Errors ?? 0,
        (totals.Errors || 0) > 0 ? 'red' : 'green'),
      this._metric('Learned Patterns', totals['ShopAI/Learned'] ?? 0, 'orange',
        'auto-exported'),
    ].join('');
  },

  _metric(label, value, tone = 'accent', sub = '') {
    return `
      <div class="metric-card ${tone}">
        <div class="metric-label">${label}</div>
        <div class="metric-value">${value}</div>
        ${sub ? `<div class="metric-sub">${sub}</div>` : ''}
      </div>`;
  },

  _renderColumn(id, rows, emptyText) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state muted">${emptyText}</div>`;
      return;
    }
    el.innerHTML = rows.map(r => this._noteCard(r)).join('');
  },

  _renderLearned(rows) {
    const el = document.getElementById('vault-learned');
    if (!el) return;
    if (!rows.length) {
      el.innerHTML = `
        <div class="empty-state muted">
          No patterns auto-exported yet.
          <br>The reflection hook writes here after each cycle that
          produces high-confidence insights.
        </div>`;
      return;
    }
    el.innerHTML = `
      <div class="learned-grid">
        ${rows.map(r => {
          const pathAttr = r.path ? ` data-path="${this._esc(r.path)}"` : '';
          const cls = r.path ? 'learned-card vault-note-clickable' : 'learned-card';
          return `
          <div class="${cls}"${pathAttr}>
            <div class="learned-title">${this._esc(r.title)}</div>
            ${r.cycle_id ? `<div class="muted">cycle <code>${this._esc(String(r.cycle_id).slice(-10))}</code></div>` : ''}
            ${r.action ? `<div class="muted">${this._esc(r.action)}</div>` : ''}
            <div class="muted vault-note-meta">${this._relTime(r.mtime)}</div>
          </div>`;
        }).join('')}
      </div>`;
  },

  _noteCard(r) {
    const tags = (r.tags || []).slice(0, 4).map(
      t => `<span class="vault-tag">${this._esc(t)}</span>`).join('');
    const pathAttr = r.path ? ` data-path="${this._esc(r.path)}"` : '';
    return `
      <div class="vault-note${r.path ? ' vault-note-clickable' : ''}"${pathAttr}>
        <div class="vault-note-head">${this._esc(r.title)}</div>
        <div class="vault-note-meta muted">${this._relTime(r.mtime)}</div>
        ${tags ? `<div class="vault-tags">${tags}</div>` : ''}
      </div>`;
  },

  _relTime(ts) {
    if (!ts) return '—';
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  },

  _esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
};

window.Vault = Vault;
