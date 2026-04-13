/* ── Tab 2: Neural Map — Force-directed graph ─────── */

const NeuralMap = {
  canvas: null,
  ctx: null,
  nodes: [],
  edges: [],
  animFrame: null,
  hoveredNode: null,
  dragging: null,
  mouse: { x: 0, y: 0 },
  initialized: false,

  init() {
    if (this.animFrame) cancelAnimationFrame(this.animFrame);

    this.canvas = document.getElementById('neural-canvas');
    this.ctx = this.canvas.getContext('2d');
    this.resize();

    window.addEventListener('resize', () => this.resize());
    this.canvas.addEventListener('mousemove', e => this.onMouseMove(e));
    this.canvas.addEventListener('mousedown', e => this.onMouseDown(e));
    this.canvas.addEventListener('mouseup', () => this.onMouseUp());
    this.canvas.addEventListener('mouseleave', () => { this.hoveredNode = null; this.dragging = null; });

    this.loadData();
    this.renderLegend();
    this.initialized = true;
  },

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.canvas.width = rect.width * devicePixelRatio;
    this.canvas.height = rect.height * devicePixelRatio;
    this.canvas.style.width = rect.width + 'px';
    this.canvas.style.height = rect.height + 'px';
    this.ctx.scale(devicePixelRatio, devicePixelRatio);
    this.W = rect.width;
    this.H = rect.height;
  },

  loadData() {
    const graphData = App.data.graph || {};
    const rawNodes = graphData.nodes || [];
    const rawEdges = graphData.edges || [];

    // Initialize node positions
    this.nodes = rawNodes.map((n, i) => {
      const angle = (i / rawNodes.length) * Math.PI * 2;
      const r = n.type === 'core' ? 0 : n.type === 'category' ? 150 : n.type === 'system' ? 120 : 280;
      return {
        ...n,
        x: this.W / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 60,
        y: this.H / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 60,
        vx: 0,
        vy: 0,
        targetSize: n.size || 15,
        currentSize: 0,
        glowPhase: Math.random() * Math.PI * 2,
      };
    });

    this.edges = rawEdges.map(e => ({
      ...e,
      fromNode: this.nodes.find(n => n.id === e.from),
      toNode: this.nodes.find(n => n.id === e.to),
    })).filter(e => e.fromNode && e.toNode);

    this.animate();
  },

  animate() {
    this.simulate();
    this.draw();
    this.animFrame = requestAnimationFrame(() => this.animate());
  },

  simulate() {
    const dt = 0.016;
    const repulsion = 2000;
    const attraction = 0.01;
    const damping = 0.85;
    const centerPull = 0.002;

    // Repulsion between all nodes
    for (let i = 0; i < this.nodes.length; i++) {
      for (let j = i + 1; j < this.nodes.length; j++) {
        const a = this.nodes[i];
        const b = this.nodes[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dist = Math.sqrt(dx * dx + dy * dy) + 1;
        const force = repulsion / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx += fx * dt;
        a.vy += fy * dt;
        b.vx -= fx * dt;
        b.vy -= fy * dt;
      }
    }

    // Attraction along edges
    for (const edge of this.edges) {
      const a = edge.fromNode;
      const b = edge.toNode;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 1;
      const idealDist = a.type === 'core' ? 160 : 120;
      const force = (dist - idealDist) * attraction;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    // Center gravity + update positions
    for (const node of this.nodes) {
      if (node === this.dragging) continue;
      node.vx += (this.W / 2 - node.x) * centerPull;
      node.vy += (this.H / 2 - node.y) * centerPull;
      node.vx *= damping;
      node.vy *= damping;
      node.x += node.vx;
      node.y += node.vy;

      // Bounds
      const margin = 40;
      node.x = Math.max(margin, Math.min(this.W - margin, node.x));
      node.y = Math.max(margin, Math.min(this.H - margin, node.y));

      // Animate size
      node.currentSize += (node.targetSize - node.currentSize) * 0.05;
      node.glowPhase += 0.02;
    }
  },

  draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);

    // Background grid
    ctx.strokeStyle = 'rgba(30,30,58,0.3)';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < this.W; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.H); ctx.stroke();
    }
    for (let y = 0; y < this.H; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(this.W, y); ctx.stroke();
    }

    // Edges
    for (const edge of this.edges) {
      const a = edge.fromNode;
      const b = edge.toNode;
      const gradient = ctx.createLinearGradient(a.x, a.y, b.x, b.y);

      if (edge.type === 'primary') {
        gradient.addColorStop(0, 'rgba(0,212,255,0.4)');
        gradient.addColorStop(1, 'rgba(0,212,255,0.15)');
        ctx.lineWidth = 2;
      } else if (edge.type === 'system') {
        gradient.addColorStop(0, 'rgba(170,102,255,0.3)');
        gradient.addColorStop(1, 'rgba(170,102,255,0.1)');
        ctx.lineWidth = 1.5;
      } else {
        gradient.addColorStop(0, 'rgba(107,107,141,0.25)');
        gradient.addColorStop(1, 'rgba(107,107,141,0.08)');
        ctx.lineWidth = 1;
      }

      ctx.strokeStyle = gradient;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();

      // Animated particle along edge
      const t = (Date.now() % 3000) / 3000;
      const px = a.x + (b.x - a.x) * t;
      const py = a.y + (b.y - a.y) * t;
      ctx.fillStyle = edge.type === 'primary' ? 'rgba(0,212,255,0.6)' : 'rgba(170,102,255,0.4)';
      ctx.beginPath();
      ctx.arc(px, py, 2, 0, Math.PI * 2);
      ctx.fill();
    }

    // Nodes
    for (const node of this.nodes) {
      const size = node.currentSize;
      const glow = Math.sin(node.glowPhase) * 0.3 + 0.7;
      const isHovered = node === this.hoveredNode;
      const color = this.getNodeColor(node);

      // Glow
      if (node.type === 'core' || isHovered) {
        const glowSize = size * (isHovered ? 3 : 2.5);
        const grad = ctx.createRadialGradient(node.x, node.y, size * 0.5, node.x, node.y, glowSize);
        grad.addColorStop(0, color.replace(')', `,${glow * 0.25})`).replace('rgb', 'rgba'));
        grad.addColorStop(1, 'transparent');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(node.x, node.y, glowSize, 0, Math.PI * 2);
        ctx.fill();
      }

      // Node circle
      ctx.fillStyle = color;
      ctx.globalAlpha = node.configured === false ? 0.4 : glow;
      ctx.beginPath();
      ctx.arc(node.x, node.y, size, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;

      // Border
      if (isHovered) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label
      ctx.fillStyle = isHovered ? '#ffffff' : 'rgba(200,200,224,0.8)';
      ctx.font = `${isHovered ? '12px' : node.type === 'core' ? '13px' : '10px'} -apple-system, sans-serif`;
      ctx.textAlign = 'center';
      ctx.fillText(node.label, node.x, node.y + size + 14);
    }
  },

  getNodeColor(node) {
    switch (node.type) {
      case 'core': return 'rgb(0,212,255)';
      case 'category': return 'rgb(0,255,136)';
      case 'system': return 'rgb(170,102,255)';
      case 'adapter': return node.configured ? 'rgb(0,180,220)' : 'rgb(80,80,120)';
      default: return 'rgb(107,107,141)';
    }
  },

  onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = e.clientX - rect.left;
    this.mouse.y = e.clientY - rect.top;

    if (this.dragging) {
      this.dragging.x = this.mouse.x;
      this.dragging.y = this.mouse.y;
      this.dragging.vx = 0;
      this.dragging.vy = 0;
      return;
    }

    // Hit test
    this.hoveredNode = null;
    for (const node of this.nodes) {
      const dx = this.mouse.x - node.x;
      const dy = this.mouse.y - node.y;
      if (dx * dx + dy * dy < (node.currentSize + 8) * (node.currentSize + 8)) {
        this.hoveredNode = node;
        this.canvas.style.cursor = 'pointer';
        this.showNodeInfo(node);
        return;
      }
    }
    this.canvas.style.cursor = 'grab';
    this.hideNodeInfo();
  },

  onMouseDown(e) {
    if (this.hoveredNode) {
      this.dragging = this.hoveredNode;
      this.canvas.style.cursor = 'grabbing';
    }
  },

  onMouseUp() {
    this.dragging = null;
    this.canvas.style.cursor = this.hoveredNode ? 'pointer' : 'grab';
  },

  showNodeInfo(node) {
    const info = document.getElementById('graph-info');
    let details = '';
    if (node.type === 'adapter') {
      details = `
        <div class="node-detail">
          Status: ${node.configured ? '<span style="color:var(--green)">Online</span>' : '<span style="color:var(--red)">Offline</span>'}<br>
          Priority: ${node.priority || 0}<br>
          Type: Adapter
        </div>`;
    } else if (node.type === 'category') {
      details = `<div class="node-detail">Adapters: ${node.count || 0}<br>Type: Category Hub</div>`;
    } else if (node.type === 'core') {
      details = `<div class="node-detail">Central intelligence orchestrator</div>`;
    } else {
      details = `<div class="node-detail">Type: ${node.type}</div>`;
    }
    info.innerHTML = `<div class="node-name">${node.label}</div>${details}`;
  },

  hideNodeInfo() {
    document.getElementById('graph-info').innerHTML = '<span>Click a node for details</span>';
  },

  renderLegend() {
    document.getElementById('graph-legend').innerHTML = `
      <div class="legend-item"><div class="legend-dot" style="background:#00d4ff"></div> Core</div>
      <div class="legend-item"><div class="legend-dot" style="background:#00ff88"></div> Category</div>
      <div class="legend-item"><div class="legend-dot" style="background:#aa66ff"></div> System</div>
      <div class="legend-item"><div class="legend-dot" style="background:#00b4dc"></div> Adapter</div>
      <div class="legend-item"><div class="legend-dot" style="background:#505078"></div> Offline</div>
    `;
  },
};
