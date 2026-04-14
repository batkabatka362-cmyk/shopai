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
    const [retries, sla, rate, idem, health, dl] = await Promise.all([
      App.fetch('/api/retries'),
      App.fetch('/api/sla'),
      App.fetch('/api/ratelimit'),
      App.fetch('/api/idempotency'),
      App.fetch('/api/adapter-health'),
      App.fetch('/api/deadletter'),
    ]);
    this.render(
      retries || {}, sla || {}, rate || {}, idem || {}, health || {},
      dl || {},
    );
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'reliability') return;
      const [fr, fs, frl, fi, fh, fdl] = await Promise.all([
        App.fetch('/api/retries'),
        App.fetch('/api/sla'),
        App.fetch('/api/ratelimit'),
        App.fetch('/api/idempotency'),
        App.fetch('/api/adapter-health'),
        App.fetch('/api/deadletter'),
      ]);
      this.render(
        fr || {}, fs || {}, frl || {}, fi || {}, fh || {}, fdl || {},
      );
    }, 15000);
  },

  render(data, sla, rate, idem, health, dl) {
    this._renderMetrics(data.totals || {});
    this._renderHealth(health || {});
    this._renderBreakers(data.breakers || []);
    this._renderAdapters(data.per_adapter || []);
    this._renderSLA(sla || {});
    this._renderRateLimit(rate || {});
    this._renderIdempotency(idem || {});
    this._renderDeadletter(dl || {});
  },

  _renderDeadletter(dl) {
    const body = document.getElementById('reliability-deadletter');
    const badge = document.getElementById('reliability-deadletter-badge');
    const recent = dl.recent || [];
    const size = dl.size || 0;
    const writeFail = dl.write_failures || 0;
    if (badge) {
      if (size === 0) {
        badge.textContent = 'clean';
        badge.className = 'badge badge-green';
      } else {
        const perAdapter = dl.per_adapter || {};
        const top = Object.entries(perAdapter)
          .sort((a, b) => b[1] - a[1])[0];
        const topLabel = top ? ` · top ${top[0]} (${top[1]})` : '';
        badge.textContent = `${size} dropped${topLabel}`;
        badge.className = 'badge badge-red';
      }
    }
    if (!body) return;
    if (!recent.length) {
      body.innerHTML = `<div class="empty-state muted">
        No terminal failures recorded. Requests that fail every
        fallback will appear here with a redacted snapshot.
      </div>`;
      return;
    }
    const warn = writeFail > 0
      ? `<div class="dl-warn muted">
           ⚠ ${writeFail} disk write failure${writeFail === 1 ? '' : 's'} — in-memory only
         </div>`
      : '';
    const items = recent.map(e => {
      const ts = e.timestamp
        ? new Date(e.timestamp * 1000).toLocaleTimeString()
        : '—';
      const snap = e.params_snapshot || {};
      const snapChips = Object.entries(snap)
        .slice(0, 6)
        .map(([k, v]) =>
          `<span class="dl-chip">${this._esc(k)}=${this._esc(String(v))}</span>`)
        .join(' ');
      return `
        <div class="dl-row">
          <div class="dl-head">
            <span class="dl-adapter">${this._esc(e.adapter || '?')}</span>
            <span class="muted">·</span>
            <span class="dl-cap">${this._esc(e.capability || '?')}</span>
            <span class="badge badge-red">${this._esc(e.error_type || 'Error')}</span>
            <span class="muted dl-time">${this._esc(ts)}</span>
          </div>
          <div class="dl-msg muted">${this._esc(e.error_message || '')}</div>
          <div class="dl-meta muted">
            attempts ${e.attempts || 0} · hash ${this._esc((e.params_hash || '').slice(0, 10))}
          </div>
          ${snapChips ? `<div class="dl-snap">${snapChips}</div>` : ''}
        </div>`;
    }).join('');
    body.innerHTML = warn + `<div class="dl-feed">${items}</div>`;
  },

  _renderHealth(health) {
    const body = document.getElementById('reliability-health');
    const badge = document.getElementById('reliability-health-badge');
    const rows = health.rows || [];
    const totals = health.totals || {
      unhealthy: 0, degraded: 0, healthy: 0, unknown: 0,
    };
    if (badge) {
      const u = totals.unhealthy || 0;
      const d = totals.degraded || 0;
      const h = totals.healthy || 0;
      badge.textContent = `${u} down · ${d} degraded · ${h} healthy`;
      badge.className = 'badge ' + (
        u > 0 ? 'badge-red'
        : d > 0 ? 'badge-orange'
        : h > 0 ? 'badge-green'
        : 'badge-gray'
      );
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No telemetry yet. Health scores appear here once adapters
        have accumulated breaker / SLA / retry / rate-limit data.
      </div>`;
      return;
    }
    const items = rows.map(r => {
      const gradeCls = r.grade === 'unhealthy' ? 'badge-red'
        : r.grade === 'degraded' ? 'badge-orange'
        : r.grade === 'healthy' ? 'badge-green'
        : 'badge-gray';
      const pct = Math.round((r.score || 0) * 100);
      const comps = (r.components || []).map(c => {
        if (!c.available) {
          return `<span class="health-chip health-chip-muted">
            ${this._esc(c.name)}: <span class="muted">${this._esc(c.detail)}</span>
          </span>`;
        }
        const chipCls = c.score >= 0.8 ? 'health-chip-ok'
          : c.score >= 0.5 ? 'health-chip-warn'
          : 'health-chip-bad';
        return `<span class="health-chip ${chipCls}" title="${this._esc(c.detail)}">
          ${this._esc(c.name)}: ${Math.round(c.score * 100)}
        </span>`;
      }).join(' ');
      const barCls = r.grade === 'unhealthy' ? 'rate-fill-red'
        : r.grade === 'degraded' ? 'rate-fill-orange'
        : 'rate-fill-green';
      return `
        <div class="health-row">
          <div class="health-head">
            <div class="health-name">${this._esc(r.adapter)}</div>
            <span class="badge ${gradeCls}">${this._esc(r.grade)}</span>
            <div class="health-score muted">${pct}</div>
          </div>
          <div class="health-bar-track">
            <div class="health-bar-fill ${barCls}"
                 style="width: ${pct}%"></div>
          </div>
          <div class="health-comps">${comps}</div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="health-list">${items}</div>`;
  },

  _renderIdempotency(idem) {
    const body = document.getElementById('reliability-idempotency');
    const badge = document.getElementById('reliability-idempotency-badge');
    const counters = idem.counters || {
      hits: 0, misses: 0, stores: 0, evictions: 0, skipped: 0,
    };
    const rows = idem.rows || [];
    const hitRate = Number(idem.hit_rate || 0);
    if (badge) {
      const pct = Math.round(hitRate * 100);
      const lookups = (counters.hits || 0) + (counters.misses || 0);
      badge.textContent = lookups > 0
        ? `${pct}% hit · ${counters.hits || 0}/${lookups}`
        : 'no lookups yet';
      badge.className = 'badge ' + (
        lookups === 0 ? 'badge-gray'
        : hitRate >= 0.5 ? 'badge-green'
        : hitRate >= 0.2 ? 'badge-orange'
        : 'badge-red'
      );
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No capabilities have a cache policy registered. Enable one with
        <code>IdempotencyCache.set_policy(cap, IdempotencyPolicy(ttl_s=…))</code>
        or rely on the default catalog for CHAT_COMPLETE / EMBED_TEXT /
        WEB_SEARCH.
      </div>`;
      return;
    }
    const summary = `
      <div class="idem-summary">
        <span class="muted">
          ${counters.hits || 0} hits · ${counters.misses || 0} misses ·
          ${counters.stores || 0} stored · ${counters.evictions || 0} evicted ·
          ${counters.skipped || 0} skipped
        </span>
        <span class="muted">
          ${idem.live || 0} / ${idem.size || 0} live
          · cap ${idem.max_entries || 0}
        </span>
      </div>`;
    const items = rows.map(r => {
      const cls = r.enabled ? 'badge-green' : 'badge-gray';
      const ttl = r.ttl_s > 0 ? `${r.ttl_s.toFixed(0)}s ttl` : 'disabled';
      const scope = r.shared_across_adapters ? 'shared' : 'per-adapter';
      return `
        <div class="idem-row">
          <div class="idem-name">
            <div>${this._esc(r.capability)}</div>
            <span class="badge ${cls}">${this._esc(ttl)}</span>
          </div>
          <div class="idem-stats muted">
            ${r.live || 0} live · ${this._esc(scope)}
          </div>
        </div>`;
    }).join('');
    body.innerHTML = summary + `<div class="idem-list">${items}</div>`;
  },

  _renderRateLimit(rate) {
    const body = document.getElementById('reliability-ratelimit');
    const badge = document.getElementById('reliability-ratelimit-badge');
    const rows = rate.rows || [];
    const totals = rate.totals || {throttled: 0, near: 0, ok: 0, idle: 0};
    if (badge) {
      const t = totals.throttled || 0;
      const n = totals.near || 0;
      const o = totals.ok || 0;
      badge.textContent = `${t} throttled · ${n} near · ${o} ok`;
      badge.className = 'badge ' + (
        t > 0 ? 'badge-red'
        : n > 0 ? 'badge-orange'
        : 'badge-green'
      );
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No adapters have a rate-limit policy registered. Register one
        with <code>RateLimiter.set_policy(adapter, RateLimit(…))</code>
        or rely on the default catalog for common vendors.
      </div>`;
      return;
    }
    const items = rows.map(r => {
      const cls = r.status === 'throttled' ? 'badge-red'
        : r.status === 'near' ? 'badge-orange'
        : r.status === 'ok' ? 'badge-green'
        : 'badge-gray';
      const pol = r.policy || {};
      const minutePart = pol.requests_per_min
        ? this._bar(r.minute_used_pct, r.tokens_min, pol.requests_per_min, 'per min')
        : '<span class="muted">no per-minute cap</span>';
      const hourPart = pol.requests_per_hour
        ? this._bar(r.hour_used_pct, r.tokens_hour, pol.requests_per_hour, 'per hour')
        : '<span class="muted">no per-hour cap</span>';
      const conc = pol.concurrent
        ? `<span class="muted">in-flight ${r.in_flight || 0} / ${pol.concurrent}</span>`
        : '';
      return `
        <div class="rate-row">
          <div class="rate-name">
            <div>${this._esc(r.adapter)}</div>
            <span class="badge ${cls}">${this._esc(r.status)}</span>
          </div>
          <div class="rate-bars">
            ${minutePart}
            ${hourPart}
            ${conc}
          </div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="rate-list">${items}</div>`;
  },

  _bar(pct, tokens, cap, label) {
    const p = Math.max(0, Math.min(1, Number(pct) || 0));
    const pctLabel = `${Math.round(p * 100)}%`;
    const fillCls = p >= 1 ? 'rate-fill-red'
      : p >= 0.8 ? 'rate-fill-orange'
      : 'rate-fill-green';
    const used = Math.max(0, Math.round((cap || 0) - (Number(tokens) || 0)));
    return `
      <div class="rate-bar">
        <div class="rate-bar-label">
          <span>${this._esc(label)}</span>
          <span class="muted">${used} / ${cap || 0} used (${pctLabel})</span>
        </div>
        <div class="rate-bar-track">
          <div class="rate-bar-fill ${fillCls}"
               style="width: ${(p * 100).toFixed(1)}%"></div>
        </div>
      </div>`;
  },

  _renderSLA(sla) {
    const body = document.getElementById('reliability-sla');
    const badge = document.getElementById('reliability-sla-badge');
    const rows = sla.rows || [];
    const totals = sla.totals || {breach: 0, warn: 0, ok: 0};
    if (badge) {
      const label = `${totals.breach || 0} breach · ${totals.warn || 0} warn · ${totals.ok || 0} ok`;
      badge.textContent = label;
      badge.className = 'badge ' + (
        totals.breach > 0 ? 'badge-red'
        : totals.warn > 0 ? 'badge-orange'
        : 'badge-green'
      );
    }
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<div class="empty-state muted">
        No adapter calls yet. SLA grades appear once adapters have
        accumulated enough samples to meet the monitor's
        min-samples threshold.
      </div>`;
      return;
    }
    const items = rows.map(r => {
      const grade = r.evaluated ? r.grade : 'warming';
      const cls = grade === 'breach' ? 'badge-red'
        : grade === 'warn' ? 'badge-orange'
        : grade === 'ok' ? 'badge-green'
        : 'badge-gray';
      const label = r.evaluated ? grade : 'warming up';
      const detail = r.evaluated
        ? (r.violations.length
            ? r.violations.join(' · ')
            : (r.warnings.length
                ? r.warnings.join(' · ')
                : `p95 ${Math.round(r.p95_ms)}ms · p99 ${Math.round(r.p99_ms)}ms · ${Math.round((r.success_rate||0)*100)}% ok`))
        : `${r.samples || 0} samples — need more data`;
      return `
        <div class="sla-row">
          <div class="sla-name">${this._esc(r.adapter)}</div>
          <div class="sla-grade">
            <span class="badge ${cls}">${this._esc(label)}</span>
          </div>
          <div class="sla-detail muted">${this._esc(detail)}</div>
        </div>`;
    }).join('');
    body.innerHTML = `<div class="sla-list">${items}</div>`;
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
