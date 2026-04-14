/* ── Feedback review tab — Option O ──────────────────
 *
 * Polls /api/feedback on entry and every 15s while the tab is visible.
 * Renders:
 *   • four metric cards: total, good, bad, good-rate
 *   • good/bad ratio bar with percentage
 *   • recurring-complaint themes (word-count chips)
 *   • configuration panel (vault path + setup hint)
 *   • recent feedback list with rating pills + excerpts
 *
 * The endpoint never 500s — a missing/unconfigured vault reports
 * ``configured: false`` and we render an onboarding card instead.
 */

const Feedback = {
  _timer: null,

  async refresh() {
    const [data, lessons] = await Promise.all([
      App.fetch('/api/feedback'),
      App.fetch('/api/lessons'),
    ]);
    this.render(data || {}, lessons || {});
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(async () => {
      if (App.currentTab !== 'feedback') return;
      const [fresh, lf] = await Promise.all([
        App.fetch('/api/feedback'),
        App.fetch('/api/lessons'),
      ]);
      this.render(fresh || {}, lf || {});
    }, 15000);
  },

  render(data, lessons) {
    this._renderMetrics(data);
    this._renderRatio(data);
    this._renderThemes(data);
    this._renderConfig(data);
    this._renderRecent(data);
    this._renderLessons(lessons || {});
    const pathEl = document.getElementById('feedback-path');
    if (pathEl) {
      pathEl.textContent = data.path ? this._esc(data.path) : '';
    }
  },

  _renderLessons(data) {
    const el = document.getElementById('lessons-body');
    const countEl = document.getElementById('lessons-count');
    if (!el) return;
    const rows = data.lessons || [];
    if (countEl) countEl.textContent = String(rows.length);
    if (!rows.length) {
      // Leave the default empty-state hint from the HTML in place.
      return;
    }
    el.innerHTML = `
      <ul class="lesson-list">
        ${rows.map(r => `
          <li class="lesson-item">
            <div class="lesson-head">
              <span class="lesson-theme">${this._esc(r.theme || r.title)}</span>
              <span class="lesson-count">×${r.source_count}</span>
              <span class="muted">updated ${this._esc(r.updated || '—')}</span>
            </div>
            <div class="lesson-body muted">
              Flagged by ${(r.sources || []).length} feedback note(s).
              Injected into chat context when the theme appears in a
              user message.
            </div>
            ${(r.sources || []).length ? `
              <details class="lesson-sources">
                <summary class="muted">sources</summary>
                <ul>
                  ${r.sources.map(s => `<li><code>${this._esc(s)}</code></li>`).join('')}
                </ul>
              </details>
            ` : ''}
          </li>`).join('')}
      </ul>`;
  },

  // ── Metric cards ──────────────────────────────────

  _renderMetrics(data) {
    const el = document.getElementById('feedback-metrics');
    if (!el) return;
    const total = data.total || 0;
    const good = data.good || 0;
    const bad = data.bad || 0;
    const rate = (data.good_rate || 0) * 100;
    const rateTone = rate >= 80 ? 'green'
                    : rate >= 50 ? 'orange'
                    : total === 0 ? 'accent' : 'red';
    el.innerHTML = [
      this._metric('Total Feedback', total, 'accent',
        total === 0 ? 'no ratings yet' : 'rated messages'),
      this._metric('Good', good, 'green', good === 1 ? 'thumbs up' : 'thumbs up'),
      this._metric('Bad', bad, bad > 0 ? 'red' : 'accent',
        bad === 1 ? 'thumbs down' : 'thumbs down'),
      this._metric('Good Rate', `${rate.toFixed(1)}%`, rateTone,
        total === 0 ? '—' : `of ${total}`),
    ].join('');
  },

  _metric(label, value, tone = 'accent', sub = '') {
    return `
      <div class="metric-card ${tone}">
        <div class="metric-label">${this._esc(label)}</div>
        <div class="metric-value">${this._esc(value)}</div>
        ${sub ? `<div class="metric-sub">${this._esc(sub)}</div>` : ''}
      </div>`;
  },

  // ── Good/bad ratio bar ───────────────────────────

  _renderRatio(data) {
    const el = document.getElementById('feedback-ratio');
    const badge = document.getElementById('feedback-ratio-badge');
    if (!el) return;
    const good = data.good || 0;
    const bad = data.bad || 0;
    const total = good + bad;
    if (total === 0) {
      el.innerHTML = `<div class="empty-state muted">
        No ratings collected yet. Operators can tap thumbs up/down on
        any assistant reply to file a feedback note.
      </div>`;
      if (badge) { badge.textContent = 'idle'; badge.className = 'badge'; }
      return;
    }
    const goodPct = (good / total) * 100;
    const badPct = 100 - goodPct;
    el.innerHTML = `
      <div class="feedback-ratio-bar">
        <div class="feedback-ratio-good" style="width:${goodPct.toFixed(1)}%"
             title="${good} good">${goodPct >= 12 ? good : ''}</div>
        <div class="feedback-ratio-bad" style="width:${badPct.toFixed(1)}%"
             title="${bad} bad">${badPct >= 12 ? bad : ''}</div>
      </div>
      <div class="feedback-ratio-legend">
        <span class="dot dot-good"></span>
        <span>${good} good (${goodPct.toFixed(1)}%)</span>
        <span class="dot dot-bad"></span>
        <span>${bad} bad (${badPct.toFixed(1)}%)</span>
      </div>`;
    if (badge) {
      const tone = goodPct >= 80 ? 'badge-green'
                 : goodPct >= 50 ? 'badge-orange' : 'badge-red';
      badge.textContent = `${goodPct.toFixed(0)}% good`;
      badge.className = 'badge ' + tone;
    }
  },

  // ── Complaint themes ──────────────────────────────

  _renderThemes(data) {
    const el = document.getElementById('feedback-themes');
    if (!el) return;
    const themes = data.themes || [];
    if (!themes.length) {
      el.innerHTML = `<div class="empty-state muted">
        No recurring complaint themes yet. Themes appear once the same
        word shows up in two or more operator notes on "bad" ratings.
      </div>`;
      return;
    }
    el.innerHTML = `
      <div class="feedback-themes">
        ${themes.map(t => `
          <span class="feedback-theme">
            <strong>${this._esc(t.word)}</strong>
            <span class="muted">×${t.count}</span>
          </span>`).join('')}
      </div>`;
  },

  // ── Config / setup panel ──────────────────────────

  _renderConfig(data) {
    const el = document.getElementById('feedback-config');
    if (!el) return;
    if (data.configured === false) {
      el.innerHTML = `
        <div class="empty-state">
          <p><strong>Vault not configured.</strong></p>
          <p class="muted">
            Set <code>OBSIDIAN_VAULT_PATH</code> in your environment so
            the chat feedback capture can write notes under
            <code>ShopAI/Feedback/</code>.
          </p>
        </div>`;
      return;
    }
    const err = data.error
      ? `<div class="feedback-config-err">last error: ${this._esc(data.error)}</div>`
      : '';
    el.innerHTML = `
      <div class="feedback-config-body">
        <div>
          <span class="muted">Feedback folder:</span>
          <code>${this._esc(data.path || '—')}</code>
        </div>
        <div class="muted">
          Operators file feedback from the Assistant tab — each thumb
          tap writes one markdown note with the user message, the
          assistant reply, and an optional operator note.
        </div>
        ${err}
      </div>`;
  },

  // ── Recent feedback list ──────────────────────────

  _renderRecent(data) {
    const el = document.getElementById('feedback-recent');
    const countEl = document.getElementById('feedback-recent-count');
    if (!el) return;
    const rows = data.recent || [];
    if (countEl) countEl.textContent = String(rows.length);
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state muted">No feedback yet.</div>`;
      return;
    }
    el.innerHTML = `
      <ul class="feedback-list">
        ${rows.map(r => `
          <li class="feedback-item feedback-${this._esc(r.rating)}">
            <div class="feedback-head">
              <span class="feedback-pill feedback-pill-${this._esc(r.rating)}">
                ${r.rating === 'up' ? '👍' : '👎'} ${this._esc(r.rating)}
              </span>
              <span class="feedback-title">${this._esc(r.title)}</span>
              <span class="muted">${this._relTime(r.mtime)}</span>
            </div>
            ${r.excerpt ? `
              <div class="feedback-excerpt">${this._esc(r.excerpt)}</div>
            ` : ''}
            <div class="feedback-path muted">${this._esc(r.path)}</div>
          </li>`).join('')}
      </ul>`;
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
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
};

window.Feedback = Feedback;
