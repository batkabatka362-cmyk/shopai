/* ── Reliability tab — Option R ──────────────────────────────
 *
 * Polls /api/retries on entry and every 15s while the tab is visible.
 * Renders:
 *   • three metric cards: total calls, retries, giveups
 *   • circuit-breaker rows with colour-coded state chips
 *   • per-adapter retry rows sorted by retries+giveups
 *
 * The endpoint never 500s — a fresh process simply reports zeros,
 * which we render as an informative empty state instead of a blank.
 */

const Reliability = {
  _timer: null,

  async refresh() {
    const data = await App.fetch('/api/retries');
    this.render(data || {});
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'reliability') return;
      const fresh = await App.fetch('/api/retries');
      this.render(fresh || {});
    }, 15000);
  },

  render(data) {
    this._renderMetrics(data.totals || {});
    this._renderBreakers(data.breakers || []);
    this._renderAdapters(data.per_adapter || []);
  },

  _renderMetrics(totals) {
    const el = document.getElementById('reliability-metrics');
    if (!el) return;
    el.innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Router calls</div>
        <div class="metric-value">${totals.calls || 0}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Retried</div>
        <div class="metric-value">${totals.retries || 0}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Gave up</div>
        <div class="metric-value">${totals.giveups || 0}</div>
      </div>
    `;
  },

  _renderBreakers(breakers) {
    const body = document.getElementById('reliability-breakers');
    const badge = document.getElementById('reliability-breakers-badge');
    if (!body) return;
    if (badge) badge.textContent = String(breakers.length);
    if (!breakers.length) {
      body.innerHTML = `<div class="empty-state muted">
        No adapters have been called through the router yet. Breakers
        appear here after the first call to each adapter.
      </div>`;
      return;
    }
    const rows = breakers.map(br => {
      const state = br.state || 'closed';
      const cls = state === 'open' ? 'badge-red'
        : state === 'half_open' ? 'badge-orange'
        : 'badge-green';
      return `
        <div class="breaker-row">
          <div class="breaker-name">${this._esc(br.adapter)}</div>
          <div class="breaker-state">
            <span class="badge ${cls}">${state}</span>
          </div>
          <div class="breaker-stats muted">
            trips ${br.trips || 0} · consecutive ${br.consecutive_failures || 0}
            · threshold ${br.fail_threshold || 0}
            · cool-down ${this._fmtSec(br.reset_after_s)}
          </div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="breaker-list">${rows}</div>`;
  },

  _renderAdapters(rows) {
    const body = document.getElementById('reliability-adapters');
    const badge = document.getElementById('reliability-adapters-badge');
    if (!body) return;
    if (badge) badge.textContent = String(rows.length);
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No retries have happened yet. Transient failures from LLM APIs
        (HTTP 429, 502, timeouts) will show up here.
      </div>`;
      return;
    }
    const items = rows.map(r => {
      const rate = Math.round(((r.success_rate || 0) * 100));
      return `
        <div class="adapter-retry-row">
          <div class="adapter-retry-name">${this._esc(r.adapter)}</div>
          <div class="adapter-retry-stats">
            <span class="muted">${r.calls || 0} calls</span>
            <span class="badge badge-orange">${r.retries || 0} retries</span>
            <span class="badge badge-red">${r.giveups || 0} gave up</span>
            <span class="badge badge-green">${rate}% ok</span>
          </div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="adapter-retry-list">${items}</div>`;
  },

  _fmtSec(s) {
    const n = Number(s || 0);
    if (n < 60) return `${n.toFixed(0)}s`;
    return `${(n / 60).toFixed(1)}m`;
  },

  _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};

window.Reliability = Reliability;
