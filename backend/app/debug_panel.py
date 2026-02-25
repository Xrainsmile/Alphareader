"""Built-in API Debug Panel for AlphaReader.

Serves a self-contained HTML page at ``/debug`` (only when DEBUG=true).
Features:
  - All API endpoints with pre-filled parameters
  - One-click request execution with response viewer
  - Request/response timing and X-Request-ID tracking
  - Dark theme matching the AlphaReader frontend
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["debug"])

_DEBUG_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AlphaReader – API Debug Panel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0b1120;--surface:#111827;--surface2:#1e293b;--border:#334155;
  --text:#e2e8f0;--text2:#94a3b8;--accent:#3b82f6;--accent-hover:#2563eb;
  --green:#22c55e;--red:#ef4444;--orange:#f59e0b;--purple:#a78bfa;
  --radius:8px;--mono:'SF Mono','Fira Code','JetBrains Mono',Consolas,monospace;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.5;min-height:100vh}

/* ── Header ── */
.header{background:var(--surface);border-bottom:1px solid var(--border);
  padding:16px 24px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:10}
.header h1{font-size:18px;font-weight:700;color:#fff}
.header .badge{font-size:11px;padding:2px 8px;border-radius:10px;
  background:var(--accent);color:#fff;font-weight:600}
.header .env{margin-left:auto;font-size:12px;color:var(--text2)}

/* ── Layout ── */
.container{max-width:1200px;margin:0 auto;padding:24px}

/* ── Status Bar ── */
.status-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:12px;margin-bottom:24px}
.status-card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:14px 16px}
.status-card .label{font-size:11px;color:var(--text2);text-transform:uppercase;
  letter-spacing:0.5px;margin-bottom:4px}
.status-card .value{font-size:20px;font-weight:700}
.status-card .value.ok{color:var(--green)}
.status-card .value.err{color:var(--red)}
.status-card .value.loading{color:var(--text2)}

/* ── Endpoint Cards ── */
.endpoint{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);margin-bottom:16px;overflow:hidden}
.endpoint .ep-header{display:flex;align-items:center;gap:12px;
  padding:14px 16px;cursor:pointer;user-select:none}
.endpoint .ep-header:hover{background:var(--surface2)}
.method{font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;
  font-family:var(--mono);min-width:56px;text-align:center}
.method.get{background:#164e63;color:#22d3ee}
.method.post{background:#3b2f00;color:var(--orange)}
.method.delete{background:#450a0a;color:#fca5a5}
.ep-path{font-family:var(--mono);font-size:13px;color:#fff;font-weight:500}
.ep-desc{font-size:12px;color:var(--text2);margin-left:auto}
.ep-arrow{color:var(--text2);font-size:14px;transition:transform .2s}
.endpoint.open .ep-arrow{transform:rotate(90deg)}

.ep-body{display:none;border-top:1px solid var(--border);padding:16px}
.endpoint.open .ep-body{display:block}

/* ── Form ── */
.params{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin-bottom:14px}
.param{display:flex;flex-direction:column;gap:4px}
.param label{font-size:11px;color:var(--text2);font-weight:500}
.param input,.param select{background:var(--bg);border:1px solid var(--border);
  border-radius:6px;padding:7px 10px;color:var(--text);font-size:13px;
  font-family:var(--mono);outline:none}
.param input:focus,.param select:focus{border-color:var(--accent)}
.param .hint{font-size:10px;color:var(--text2)}

.actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.btn{padding:8px 18px;border:none;border-radius:6px;font-size:13px;
  font-weight:600;cursor:pointer;transition:all .15s}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent-hover)}
.btn-danger{background:#991b1b;color:#fca5a5}
.btn-danger:hover{background:#7f1d1d}
.btn-secondary{background:var(--surface2);color:var(--text);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--border)}
.btn:disabled{opacity:.5;cursor:not-allowed}

.req-meta{font-size:11px;color:var(--text2);margin-left:auto;font-family:var(--mono)}
.req-meta .rid{color:var(--purple)}
.req-meta .time{color:var(--orange)}

/* ── Response ── */
.response{margin-top:14px;border-radius:var(--radius);overflow:hidden;
  border:1px solid var(--border)}
.resp-header{display:flex;align-items:center;gap:10px;padding:8px 12px;
  background:var(--surface2);font-size:12px}
.resp-status{font-weight:700;font-family:var(--mono)}
.resp-status.s2xx{color:var(--green)}
.resp-status.s4xx{color:var(--orange)}
.resp-status.s5xx{color:var(--red)}
.resp-body{padding:12px;background:var(--bg);max-height:500px;overflow:auto;
  font-family:var(--mono);font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all}

/* ── Utilities ── */
.hidden{display:none}
.spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── JSON Syntax Highlighting ── */
.json-key{color:#93c5fd}
.json-str{color:#86efac}
.json-num{color:#fde68a}
.json-bool{color:#c4b5fd}
.json-null{color:#94a3b8}
</style>
</head>
<body>

<div class="header">
  <h1>AlphaReader</h1>
  <span class="badge">Debug Panel</span>
  <span class="env" id="envInfo">loading…</span>
</div>

<div class="container">

  <!-- Status Bar -->
  <div class="status-bar">
    <div class="status-card" id="card-service">
      <div class="label">Service</div>
      <div class="value loading" id="val-service">—</div>
    </div>
    <div class="status-card" id="card-postgres">
      <div class="label">PostgreSQL</div>
      <div class="value loading" id="val-postgres">—</div>
    </div>
    <div class="status-card" id="card-redis">
      <div class="label">Redis</div>
      <div class="value loading" id="val-redis">—</div>
    </div>
    <div class="status-card" id="card-pipeline">
      <div class="label">Pipeline</div>
      <div class="value loading" id="val-pipeline">—</div>
    </div>
  </div>

  <!-- ── Endpoints ── -->
  <div id="endpoints"></div>

</div>

<script>
const BASE = window.location.origin;
const _API_KEY = '{{ api_key }}';

// ── Endpoint Definitions ──
const ENDPOINTS = [
  {
    id: 'root', method: 'GET', path: '/',
    desc: '服务信息', params: []
  },
  {
    id: 'health', method: 'GET', path: '/api/v1/health',
    desc: '健康检查（DB + Redis）', params: []
  },
  {
    id: 'news', method: 'GET', path: '/api/v1/news/',
    desc: '新闻列表（分页 + 筛选）',
    params: [
      { name: 'limit', type: 'number', default: 20, hint: '1–100' },
      { name: 'offset', type: 'number', default: 0, hint: '≥0' },
      { name: 'min_score', type: 'number', default: 6, hint: '0–10' },
      { name: 'source', type: 'text', default: '', hint: '如 财联社 / 华尔街见闻 / MarketWatch / CNBC' },
      { name: 'sector', type: 'text', default: '', hint: '如 新能源 / 半导体' },
    ]
  },
  {
    id: 'pipeline-run', method: 'POST', path: '/api/v1/news/pipeline/run',
    desc: '手动触发 Pipeline', params: [], danger: true
  },
  {
    id: 'pipeline-status', method: 'GET', path: '/api/v1/news/pipeline/status',
    desc: 'Pipeline 运行状态', params: []
  },
  {
    id: 'pipeline-cache', method: 'DELETE', path: '/api/v1/news/pipeline/cache',
    desc: '清除去重缓存', params: [], danger: true
  },
  {
    id: 'bridge', method: 'GET', path: '/api/v1/bridge/generate_prompt',
    desc: '生成大模型提示词',
    params: [
      { name: 'sector', type: 'text', default: '', hint: '板块，如 新能源' },
      { name: 'date', type: 'date', default: new Date().toISOString().slice(0, 10), hint: '目标日期' },
      { name: 'top_n', type: 'number', default: 10, hint: '1–30' },
    ]
  },
];

// ── JSON Syntax Highlight ──
function highlightJson(obj) {
  const raw = JSON.stringify(obj, null, 2);
  return raw.replace(
    /("(?:[^"\\]|\\.)*")\s*:/g,
    '<span class="json-key">$1</span>:'
  ).replace(
    /:\s*("(?:[^"\\]|\\.)*")/g,
    ': <span class="json-str">$1</span>'
  ).replace(
    /:\s*(\d+\.?\d*)/g,
    ': <span class="json-num">$1</span>'
  ).replace(
    /:\s*(true|false)/g,
    ': <span class="json-bool">$1</span>'
  ).replace(
    /:\s*(null)/g,
    ': <span class="json-null">$1</span>'
  );
}

// ── Build UI ──
function renderEndpoints() {
  const container = document.getElementById('endpoints');
  ENDPOINTS.forEach(ep => {
    const card = document.createElement('div');
    card.className = 'endpoint';
    card.id = `ep-${ep.id}`;

    const methodClass = ep.method.toLowerCase();
    const btnClass = ep.danger ? 'btn btn-danger' : 'btn btn-primary';

    let paramsHtml = '';
    if (ep.params.length) {
      paramsHtml = '<div class="params">' + ep.params.map(p => {
        const val = p.default !== undefined ? p.default : '';
        return `<div class="param">
          <label>${p.name}</label>
          <input type="${p.type}" name="${p.name}" value="${val}" data-ep="${ep.id}" />
          ${p.hint ? `<span class="hint">${p.hint}</span>` : ''}
        </div>`;
      }).join('') + '</div>';
    }

    card.innerHTML = `
      <div class="ep-header" onclick="toggleEndpoint('${ep.id}')">
        <span class="method ${methodClass}">${ep.method}</span>
        <span class="ep-path">${ep.path}</span>
        <span class="ep-desc">${ep.desc}</span>
        <span class="ep-arrow">▶</span>
      </div>
      <div class="ep-body">
        ${paramsHtml}
        <div class="actions">
          <button class="${btnClass}" onclick="sendRequest('${ep.id}')" id="btn-${ep.id}">
            发送请求
          </button>
          <button class="btn btn-secondary" onclick="clearResponse('${ep.id}')">清除</button>
          <span class="req-meta" id="meta-${ep.id}"></span>
        </div>
        <div class="response hidden" id="resp-${ep.id}">
          <div class="resp-header">
            <span class="resp-status" id="status-${ep.id}"></span>
            <span id="statusText-${ep.id}" style="color:var(--text2)"></span>
          </div>
          <div class="resp-body" id="body-${ep.id}"></div>
        </div>
      </div>`;
    container.appendChild(card);
  });
}

function toggleEndpoint(id) {
  document.getElementById(`ep-${id}`).classList.toggle('open');
}

function clearResponse(id) {
  document.getElementById(`resp-${id}`).classList.add('hidden');
  document.getElementById(`meta-${id}`).innerHTML = '';
}

// ── Send Request ──
async function sendRequest(id) {
  const ep = ENDPOINTS.find(e => e.id === id);
  const btn = document.getElementById(`btn-${id}`);
  const meta = document.getElementById(`meta-${id}`);
  const respEl = document.getElementById(`resp-${id}`);
  const statusEl = document.getElementById(`status-${id}`);
  const statusTextEl = document.getElementById(`statusText-${id}`);
  const bodyEl = document.getElementById(`body-${id}`);

  // Build URL with query params
  let url = BASE + ep.path;
  if (ep.params.length) {
    const params = new URLSearchParams();
    ep.params.forEach(p => {
      const input = document.querySelector(`input[data-ep="${id}"][name="${p.name}"]`);
      if (input && input.value !== '') {
        params.set(p.name, input.value);
      }
    });
    const qs = params.toString();
    if (qs) url += '?' + qs;
  }

  btn.disabled = true;
  meta.innerHTML = '<span class="spinner"></span>';

  const t0 = performance.now();
  try {
    const resp = await fetch(url, { method: ep.method, headers: _API_KEY ? {'X-API-Key': _API_KEY} : {} });
    const elapsed = (performance.now() - t0).toFixed(0);
    const rid = resp.headers.get('x-request-id') || '—';

    let data;
    const ct = resp.headers.get('content-type') || '';
    if (ct.includes('json')) {
      data = await resp.json();
    } else {
      data = await resp.text();
    }

    // Status
    const sc = resp.status;
    statusEl.textContent = sc;
    statusEl.className = 'resp-status ' + (sc < 300 ? 's2xx' : sc < 500 ? 's4xx' : 's5xx');
    statusTextEl.textContent = resp.statusText;

    // Body
    if (typeof data === 'object') {
      bodyEl.innerHTML = highlightJson(data);
    } else {
      bodyEl.textContent = data;
    }

    // Meta
    meta.innerHTML = `<span class="time">${elapsed}ms</span> · <span class="rid">rid: ${rid}</span>`;

    respEl.classList.remove('hidden');
  } catch (err) {
    statusEl.textContent = 'ERR';
    statusEl.className = 'resp-status s5xx';
    statusTextEl.textContent = 'Network Error';
    bodyEl.textContent = err.message;
    meta.innerHTML = '<span style="color:var(--red)">请求失败</span>';
    respEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
  }
}

// ── Status Bar Auto-Refresh ──
async function refreshStatus() {
  const _h = _API_KEY ? {'X-API-Key': _API_KEY} : {};
  // Service info
  try {
    const r = await fetch(BASE + '/', {headers: _h});
    const d = await r.json();
    document.getElementById('val-service').textContent = `v${d.version}`;
    document.getElementById('val-service').className = 'value ok';
    document.getElementById('envInfo').textContent = `${d.env} · ${window.location.host}`;
  } catch {
    document.getElementById('val-service').textContent = 'DOWN';
    document.getElementById('val-service').className = 'value err';
  }

  // Health
  try {
    const r = await fetch(BASE + '/api/v1/health');
    const d = await r.json();
    document.getElementById('val-postgres').textContent = d.postgres === 'ok' ? 'OK' : 'ERR';
    document.getElementById('val-postgres').className = 'value ' + (d.postgres === 'ok' ? 'ok' : 'err');
    document.getElementById('val-redis').textContent = d.redis === 'ok' ? 'OK' : 'ERR';
    document.getElementById('val-redis').className = 'value ' + (d.redis === 'ok' ? 'ok' : 'err');
  } catch {
    document.getElementById('val-postgres').textContent = '—';
    document.getElementById('val-redis').textContent = '—';
  }

  // Pipeline
  try {
    const r = await fetch(BASE + '/api/v1/news/pipeline/status', {headers: _h});
    const d = await r.json();
    if (d.running) {
      document.getElementById('val-pipeline').textContent = 'RUNNING';
      document.getElementById('val-pipeline').className = 'value';
      document.getElementById('val-pipeline').style.color = 'var(--orange)';
    } else if (d.last_result && d.last_result.error) {
      document.getElementById('val-pipeline').textContent = 'FAILED';
      document.getElementById('val-pipeline').className = 'value err';
    } else {
      document.getElementById('val-pipeline').textContent = 'IDLE';
      document.getElementById('val-pipeline').className = 'value ok';
    }
  } catch {
    document.getElementById('val-pipeline').textContent = '—';
  }
}

// ── Init ──
renderEndpoints();
refreshStatus();
setInterval(refreshStatus, 15000);

// Keyboard shortcut: Ctrl+Enter to send request in focused endpoint
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const focused = document.activeElement;
    if (focused && focused.dataset && focused.dataset.ep) {
      sendRequest(focused.dataset.ep);
    }
  }
});
</script>
</body>
</html>"""


@router.get("/debug", response_class=HTMLResponse, include_in_schema=False)
async def debug_panel():
    """Serve the API debug panel (only available when DEBUG=true)."""
    from app.config import settings
    html = _DEBUG_HTML.replace("{{ api_key }}", settings.API_KEY or "")
    return HTMLResponse(content=html)
