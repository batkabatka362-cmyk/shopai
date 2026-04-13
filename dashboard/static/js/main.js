/* ── ShopAI Neural Command — Main App ──────────────── */

const App = {
  currentTab: 'command',
  data: {},
  refreshInterval: null,

  init() {
    this.setupNav();
    this.startClock();
    this.refresh();
    this.refreshInterval = setInterval(() => this.refresh(), 8000);
  },

  setupNav() {
    document.querySelectorAll('.nav-item').forEach(item => {
      item.addEventListener('click', () => {
        const tab = item.dataset.tab;
        this.switchTab(tab);
      });
    });
  },

  switchTab(tab) {
    this.currentTab = tab;

    // Update nav
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelector(`.nav-item[data-tab="${tab}"]`)?.classList.add('active');

    // Update panels
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    document.getElementById(`tab-${tab}`)?.classList.add('active');

    // Update title
    const titles = {
      command: 'Command Center',
      neural: 'Neural Map',
      analytics: 'Analytics',
      assistant: 'AI Assistant',
      stream: 'Synaptic Stream',
      cycle: 'Cycles',
      vault: 'Vault',
    };
    document.getElementById('page-title').textContent = titles[tab] || tab;

    // Tab-specific init
    if (tab === 'neural') NeuralMap.init();
    if (tab === 'analytics') Analytics.refresh();
    if (tab === 'stream') Stream.refresh();
    if (tab === 'cycle' && window.Cycle) Cycle.refresh();
    if (tab === 'vault' && window.Vault) Vault.refresh();
  },

  async refresh() {
    try {
      const [overview, graph, analytics, stream] = await Promise.all([
        this.fetch('/api/overview'),
        this.fetch('/api/graph'),
        this.fetch('/api/analytics'),
        this.fetch('/api/stream'),
      ]);

      this.data = { overview, graph, analytics, stream };

      // Update sidebar status
      const total = overview?.adapters?.total || 0;
      const configured = overview?.adapters?.configured || 0;
      document.getElementById('sidebar-status').textContent =
        `${configured}/${total} adapters online`;

      // Refresh active tab
      if (this.currentTab === 'command') Overview.render(overview);
      if (this.currentTab === 'analytics') Analytics.render(analytics);
      if (this.currentTab === 'stream') Stream.render(stream);

    } catch (e) {
      document.getElementById('sidebar-status').textContent = 'Connection error';
    }
  },

  async fetch(url) {
    const r = await fetch(url);
    if (!r.ok) return {};
    return r.json();
  },

  startClock() {
    const update = () => {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, '0');
      const m = String(now.getMinutes()).padStart(2, '0');
      const s = String(now.getSeconds()).padStart(2, '0');
      document.getElementById('clock').textContent = `${h}:${m}:${s}`;
    };
    update();
    setInterval(update, 1000);
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
