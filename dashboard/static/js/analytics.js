/* ── Tab 3: Analytics — Charts & Data ─────────────── */

const Analytics = {
  refresh() {
    const data = App.data.analytics || {};
    this.render(data);
  },

  render(data) {
    if (!data) return;
    this.renderMetrics(data);
    this.drawCategoryChart(data.adapter_categories || {});
    this.drawLLMChart(data.llm_providers || []);
    this.drawCostChart(data.llm_providers || []);
    this.renderCapabilityMap();
  },

  renderMetrics(data) {
    const total = data.total_adapters || 0;
    const configured = data.configured_adapters || 0;
    const cats = Object.keys(data.adapter_categories || {}).length;
    const llmCount = (data.llm_providers || []).length;

    document.getElementById('analytics-metrics').innerHTML = `
      <div class="metric-card accent">
        <div class="metric-label">Total Adapters</div>
        <div class="metric-value">${total}</div>
        <div class="metric-sub">across ${cats} categories</div>
      </div>
      <div class="metric-card green">
        <div class="metric-label">Configured</div>
        <div class="metric-value">${configured}</div>
        <div class="metric-sub">${total > 0 ? Math.round(configured/total*100) : 0}% active</div>
      </div>
      <div class="metric-card purple">
        <div class="metric-label">LLM Providers</div>
        <div class="metric-value">${llmCount}</div>
        <div class="metric-sub">${(data.llm_providers||[]).filter(l=>l.configured).length} online</div>
      </div>
      <div class="metric-card orange">
        <div class="metric-label">Categories</div>
        <div class="metric-value">${cats}</div>
        <div class="metric-sub">adapter groups</div>
      </div>
    `;
  },

  drawCategoryChart(categories) {
    const canvas = document.getElementById('chart-categories');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = 240 * devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '240px';
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const W = rect.width;
    const H = 240;
    ctx.clearRect(0, 0, W, H);

    const entries = Object.entries(categories).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No data available', W/2, H/2);
      return;
    }

    const colors = ['#00d4ff', '#00ff88', '#ffbb00', '#aa66ff', '#ff8844', '#ff4466',
                    '#00bbaa', '#dd66ff', '#88ccff', '#ffdd44'];
    const maxVal = Math.max(...entries.map(e => e[1]));
    const barW = Math.min(40, (W - 60) / entries.length - 8);
    const startX = 40;
    const chartH = H - 50;

    // Y axis
    ctx.strokeStyle = 'rgba(30,30,58,0.5)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = 20 + (chartH / 4) * i;
      ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(W - 10, y); ctx.stroke();
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '10px -apple-system, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(maxVal - (maxVal/4)*i), startX - 6, y + 4);
    }

    // Bars
    entries.forEach(([name, count], i) => {
      const x = startX + 10 + i * (barW + 8);
      const barH = (count / maxVal) * chartH;
      const y = 20 + chartH - barH;
      const color = colors[i % colors.length];

      // Bar gradient
      const grad = ctx.createLinearGradient(x, y, x, y + barH);
      grad.addColorStop(0, color);
      grad.addColorStop(1, color + '44');
      ctx.fillStyle = grad;

      // Rounded top
      const r = Math.min(4, barW / 2);
      ctx.beginPath();
      ctx.moveTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.lineTo(x + barW - r, y);
      ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
      ctx.lineTo(x + barW, y + barH);
      ctx.lineTo(x, y + barH);
      ctx.closePath();
      ctx.fill();

      // Value on top
      ctx.fillStyle = color;
      ctx.font = 'bold 11px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(count, x + barW/2, y - 6);

      // Label below
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '9px -apple-system, sans-serif';
      ctx.save();
      ctx.translate(x + barW/2, H - 4);
      ctx.rotate(-0.4);
      ctx.textAlign = 'right';
      ctx.fillText(name.replace(/_/g, ' '), 0, 0);
      ctx.restore();
    });
  },

  drawLLMChart(providers) {
    const canvas = document.getElementById('chart-llm');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = 240 * devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '240px';
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const W = rect.width;
    const H = 240;
    ctx.clearRect(0, 0, W, H);

    if (providers.length === 0) {
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No LLM providers', W/2, H/2);
      return;
    }

    // Donut chart
    const cx = W * 0.35;
    const cy = H / 2;
    const outerR = 80;
    const innerR = 50;
    const total = providers.length;
    const colors = ['#00d4ff', '#00ff88', '#ffbb00', '#aa66ff', '#ff8844', '#ff4466',
                    '#00bbaa', '#dd66ff', '#88ccff'];

    let startAngle = -Math.PI / 2;
    providers.forEach((p, i) => {
      const sliceAngle = (1 / total) * Math.PI * 2;
      const color = colors[i % colors.length];
      const configured = p.configured;

      ctx.fillStyle = configured ? color : color + '33';
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, startAngle, startAngle + sliceAngle);
      ctx.arc(cx, cy, innerR, startAngle + sliceAngle, startAngle, true);
      ctx.closePath();
      ctx.fill();

      startAngle += sliceAngle;
    });

    // Center text
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 24px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(providers.filter(p => p.configured).length, cx, cy + 4);
    ctx.fillStyle = '#6b6b8d';
    ctx.font = '10px -apple-system, sans-serif';
    ctx.fillText('ONLINE', cx, cy + 18);

    // Legend
    const legendX = W * 0.65;
    let legendY = 20;
    providers.forEach((p, i) => {
      const color = colors[i % colors.length];
      ctx.fillStyle = p.configured ? color : color + '55';
      ctx.beginPath();
      ctx.arc(legendX, legendY + 6, 4, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = p.configured ? '#c8c8e0' : '#6b6b8d';
      ctx.font = '11px -apple-system, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(p.name, legendX + 12, legendY + 10);

      ctx.fillStyle = '#6b6b8d';
      ctx.font = '9px -apple-system, sans-serif';
      ctx.fillText(`P${p.priority}`, legendX + 12, legendY + 22);

      legendY += 26;
    });
  },

  drawCostChart(providers) {
    const canvas = document.getElementById('chart-cost');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * devicePixelRatio;
    canvas.height = 240 * devicePixelRatio;
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '240px';
    ctx.scale(devicePixelRatio, devicePixelRatio);

    const W = rect.width;
    const H = 240;
    ctx.clearRect(0, 0, W, H);

    const withCost = providers.filter(p => p.cost_per_call > 0);
    const freeTier = providers.filter(p => p.cost_per_call === 0);

    if (providers.length === 0) {
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '13px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('No cost data', W/2, H/2);
      return;
    }

    // Horizontal bar chart
    const sorted = [...providers].sort((a, b) => b.cost_per_call - a.cost_per_call);
    const maxCost = Math.max(...sorted.map(p => p.cost_per_call), 0.001);
    const barH = Math.min(22, (H - 40) / sorted.length - 4);
    const labelW = 90;
    const chartW = W - labelW - 60;

    sorted.forEach((p, i) => {
      const y = 20 + i * (barH + 6);
      const barW = (p.cost_per_call / maxCost) * chartW;
      const isFree = p.cost_per_call === 0;

      // Label
      ctx.fillStyle = p.configured ? '#c8c8e0' : '#6b6b8d';
      ctx.font = '11px -apple-system, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(p.name, labelW - 8, y + barH / 2 + 4);

      // Bar
      const color = isFree ? '#00ff88' : '#ff8844';
      const grad = ctx.createLinearGradient(labelW, y, labelW + barW, y);
      grad.addColorStop(0, color);
      grad.addColorStop(1, color + '44');
      ctx.fillStyle = grad;

      if (barW > 2) {
        ctx.beginPath();
        ctx.roundRect(labelW, y, Math.max(barW, 4), barH, 3);
        ctx.fill();
      } else {
        // Free tier - show minimal bar
        ctx.fillStyle = '#00ff8844';
        ctx.beginPath();
        ctx.roundRect(labelW, y, 30, barH, 3);
        ctx.fill();
      }

      // Cost label
      ctx.fillStyle = '#6b6b8d';
      ctx.font = '10px -apple-system, sans-serif';
      ctx.textAlign = 'left';
      const costText = isFree ? 'FREE' : `$${p.cost_per_call.toFixed(4)}/call`;
      ctx.fillText(costText, labelW + Math.max(barW, 30) + 8, y + barH / 2 + 4);
    });
  },

  renderCapabilityMap() {
    try {
      const adapters = App.data.overview?.adapters?.categories || {};
      const capMap = {};

      for (const [cat, items] of Object.entries(adapters)) {
        for (const adapter of items) {
          for (const cap of adapter.capabilities || []) {
            if (!capMap[cap]) capMap[cap] = 0;
            capMap[cap]++;
          }
        }
      }

      const sorted = Object.entries(capMap).sort((a, b) => b[1] - a[1]);
      let html = '<div class="cap-grid">';
      for (const [cap, count] of sorted) {
        html += `<div class="cap-item">
          <span class="cap-name">${cap.replace(/_/g, ' ')}</span>
          <span class="cap-count">${count}</span>
        </div>`;
      }
      html += '</div>';
      document.getElementById('capability-map').innerHTML = html || '<span style="color:var(--text-dim)">No capabilities</span>';
    } catch (e) {
      document.getElementById('capability-map').innerHTML = '<span style="color:var(--text-dim)">Loading...</span>';
    }
  },
};
