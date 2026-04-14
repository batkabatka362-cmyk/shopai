/* ── Cost Tracker tab — Option M ─────────────────────
 *
 * Polls /api/cost on entry and every 10s while the tab is visible.
 * Renders:
 *   • four metric cards: total spend, budget cap, % used, top spender
 *   • budget progress bar tinted by % (green → amber → red)
 *   • category totals as a horizontal bar list
 *   • per-adapter table sorted by cost desc
 *
 * The API always returns a well-formed envelope, so every renderer
 * treats "no data" as a normal empty state rather than an error.
 */

const Cost = {
  _timer: null,

  async refresh() {
    const [cost, budget, attribution] = await Promise.all([
      App.fetch('/api/cost'),
      App.fetch('/api/budget'),
      App.fetch('/api/cost-attribution'),
    ]);
    this.render(cost || {}, budget || {}, attribution || {});
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'cost') return;
      const [c, b, a] = await Promise.all([
        App.fetch('/api/cost'),
        App.fetch('/api/budget'),
        App.fetch('/api/cost-attribution'),
      ]);
      this.render(c || {}, b || {}, a || {});
    }, 10000);
  },

  render(data, budget, attribution) {
    this._renderMetrics(data);
    this._renderBudget(data);
    this._renderCategories(data);
    this._renderTopSpenders(data);
    this._renderTable(data);
    this._renderBudgetCaps(budget || {});
    this._renderAttribution(attribution || {});
    const stamp = document.getElementById('cost-timestamp');
    if (stamp) {
      stamp.textContent = data.timestamp
        ? `updated ${this._relTime(data.timestamp)}`
        : '';
    }
  },

  _renderAttribution(data) {
    const body = document.getElementById('cost-attribution');
    const badge = document.getElementById('cost-attribution-badge');
    const perCaller = data.per_caller || [];
    const rows = data.rows || [];
    const total = Number(data.total_usd || 0);
    const overflow = data.overflow || {active: false};
    if (badge) {
      if (!perCaller.length) {
        badge.textContent = 'no data';
        badge.className = 'badge badge-gray';
      } else {
        const top = perCaller[0];
        badge.textContent = `$${total.toFixed(4)} · top ${top.caller}`;
        badge.className = 'badge badge-green';
      }
    }
    if (!body) return;
    if (!perCaller.length) {
      body.innerHTML = `<div class="empty-state muted">
        No caller-tagged cost recorded yet. Pass
        <code>RouteContext(caller="&lt;name&gt;")</code> when calling
        the router so spend gets attributed to its originating
        subsystem.
      </div>`;
      return;
    }
    const overflowBanner = overflow.active
      ? `<div class="dl-warn muted">
           ⚠ overflow bucket active: ${overflow.calls} call(s) · $${Number(overflow.usd || 0).toFixed(6)}
           folded because ${data.key_count}/${data.max_keys} unique
           tags hit the cap. A buggy caller is likely generating
           per-request tags — switch to a stable caller name.
         </div>`
      : '';
    const callerItems = perCaller.map(c => {
      const pct = total > 0 ? (c.total_usd / total) * 100 : 0;
      return `
        <div class="attrib-row">
          <div class="attrib-head">
            <span class="attrib-name">${this._esc(c.caller)}</span>
            <span class="attrib-usd">$${Number(c.total_usd).toFixed(4)}</span>
            <span class="muted attrib-pct">${pct.toFixed(1)}%</span>
          </div>
          <div class="attrib-bar-track">
            <div class="attrib-bar-fill" style="width: ${pct.toFixed(1)}%"></div>
          </div>
          <div class="attrib-stats muted">
            ${c.calls || 0} calls · ${c.adapter_count || 0} adapter${(c.adapter_count || 0) === 1 ? '' : 's'}
            · ${(c.tokens_in || 0) + (c.tokens_out || 0)} tokens
          </div>
        </div>`;
    }).join('');
    // Drill-down table — top 20 rows by spend.
    const drilldown = rows.slice(0, 20).map(r => `
      <tr>
        <td>${this._esc(r.caller)}</td>
        <td>${this._esc(r.adapter)}</td>
        <td><code>${this._esc(r.capability)}</code></td>
        <td class="num">$${Number(r.total_usd).toFixed(6)}</td>
        <td class="num">${r.calls || 0}</td>
      </tr>`).join('');
    const table = rows.length
      ? `<table class="attrib-table">
           <thead>
             <tr>
               <th>Caller</th><th>Adapter</th><th>Capability</th>
               <th class="num">Spend</th><th class="num">Calls</th>
             </tr>
           </thead>
           <tbody>${drilldown}</tbody>
         </table>`
      : '';
    body.innerHTML = overflowBanner
      + `<div class="attrib-list">${callerItems}</div>`
      + table;
  },

  _renderBudgetCaps(data) {
    const body = document.getElementById('budget-rows');
    const badge = document.getElementById('budget-badge');
    const rows = data.rows || [];
    const totals = data.totals || {};
    if (badge) {
      const exceeded = totals.exceeded || 0;
      const warn = totals.warn || 0;
      const ok = totals.ok || 0;
      const label = `${exceeded} over · ${warn} warn · ${ok} ok`;
      badge.textContent = label;
      badge.className = 'badge ' + (
        exceeded > 0 ? 'badge-red'
        : warn > 0 ? 'badge-orange'
        : 'badge-green'
      );
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No budget caps declared. Configure per-adapter
        <code>CostBudget(daily_usd, monthly_usd)</code> to enable
        hard-stop enforcement.
      </div>`;
      return;
    }
    const items = rows.map(r => {
      const status = r.status || 'unconfigured';
      const cls = status === 'exceeded' ? 'badge-red'
        : status === 'warn' ? 'badge-orange'
        : status === 'ok' ? 'badge-green'
        : 'badge-gray';
      const budget = r.budget || {};
      const dailyPct = r.daily_used_pct;
      const monthlyPct = r.monthly_used_pct;
      const dailyBar = dailyPct === null
        ? '<span class="muted">no daily cap</span>'
        : this._bar(dailyPct, r.spent_daily_usd, budget.daily_usd, 'daily');
      const monthlyBar = monthlyPct === null
        ? '<span class="muted">no monthly cap</span>'
        : this._bar(monthlyPct, r.spent_monthly_usd, budget.monthly_usd, 'monthly');
      return `
        <div class="budget-row">
          <div class="budget-name">
            <div>${this._esc(r.adapter)}</div>
            <span class="badge ${cls}">${this._esc(status)}</span>
          </div>
          <div class="budget-bars">
            ${dailyBar}
            ${monthlyBar}
          </div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="budget-list">${items}</div>`;
  },

  _bar(pct, spent, cap, label) {
    const pctLabel = `${Math.round((pct || 0) * 100)}%`;
    const fillCls = pct >= 1 ? 'budget-fill-red'
      : pct >= 0.8 ? 'budget-fill-orange'
      : 'budget-fill-green';
    return `
      <div class="budget-bar">
        <div class="budget-bar-label">
          <span>${this._esc(label)}</span>
          <span class="muted">
            $${(spent || 0).toFixed(2)} / $${(cap || 0).toFixed(2)}
            (${pctLabel})
          </span>
        </div>
        <div class="budget-bar-track">
          <div class="budget-bar-fill ${fillCls}"
               style="width: ${Math.min(100, (pct || 0) * 100)}%"></div>
        </div>
      </div>`;
  },

  // ── Metric cards ──────────────────────────────────

  _renderMetrics(data) {
    const el = document.getElementById('cost-metrics');
    if (!el) return;
    const total = data.total_usd || 0;
    const budget = data.budget || {};
    const cap = budget.cap_usd || 0;
    const pct = budget.pct_used || 0;
    const tone = pct >= 100 ? 'red' : pct >= 75 ? 'orange' : 'green';
    el.innerHTML = [
      this._metric('Total Spend', this._money(total), 'accent',
        (data.per_adapter || []).length + ' adapter(s)'),
      this._metric('Budget Cap', cap ? this._money(cap) : '—', 'accent',
        'per month'),
      this._metric('% Used', `${pct.toFixed(1)}%`, tone,
        budget.over_budget ? 'over budget' : 'on track'),
      this._metric('Top Spender', data.top_spender || '—', 'orange',
        data.top_spender ? this._money(this._topCost(data)) : 'no spend yet'),
    ].join('');
  },

  _topCost(data) {
    const rows = data.per_adapter || [];
    return rows.length ? rows[0].cost_usd : 0;
  },

  _metric(label, value, tone = 'accent', sub = '') {
    return `
      <div class="metric-card ${tone}">
        <div class="metric-label">${this._esc(label)}</div>
        <div class="metric-value">${this._esc(value)}</div>
        ${sub ? `<div class="metric-sub">${this._esc(sub)}</div>` : ''}
      </div>`;
  },

  // ── Budget bar ────────────────────────────────────

  _renderBudget(data) {
    const el = document.getElementById('cost-budget');
    const badge = document.getElementById('cost-budget-badge');
    if (!el) return;
    const budget = data.budget || {};
    const pct = Math.min(100, budget.pct_used || 0);
    const cap = budget.cap_usd || 0;
    const spent = budget.spent_usd || 0;
    const tone = pct >= 100 ? 'red' : pct >= 75 ? 'orange' : 'green';
    if (badge) {
      badge.textContent = budget.over_budget ? 'over' : `${pct.toFixed(1)}%`;
    }
    if (!cap) {
      el.innerHTML = `
        <div class="empty-state muted">
          No budget cap configured.
          Set <code>SHOPAI_MONTHLY_BUDGET_USD</code> to enable the progress bar.
        </div>`;
      return;
    }
    el.innerHTML = `
      <div class="cost-budget-row">
        <span>${this._money(spent)}</span>
        <span class="muted">of ${this._money(cap)}</span>
      </div>
      <div class="cost-bar">
        <div class="cost-bar-fill cost-bar-${tone}"
             style="width:${pct}%"></div>
      </div>
      <div class="cost-budget-foot muted">
        ${budget.over_budget
          ? '⚠ Over budget — review which adapter is bleeding.'
          : `${(100 - pct).toFixed(1)}% remaining this window.`}
      </div>`;
  },

  // ── Category rollup ───────────────────────────────

  _renderCategories(data) {
    const el = document.getElementById('cost-categories');
    if (!el) return;
    const cats = data.per_category || {};
    const entries = Object.entries(cats).filter(([, v]) => v > 0);
    if (!entries.length) {
      el.innerHTML = `<div class="empty-state muted">No spend yet.</div>`;
      return;
    }
    const max = Math.max(...entries.map(([, v]) => v));
    el.innerHTML = entries.map(([cat, usd]) => {
      const pct = max > 0 ? (usd / max) * 100 : 0;
      return `
        <div class="cost-cat-row">
          <div class="cost-cat-label">${this._esc(cat)}</div>
          <div class="cost-cat-bar">
            <div class="cost-cat-fill" style="width:${pct}%"></div>
          </div>
          <div class="cost-cat-value">${this._money(usd)}</div>
        </div>`;
    }).join('');
  },

  // ── Top spenders column ──────────────────────────

  _renderTopSpenders(data) {
    const el = document.getElementById('cost-top');
    if (!el) return;
    const rows = (data.per_adapter || [])
      .filter(r => r.cost_usd > 0).slice(0, 5);
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state muted">No paid calls yet.</div>`;
      return;
    }
    el.innerHTML = rows.map(r => `
      <div class="cost-top-row">
        <div>
          <div class="cost-top-name">${this._esc(r.name)}</div>
          <div class="muted cost-top-meta">
            ${this._esc(r.category)} · ${r.calls} call${r.calls === 1 ? '' : 's'}
          </div>
        </div>
        <div class="cost-top-value">${this._money(r.cost_usd)}</div>
      </div>`).join('');
  },

  // ── Per-adapter table ─────────────────────────────

  _renderTable(data) {
    const el = document.getElementById('cost-table');
    if (!el) return;
    const rows = data.per_adapter || [];
    if (!rows.length) {
      el.innerHTML = `
        <div class="empty-state muted">
          No adapters registered yet.
        </div>`;
      return;
    }
    el.innerHTML = `
      <table class="cost-table">
        <thead>
          <tr>
            <th>Adapter</th>
            <th>Category</th>
            <th class="num">Calls</th>
            <th class="num">Cost</th>
            <th class="num">Avg / call</th>
            <th class="num">Tokens</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td>${this._esc(r.name)}</td>
              <td class="muted">${this._esc(r.category)}</td>
              <td class="num">${r.calls}</td>
              <td class="num">${this._money(r.cost_usd)}</td>
              <td class="num">${r.calls > 0 ? this._money(r.avg_cost_usd) : '—'}</td>
              <td class="num muted">${(r.tokens_in || 0) + (r.tokens_out || 0)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  },

  // ── Helpers ──────────────────────────────────────

  _money(v) {
    if (v == null || isNaN(v)) return '$0.00';
    const n = Number(v);
    if (n === 0) return '$0.00';
    if (n < 0.01) return '$' + n.toFixed(6);
    if (n < 1) return '$' + n.toFixed(4);
    return '$' + n.toFixed(2);
  },

  _relTime(ts) {
    if (!ts) return '';
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  },

  _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
};

window.Cost = Cost;
