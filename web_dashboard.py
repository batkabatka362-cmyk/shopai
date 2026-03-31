"""Web Dashboard — browser-based system monitoring.

Serves HTML dashboard on /dashboard with:
  - System health, engine stats, agent stats
  - Live metrics (auto-refresh)
  - Workflow runner
  - Engine search and test

Pure stdlib — no Flask/React dependency.
"""
from __future__ import annotations

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse, parse_qs

from utils.logger import get_logger

logger = get_logger("web.dashboard")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShopAI Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0f0f0f;color:#e0e0e0}
.header{background:#1a1a2e;padding:20px 30px;border-bottom:1px solid #333}
.header h1{font-size:24px;color:#fff}
.header span{color:#888;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;padding:20px}
.card{background:#1a1a2e;border-radius:12px;padding:20px;border:1px solid #2a2a3e}
.card h2{font-size:16px;color:#888;margin-bottom:12px;text-transform:uppercase;letter-spacing:1px}
.card .value{font-size:36px;font-weight:700;color:#fff}
.card .sub{color:#888;font-size:13px;margin-top:4px}
.status-healthy{color:#4ade80}
.status-degraded{color:#fbbf24}
.status-error{color:#f87171}
.bar{height:8px;background:#2a2a3e;border-radius:4px;margin:6px 0;overflow:hidden}
.bar-fill{height:100%;border-radius:4px;transition:width 0.5s}
.bar-green{background:linear-gradient(90deg,#4ade80,#22c55e)}
.bar-blue{background:linear-gradient(90deg,#60a5fa,#3b82f6)}
.bar-yellow{background:linear-gradient(90deg,#fbbf24,#f59e0b)}
table{width:100%;border-collapse:collapse;margin-top:10px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #2a2a3e;font-size:13px}
th{color:#888;text-transform:uppercase;font-size:11px;letter-spacing:1px}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}
.badge-green{background:#064e3b;color:#4ade80}
.badge-red{background:#450a0a;color:#f87171}
.badge-yellow{background:#451a03;color:#fbbf24}
.badge-blue{background:#172554;color:#60a5fa}
.actions{padding:20px;display:flex;gap:10px;flex-wrap:wrap}
button{padding:8px 16px;border-radius:6px;border:1px solid #333;background:#1a1a2e;color:#e0e0e0;cursor:pointer;font-size:13px}
button:hover{background:#2a2a3e}
button.primary{background:#3b82f6;border-color:#3b82f6;color:#fff}
#output{padding:20px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:400px;overflow-y:auto}
.footer{text-align:center;padding:20px;color:#555;font-size:12px}
</style>
</head>
<body>
<div class="header">
  <h1>ShopAI Dashboard</h1>
  <span id="timestamp"></span> | <span id="refresh-status">Auto-refresh: 10s</span>
</div>

<div class="grid" id="stats"></div>

<div class="card" style="margin:0 20px">
  <h2>Engines by Domain</h2>
  <div id="domains"></div>
</div>

<div class="grid" style="padding-top:0">
  <div class="card">
    <h2>Agents</h2>
    <table id="agents"><tr><th>Agent</th><th>Engines</th></tr></table>
  </div>
  <div class="card">
    <h2>Workflows</h2>
    <table id="workflows"><tr><th>Workflow</th><th>Steps</th></tr></table>
  </div>
</div>

<div class="actions">
  <button class="primary" onclick="runAction('health')">Health Check</button>
  <button onclick="runAction('analyze')">System Analysis</button>
  <button onclick="runAction('workflow','product_launch')">Run Product Launch</button>
  <button onclick="runAction('workflow','customer_retention')">Run Retention</button>
</div>
<div class="card" style="margin:0 20px"><h2>Output</h2><div id="output">Ready.</div></div>

<div class="footer">ShopAI v1.0 | <span id="engine-count"></span> engines | <span id="test-count">102</span> tests</div>

<script>
async function fetchData(){
  try{
    const r=await fetch('/api/dashboard-data');
    const d=await r.json();
    renderStats(d);
    renderDomains(d.domains||{});
    renderTable('agents',d.agents||[],'name','engines');
    renderTable('workflows',d.workflows||[],'name','steps');
    document.getElementById('timestamp').textContent=new Date().toLocaleTimeString();
    document.getElementById('engine-count').textContent=d.engine_count||0;
  }catch(e){document.getElementById('output').textContent='Error: '+e.message}
}

function renderStats(d){
  const h=d.health||{};
  const m=d.metrics||{};
  const c=m.counters||{};
  document.getElementById('stats').innerHTML=`
    <div class="card"><h2>System Status</h2>
      <div class="value ${h.status==='healthy'?'status-healthy':'status-error'}">${(h.status||'?').toUpperCase()}</div>
      <div class="sub">${d.engine_count||0} engines registered</div></div>
    <div class="card"><h2>Tasks</h2>
      <div class="value">${c['task.submitted']||0}</div>
      <div class="sub">Completed: ${c['task.completed']||0} | Failed: ${(c['task.failed']||0)+(c['task.crash']||0)}</div></div>
    <div class="card"><h2>Cache</h2>
      <div class="value">${((d.cache||{}).hit_rate||0)*100|0}%</div>
      <div class="sub">Hits: ${(d.cache||{}).hits||0} | Size: ${(d.cache||{}).size||0}</div></div>
    <div class="card"><h2>Events</h2>
      <div class="value">${(d.events||{}).published||0}</div>
      <div class="sub">Delivered: ${(d.events||{}).delivered||0} | Subscribers: ${(d.events||{}).subscriber_count||0}</div></div>
  `;
}

function renderDomains(domains){
  const el=document.getElementById('domains');
  const total=Object.values(domains).reduce((a,b)=>a+b,0)||1;
  const colors=['bar-green','bar-blue','bar-yellow','bar-green','bar-blue','bar-yellow','bar-green','bar-blue','bar-yellow','bar-green'];
  let html='';
  Object.entries(domains).sort((a,b)=>b[1]-a[1]).forEach(([name,count],i)=>{
    const pct=count/total*100;
    html+=`<div style="display:flex;align-items:center;gap:10px;margin:4px 0">
      <span style="width:100px;font-size:13px">${name}</span>
      <div class="bar" style="flex:1"><div class="bar-fill ${colors[i%10]}" style="width:${pct}%"></div></div>
      <span style="font-size:12px;color:#888">${count} (${pct.toFixed(0)}%)</span>
    </div>`;
  });
  el.innerHTML=html;
}

function renderTable(id,items,k1,k2){
  const el=document.getElementById(id);
  let html='<tr><th>'+k1+'</th><th>'+k2+'</th></tr>';
  items.forEach(i=>{html+=`<tr><td>${i[k1]}</td><td>${i[k2]}</td></tr>`});
  el.innerHTML=html;
}

async function runAction(action,param){
  const el=document.getElementById('output');
  el.textContent='Running '+action+'...';
  try{
    let r;
    if(action==='health') r=await fetch('/api/health');
    else if(action==='analyze') r=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    else if(action==='workflow') r=await fetch('/api/workflow',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workflow:param,data:{products:[{name:"Test",price:30,cost:10}],criteria:{}}})});
    const d=await r.json();
    el.textContent=JSON.stringify(d,null,2);
  }catch(e){el.textContent='Error: '+e.message}
}

fetchData();
setInterval(fetchData,10000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    orchestrator = None

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path in ("", "/", "/dashboard"):
            self._html_response(200, DASHBOARD_HTML)
        elif path == "/api/dashboard-data":
            self._dashboard_data()
        elif path == "/api/health":
            from core.self_monitor import HealthChecker
            self._json_response(200, HealthChecker().check_all())
        elif path == "/api/engines":
            from engines.registry import list_engines, engine_count
            self._json_response(200, {"count": engine_count(), "engines": list_engines()})
        else:
            self._json_response(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        body = self._read_body()

        if path == "/api/analyze":
            if self.orchestrator:
                self._json_response(200, self.orchestrator.analyze_system())
            else:
                self._json_response(503, {"error": "Not initialized"})
        elif path == "/api/workflow":
            if self.orchestrator:
                wf = (body or {}).get("workflow", "product_launch")
                data = (body or {}).get("data", {})
                self._json_response(200, self.orchestrator.run_workflow(wf, data))
            else:
                self._json_response(503, {"error": "Not initialized"})
        else:
            self._json_response(404, {"error": "Not found"})

    def _dashboard_data(self):
        from engines.registry import engine_count, list_engines
        from core.step_logic.domain import DomainRouter

        data = {"engine_count": engine_count()}

        if self.orchestrator:
            status = self.orchestrator.get_status()
            data["metrics"] = status.get("metrics", {})
            data["cache"] = status.get("cache_stats", {})
            data["events"] = status.get("event_stats", {})
            data["agents"] = self.orchestrator.list_agents()
            data["workflows"] = self.orchestrator.list_workflows()

            from core.self_monitor import HealthChecker
            data["health"] = HealthChecker().check_all()

        # Domain distribution
        dr = DomainRouter()
        domains = {}
        for e in list_engines():
            d = dr.get_domain(e)
            name = type(d).__name__.replace("Logic", "") if d else "Other"
            domains[name] = domains.get(name, 0) + 1
        data["domains"] = domains

        self._json_response(200, data)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            return {}

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _html_response(self, status, html):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, *args):
        pass  # Suppress default logging


def start_dashboard(port: int = 8080):
    """Start web dashboard."""
    from core.orchestrator import MainOrchestrator
    orch = MainOrchestrator()
    orch.initialize()
    DashboardHandler.orchestrator = orch

    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"ShopAI Dashboard: http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        orch.shutdown()
        print("\nDashboard stopped.")


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    start_dashboard(port)
