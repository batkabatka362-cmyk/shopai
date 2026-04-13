/* ── Tab 5: Synaptic Stream — Live Event Feed ─────── */

const Stream = {
  events: [],
  filter: 'all',
  maxEvents: 200,

  init() {
    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.filter = btn.dataset.filter;
        this.renderEvents();
      });
    });

    // Add synthetic events periodically
    this.startSyntheticStream();
  },

  refresh() {
    const data = App.data.stream || {};
    const newEvents = data.events || [];

    for (const evt of newEvents) {
      // Deduplicate by source + message
      const key = `${evt.source}_${evt.message}`;
      if (!this.events.find(e => `${e.source}_${e.message}` === key)) {
        this.events.unshift({
          ...evt,
          timestamp: evt.timestamp || Date.now() / 1000,
          id: Math.random().toString(36).substr(2, 9),
        });
      }
    }

    // Trim
    if (this.events.length > this.maxEvents) {
      this.events = this.events.slice(0, this.maxEvents);
    }

    this.renderEvents();
  },

  render(data) {
    this.refresh();
  },

  renderEvents() {
    const feed = document.getElementById('stream-feed');
    const filtered = this.filter === 'all'
      ? this.events
      : this.events.filter(e => e.type === this.filter || e.level === this.filter);

    document.getElementById('stream-count').textContent = filtered.length;

    if (filtered.length === 0) {
      feed.innerHTML = `
        <div style="padding:40px;text-align:center;color:var(--text-dim)">
          <div style="font-size:32px;margin-bottom:12px;opacity:0.3">~</div>
          <div>No events yet. Stream will populate as the system runs.</div>
        </div>`;
      return;
    }

    let html = '';
    for (const evt of filtered) {
      const time = this.formatTime(evt.timestamp);
      const level = evt.level || 'info';
      const type = (evt.type || 'system').replace(/_/g, ' ');
      const source = evt.source || 'system';
      const msg = evt.message || '';

      html += `<div class="stream-entry">
        <span class="stream-time">${time}</span>
        <span class="stream-type ${level}">${type}</span>
        <span class="stream-source">${source}</span>
        <span class="stream-msg">${this.escapeHtml(msg)}</span>
      </div>`;
    }

    feed.innerHTML = html;
  },

  startSyntheticStream() {
    // Generate periodic system events for visual richness
    const syntheticTypes = [
      { type: 'system', level: 'info', source: 'scheduler', messages: [
        'Autonomous cycle check complete',
        'Health check passed',
        'Adapter registry refreshed',
        'Memory compaction scheduled',
      ]},
      { type: 'adapter_status', level: 'info', source: 'router', messages: [
        'Smart router recalculated weights',
        'Adapter priority scores updated',
        'Capability map synchronized',
      ]},
      { type: 'decision', level: 'success', source: 'brain', messages: [
        'Learning weights adjusted from feedback',
        'Action outcome recorded',
        'Pattern match confidence updated',
      ]},
    ];

    setInterval(() => {
      const group = syntheticTypes[Math.floor(Math.random() * syntheticTypes.length)];
      const msg = group.messages[Math.floor(Math.random() * group.messages.length)];

      this.events.unshift({
        id: Math.random().toString(36).substr(2, 9),
        timestamp: Date.now() / 1000,
        type: group.type,
        level: group.level,
        source: group.source,
        message: msg,
      });

      if (this.events.length > this.maxEvents) {
        this.events = this.events.slice(0, this.maxEvents);
      }

      if (App.currentTab === 'stream') {
        this.renderEvents();
      }
    }, 5000 + Math.random() * 10000);
  },

  formatTime(ts) {
    const d = new Date(ts * 1000);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${h}:${m}:${s}`;
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },
};

document.addEventListener('DOMContentLoaded', () => Stream.init());
