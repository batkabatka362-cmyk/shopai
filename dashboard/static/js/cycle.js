/* ── Cycles tab ─────────────────────────────────────
 *
 * Reads /api/cycle (AutoScheduler-backed) and renders:
 *   • metrics row: cycles run, last duration, errors, hooks-fired
 *   • latest cycle hero card
 *   • 4 adapter-hook cards (analytics, crm, helpdesk, automation)
 *   • recent 20-cycle history table
 *
 * Auto-refreshes every 5s while the tab is visible.
 */

const Cycle = {
  _timer: null,

  async refresh() {
    const data = await App.fetch('/api/cycle');
    this.render(data || {});
    // Keep a gentle poll going while the tab is active.
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'cycle') return;
      const fresh = await App.fetch('/api/cycle');
      this.render(fresh || {});
    }, 5000);
  },

  render(data) {
    this._renderMetrics(data);
    this._renderLatest(data);
    this._renderHooks(data);
    this._renderHistory(data);
  },

  _renderMetrics(data) {
    const el = document.getElementById('cycle-metrics');
    if (!el) return;
    const sched = data.scheduler || {};
    const latest = data.latest || {};
    const hooks = (latest.adapter_hooks || {});
    const hooksFired = ['analytics', 'crm', 'helpdesk', 'automation']
      .filter(k => this._hookFired(hooks[k])).length;
    const errTone = (latest.phase_error_count || 0) > 0 ? 'red' : 'green';

    el.innerHTML = [
      this._metric('Cycles Run', sched.cycles_run ?? 0, 'accent',
        sched.running ? 'scheduler running' : 'scheduler idle'),
      this._metric('Last Duration',
        latest.duration_s != null ? `${Number(latest.duration_s).toFixed(2)}s` : '—',
        'purple'),
      this._metric('Phase Errors', latest.phase_error_count ?? 0, errTone),
      this._metric('Hooks Fired', `${hooksFired}/4`, 'orange'),
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

  _renderLatest(data) {
    const el = document.getElementById('cycle-latest');
    const badge = document.getElementById('cycle-latest-badge');
    if (!el) return;
    const l = data.latest;
    if (!l || !data.has_data) {
      el.innerHTML = `
        <div class="empty-state">
          <p>No cycle has run yet.</p>
          <p class="muted">
            Start the scheduler or run a single cycle:<br>
            <code>from core.system.auto_scheduler import get_scheduler<br>
            get_scheduler().run_once("your-store")</code>
          </p>
        </div>`;
      if (badge) badge.textContent = 'idle';
      return;
    }
    if (badge) {
      badge.textContent = l.status || 'complete';
      badge.className = 'badge ' + (
        (l.phase_error_count || 0) > 0 ? 'badge-red' : 'badge-green');
    }
    el.innerHTML = `
      <div class="cycle-hero">
        <div class="cycle-hero-head">
          <span class="cycle-id">${this._esc(l.cycle_id)}</span>
          <span class="cycle-store">${this._esc(l.store_id)}</span>
        </div>
        <div class="cycle-stats">
          ${this._stat('Duration', `${Number(l.duration_s || 0).toFixed(2)}s`)}
          ${this._stat('Products', l.products ?? 0)}
          ${this._stat('Orders', l.orders ?? 0)}
          ${this._stat('Customers', l.customers ?? 0)}
          ${this._stat('Insights', l.insights ?? 0)}
          ${this._stat('Actions', l.actions_proposed ?? 0)}
        </div>
        ${l.top_action ? `
          <div class="cycle-action">
            <span class="muted">Top action:</span>
            <strong>${this._esc(l.top_action)}</strong>
          </div>` : ''}
        ${(l.phase_error_count || 0) > 0 ? `
          <div class="cycle-errors">
            <strong>${l.phase_error_count} phase error(s)</strong>
            <ul>${Object.entries(l.phase_errors || {}).map(
              ([p, e]) => `<li><code>${this._esc(p)}</code>: ${this._esc(String(e).slice(0, 160))}</li>`
            ).join('')}</ul>
          </div>` : ''}
      </div>`;
  },

  _stat(label, value) {
    return `<div class="cycle-stat"><span class="muted">${label}</span><strong>${value}</strong></div>`;
  },

  _renderHooks(data) {
    const el = document.getElementById('cycle-hooks');
    if (!el) return;
    const hooks = (data.latest && data.latest.adapter_hooks) || {};
    if (!hooks.enabled && Object.keys(hooks).length <= 1) {
      el.innerHTML = `<div class="empty-state muted">
        Adapter hooks are disabled or no cycle has run yet.<br>
        Set <code>SHOPAI_ADAPTER_HOOKS=on</code> (default) and
        configure at least one analytics / CRM / helpdesk / automation
        adapter to see activity here.
      </div>`;
      return;
    }
    el.innerHTML = `
      <div class="hook-grid">
        ${this._hookCard('Analytics', hooks.analytics, this._analyticsDetail)}
        ${this._hookCard('CRM', hooks.crm, this._crmDetail)}
        ${this._hookCard('Helpdesk', hooks.helpdesk, this._helpdeskDetail)}
        ${this._hookCard('Automation', hooks.automation, this._automationDetail)}
      </div>`;
  },

  _hookFired(hook) {
    if (!hook) return false;
    if (hook.cycle_event && hook.cycle_event.ok) return true;
    if (hook.synced > 0) return true;
    if (hook.created) return true;
    if (hook.triggered) return true;
    return false;
  },

  _hookCard(name, hook, detailFn) {
    const fired = this._hookFired(hook);
    const tone = fired ? 'green' : (hook && hook.error ? 'red' : 'muted');
    const body = hook ? detailFn(hook) : '<span class="muted">—</span>';
    return `
      <div class="hook-card hook-${tone}">
        <div class="hook-head">
          <span>${name}</span>
          <span class="hook-state">${fired ? 'fired' : (hook && hook.error ? 'error' : 'idle')}</span>
        </div>
        <div class="hook-body">${body}</div>
      </div>`;
  },

  _analyticsDetail(h) {
    const c = h.cycle_event || {};
    return `
      <div>Cycle event: <strong>${c.ok ? 'ok' : 'skipped'}</strong></div>
      <div>Order events: <strong>${h.order_events ?? 0}</strong></div>
      ${c.adapter ? `<div class="muted">via ${c.adapter}</div>` : ''}`;
  },
  _crmDetail(h) {
    return `
      <div>Synced: <strong>${h.synced ?? 0}</strong></div>
      <div>Skipped: <strong>${h.skipped ?? 0}</strong></div>`;
  },
  _helpdeskDetail(h) {
    if (h.created) return `<div>Ticket opened ✓</div><div class="muted">${h.adapter || ''}</div>`;
    return `<div>No ticket</div><div class="muted">${h.reason || ''}</div>`;
  },
  _automationDetail(h) {
    if (h.triggered) return `<div>Webhook triggered ✓</div><div class="muted">${h.adapter || ''}</div>`;
    return `<div>Not triggered</div><div class="muted">${h.reason || ''}</div>`;
  },

  _renderHistory(data) {
    const el = document.getElementById('cycle-history');
    if (!el) return;
    const rows = (data.recent || []).slice().reverse();
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state muted">No history yet.</div>`;
      return;
    }
    el.innerHTML = `
      <table class="cycle-table">
        <thead>
          <tr>
            <th>When</th><th>Cycle</th><th>Store</th>
            <th>Dur</th><th>Errs</th><th>Actions</th><th>Top</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr class="${(r.phase_error_count || 0) > 0 ? 'row-error' : ''}">
              <td class="muted">${this._relTime(r.timestamp)}</td>
              <td><code>${this._esc((r.cycle_id || '').slice(-10))}</code></td>
              <td>${this._esc(r.store_id || '')}</td>
              <td>${Number(r.duration_s || 0).toFixed(1)}s</td>
              <td>${r.phase_error_count || 0}</td>
              <td>${r.actions_proposed || 0}</td>
              <td class="muted">${this._esc(r.top_action || '')}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
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

window.Cycle = Cycle;
