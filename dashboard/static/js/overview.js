/* ── Tab 1: Command Center ─────────────────────────── */

const Overview = {
  render(data) {
    if (!data) return;
    this.renderMetrics(data);
    this.renderAdapters(data.adapters || {});
    this.renderHealth(data.system || {});
  },

  renderMetrics(data) {
    const adapters = data.adapters || {};
    const system = data.system || {};
    const metrics = data.metrics || {};

    const total = adapters.total || 0;
    const configured = adapters.configured || 0;
    const categories = Object.keys(adapters.categories || {}).length;
    const status = (system.status || 'unknown').toUpperCase();
    const statusClass = status === 'HEALTHY' ? 'green' : status === 'DEGRADED' ? 'yellow' : 'red';
    const tasks = metrics.tasks || {};

    document.getElementById('overview-metrics').innerHTML = `
      <div class="metric-card accent">
        <div class="metric-label">Total Adapters</div>
        <div class="metric-value">${total}</div>
        <div class="metric-sub">${categories} categories registered</div>
      </div>
      <div class="metric-card green">
        <div class="metric-label">Online</div>
        <div class="metric-value">${configured}</div>
        <div class="metric-sub">${total - configured} offline</div>
      </div>
      <div class="metric-card ${statusClass}">
        <div class="metric-label">System Status</div>
        <div class="metric-value" style="font-size:24px; color:var(--${statusClass})">${status}</div>
        <div class="metric-sub">${Object.keys(system.checks || {}).length} checks</div>
      </div>
      <div class="metric-card purple">
        <div class="metric-label">Tasks Processed</div>
        <div class="metric-value">${tasks['task.submitted'] || 0}</div>
        <div class="metric-sub">Completed: ${tasks['task.completed'] || 0}</div>
      </div>
    `;
  },

  renderAdapters(adapters) {
    const categories = adapters.categories || {};
    const catColors = {
      llm: '#00d4ff',
      search: '#00ff88',
      email: '#ffbb00',
      payment: '#aa66ff',
      browser: '#ff8844',
      vector_db: '#ff4466',
      image_gen: '#ff8844',
      logistics: '#ffbb00',
      knowledge_base: '#aa66ff',
      shopify_native: '#00ff88',
    };

    let html = '';
    const sortedCats = Object.entries(categories).sort((a, b) => b[1].length - a[1].length);

    for (const [catName, catAdapters] of sortedCats) {
      const color = catColors[catName] || '#6b6b8d';
      const onCount = catAdapters.filter(a => a.configured).length;

      html += `<div class="adapter-category">
        <div class="adapter-cat-header">
          <span style="color:${color}">${catName.replace(/_/g, ' ').toUpperCase()}</span>
          <span class="adapter-cat-count">${onCount}/${catAdapters.length}</span>
        </div>
        <div class="adapter-items">`;

      for (const adapter of catAdapters.sort((a, b) => b.priority - a.priority)) {
        html += `<div class="adapter-chip" title="${adapter.capabilities.join(', ')}">
          <span class="dot ${adapter.configured ? 'on' : 'off'}"></span>
          <span>${adapter.name}</span>
          <span class="priority">P${adapter.priority}</span>
        </div>`;
      }

      html += `</div></div>`;
    }

    document.getElementById('adapter-list').innerHTML = html || '<span style="color:var(--text-dim)">No adapters registered</span>';
    document.getElementById('adapter-count').textContent = adapters.total || 0;
  },

  renderHealth(system) {
    const checks = system.checks || {};
    let html = '';

    if (Object.keys(checks).length === 0) {
      html = '<div style="color:var(--text-dim);padding:8px 0">No health checks available</div>';
    }

    for (const [name, result] of Object.entries(checks)) {
      const isOk = typeof result === 'string'
        ? result.toLowerCase().includes('ok') || result.toLowerCase().includes('healthy')
        : !!result;
      const cls = isOk ? 'ok' : 'fail';
      const label = isOk ? 'OK' : 'ISSUE';

      html += `<div class="health-row">
        <span class="health-name">${name}</span>
        <span class="health-status ${cls}">${label}</span>
      </div>`;
    }

    document.getElementById('health-checks').innerHTML = html;
  },
};
