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

  async refresh() {
    const data = await App.fetch('/api/vault');
    this.render(data || {});
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'vault') return;
      const fresh = await App.fetch('/api/vault');
      this.render(fresh || {});
    }, 10000);
  },

  render(data) {
    this._renderBanner(data);
    this._renderMetrics(data);
    this._renderColumn('vault-wins', data.recent_wins || [], 'No wins recorded yet.');
    this._renderColumn('vault-errors', data.recent_errors || [], 'No errors recorded yet.');
    this._renderColumn('vault-decisions', data.recent_decisions || [], 'No decisions recorded yet.');
    this._renderLearned(data.recent_learned || []);
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
        ${rows.map(r => `
          <div class="learned-card">
            <div class="learned-title">${this._esc(r.title)}</div>
            ${r.cycle_id ? `<div class="muted">cycle <code>${this._esc(String(r.cycle_id).slice(-10))}</code></div>` : ''}
            ${r.action ? `<div class="muted">${this._esc(r.action)}</div>` : ''}
            <div class="muted vault-note-meta">${this._relTime(r.mtime)}</div>
          </div>`).join('')}
      </div>`;
  },

  _noteCard(r) {
    const tags = (r.tags || []).slice(0, 4).map(
      t => `<span class="vault-tag">${this._esc(t)}</span>`).join('');
    return `
      <div class="vault-note">
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
