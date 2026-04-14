/* ── Health alerts — Option L ─────────────────────────
 *
 * Polls /api/alerts every 15s. Keeps a badge in the topbar with the
 * current total count, pops a toast when a brand-new error shows up,
 * and exposes an expandable panel listing every active alert.
 *
 * The server returns a compact envelope:
 *
 *   { alerts: [{id, level, title, detail, adapter?, category?, ...}],
 *     counts: {error, warning, total}, timestamp: 1700000000.0 }
 *
 * Toasts only fire for *new* error ids since the last poll — the
 * warning list is expected to be noisy on a first-run box, so we
 * surface it passively via the badge + panel rather than interrupting.
 */

const Alerts = {
  _interval: 15000,
  _timer: null,
  _seenErrors: new Set(),
  _latest: { alerts: [], counts: { total: 0, error: 0, warning: 0 } },
  _inited: false,

  init() {
    if (this._inited) return;
    this._inited = true;

    const badge = document.getElementById('alerts-badge');
    const close = document.getElementById('alerts-panel-close');
    if (badge) badge.addEventListener('click', () => this._togglePanel());
    if (close) close.addEventListener('click', () => this._togglePanel(false));

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this._togglePanel(false);
    });

    // Initial fetch runs immediately; then we fall into the poll loop.
    this.refresh();
    this._timer = setInterval(() => this.refresh(), this._interval);
  },

  async refresh() {
    let data;
    try {
      const r = await fetch('/api/alerts');
      data = await r.json();
    } catch (e) {
      // Offline — keep the last-known counts so the badge doesn't flicker.
      return;
    }
    this._onData(data || {});
  },

  _onData(data) {
    const prev = this._latest;
    this._latest = data;

    // Toast any *new* errors since the previous poll.
    const nowErrors = (data.alerts || []).filter(a => a.level === 'error');
    for (const a of nowErrors) {
      if (!this._seenErrors.has(a.id)) {
        this._seenErrors.add(a.id);
        this._toast(a);
      }
    }
    // Drop ids that are no longer active so a re-occurrence toasts again.
    const activeIds = new Set(nowErrors.map(a => a.id));
    for (const id of Array.from(this._seenErrors)) {
      if (!activeIds.has(id)) this._seenErrors.delete(id);
    }

    this._renderBadge(data);
    if (!document.getElementById('alerts-panel').hasAttribute('hidden')) {
      this._renderPanel(data);
    }
    // Keep prev referenced just so linters don't complain about unused.
    void prev;
  },

  _renderBadge(data) {
    const badge = document.getElementById('alerts-badge');
    const count = document.getElementById('alerts-count');
    if (!badge || !count) return;
    const total = (data.counts && data.counts.total) || 0;
    const errors = (data.counts && data.counts.error) || 0;
    count.textContent = String(total);
    badge.classList.toggle('has-error', errors > 0);
    badge.classList.toggle('has-warning', errors === 0 && total > 0);
    badge.classList.toggle('clear', total === 0);
  },

  _togglePanel(force) {
    const panel = document.getElementById('alerts-panel');
    if (!panel) return;
    const shouldShow = force !== undefined
      ? force
      : panel.hasAttribute('hidden');
    if (shouldShow) {
      panel.removeAttribute('hidden');
      this._renderPanel(this._latest);
    } else {
      panel.setAttribute('hidden', '');
    }
  },

  _renderPanel(data) {
    const body = document.getElementById('alerts-panel-body');
    if (!body) return;
    const alerts = data.alerts || [];
    if (!alerts.length) {
      body.innerHTML = `
        <div class="empty-state muted">
          All clear — every configured adapter is online.
        </div>`;
      return;
    }
    body.innerHTML = alerts.map(a => `
      <div class="alert-row alert-${this._esc(a.level)}">
        <div class="alert-row-head">
          <span class="alert-level">${this._esc(a.level)}</span>
          <span class="alert-title">${this._esc(a.title)}</span>
        </div>
        ${a.detail ? `<div class="alert-detail muted">${this._esc(a.detail)}</div>` : ''}
        ${a.category ? `<div class="alert-meta muted">category: <code>${this._esc(a.category)}</code></div>` : ''}
      </div>
    `).join('');
  },

  _toast(alert) {
    // Zero-dep toast — mount a node, animate in via CSS class, auto-dismiss.
    const host = this._toastHost();
    const div = document.createElement('div');
    div.className = 'toast toast-error';
    div.innerHTML = `
      <div class="toast-head">⚠ ${this._esc(alert.title)}</div>
      <div class="toast-body muted">${this._esc(alert.detail || '')}</div>
    `;
    host.appendChild(div);
    // Force a reflow so the transition animates from the hidden state.
    void div.offsetHeight;
    div.classList.add('show');
    setTimeout(() => {
      div.classList.remove('show');
      setTimeout(() => div.remove(), 300);
    }, 7000);
  },

  _toastHost() {
    let host = document.getElementById('toast-host');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'toast-host';
    host.className = 'toast-host';
    document.body.appendChild(host);
    return host;
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
};

document.addEventListener('DOMContentLoaded', () => Alerts.init());

window.Alerts = Alerts;
