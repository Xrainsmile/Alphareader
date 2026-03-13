"""AlphaReader — RS Rating API 文档页面。

提供一个自包含的 HTML 页面，展示 RS Rating 相关 API 的使用文档，
包含接口说明、参数描述、调用示例和在线测试功能。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import settings

router = APIRouter(tags=["docs"])

_API_DOCS_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AlphaReader — RS Rating API 文档</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0b1120;--surface:#111827;--surface2:#1e293b;--border:#334155;
  --text:#e2e8f0;--text2:#94a3b8;--accent:#3b82f6;--accent-hover:#2563eb;
  --green:#22c55e;--red:#ef4444;--orange:#f59e0b;--purple:#a78bfa;
  --radius:8px;--mono:'SF Mono','Fira Code','JetBrains Mono',Consolas,monospace;
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}

.container{max-width:960px;margin:0 auto;padding:24px 20px}
header{text-align:center;padding:40px 0 32px;border-bottom:1px solid var(--border);margin-bottom:32px}
header h1{font-size:28px;font-weight:700;margin-bottom:8px}
header p{color:var(--text2);font-size:15px}

/* nav */
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:32px;padding:12px;background:var(--surface);border-radius:var(--radius);border:1px solid var(--border)}
.nav a{padding:6px 14px;border-radius:6px;font-size:13px;font-weight:500;transition:background .15s}
.nav a:hover{background:var(--surface2);text-decoration:none}

/* section */
.section{margin-bottom:40px}
.section h2{font-size:20px;font-weight:600;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px}
.section h3{font-size:16px;font-weight:600;margin:20px 0 10px;color:var(--accent)}

/* auth box */
.auth-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:24px}
.auth-box h3{margin:0 0 10px;color:var(--orange)}
.auth-box code{background:var(--surface2);padding:2px 6px;border-radius:4px;font-family:var(--mono);font-size:13px}
.auth-box .methods{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
.auth-box .method{background:var(--surface2);padding:12px;border-radius:6px}
.auth-box .method .label{font-size:12px;color:var(--text2);margin-bottom:4px}

/* endpoint card */
.endpoint{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:20px;overflow:hidden}
.endpoint .ep-header{display:flex;align-items:center;gap:10px;padding:14px 20px;border-bottom:1px solid var(--border);cursor:pointer}
.endpoint .ep-header:hover{background:var(--surface2)}
.ep-method{font-family:var(--mono);font-size:12px;font-weight:700;padding:3px 8px;border-radius:4px;min-width:52px;text-align:center}
.ep-method.get{background:#064e3b;color:var(--green)}
.ep-method.post{background:#7c2d12;color:var(--orange)}
.ep-path{font-family:var(--mono);font-size:14px;color:var(--text)}
.ep-desc{font-size:13px;color:var(--text2);margin-left:auto}
.ep-body{padding:16px 20px;display:none}
.endpoint.open .ep-body{display:block}

/* params table */
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
th{text-align:left;padding:8px 12px;background:var(--surface2);color:var(--text2);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
td{padding:8px 12px;border-top:1px solid var(--border)}
td code{background:var(--surface2);padding:1px 5px;border-radius:3px;font-family:var(--mono);font-size:12px}
.required{color:var(--red);font-size:11px;font-weight:600}
.optional{color:var(--text2);font-size:11px}

/* code block */
pre{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:14px 16px;overflow-x:auto;font-family:var(--mono);font-size:13px;line-height:1.5;margin:10px 0}
.response-label{font-size:12px;color:var(--text2);margin:12px 0 4px;font-weight:600}

/* try-it */
.try-it{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:16px;margin-top:16px}
.try-it h4{font-size:13px;color:var(--accent);margin-bottom:10px}
.try-it .params{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-bottom:12px}
.try-it label{font-size:12px;color:var(--text2);display:block;margin-bottom:3px}
.try-it input{width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:var(--mono);font-size:13px}
.try-it input:focus{outline:none;border-color:var(--accent)}
.try-it button{padding:8px 20px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;transition:background .15s}
.try-it button:hover{background:var(--accent-hover)}
.try-it button:disabled{opacity:.5;cursor:not-allowed}
.try-result{margin-top:12px}
.try-result pre{max-height:400px;overflow-y:auto}
.try-meta{font-size:12px;color:var(--text2);margin-bottom:6px}

/* error responses */
.error-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0}
.error-card{background:var(--surface2);border-radius:6px;padding:12px}
.error-card .status{font-family:var(--mono);font-weight:700;margin-bottom:6px}
.error-card .status.s401{color:var(--orange)}
.error-card .status.s403{color:var(--red)}

@media(max-width:640px){
  .container{padding:16px 12px}
  header{padding:24px 0 20px}
  header h1{font-size:22px}
  .auth-box .methods{grid-template-columns:1fr}
  .error-grid{grid-template-columns:1fr}
  .ep-desc{display:none}
  .try-it .params{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="container">

<header>
  <h1>AlphaReader RS Rating API</h1>
  <p>A 股相对强度评级（RS Rating）数据接口 · v0.1.0</p>
</header>

<nav class="nav">
  <a href="#auth">鉴权</a>
  <a href="#ep-rs-rating">RS Rating 排行</a>
  <a href="#ep-search">股票搜索</a>
  <a href="#ep-status">计算状态</a>
  <a href="#ep-compute">触发计算</a>
  <a href="#errors">错误码</a>
  <a href="#examples">调用示例</a>
</nav>

<!-- ======== 鉴权 ======== -->
<div class="section" id="auth">
  <h2>🔑 鉴权说明</h2>
  <div class="auth-box">
    <h3>API Key 认证</h3>
    <p>所有接口（<code>/api/v1/health</code> 除外）均需携带 API Key。支持两种传递方式：</p>
    <div class="methods">
      <div class="method">
        <div class="label">方式一：Header（推荐）</div>
        <code>X-API-Key: your-api-key</code>
      </div>
      <div class="method">
        <div class="label">方式二：Query 参数</div>
        <code>?api_key=your-api-key</code>
      </div>
    </div>
  </div>
</div>

<!-- ======== RS Rating 排行 ======== -->
<div class="section" id="ep-rs-rating">
  <h2>接口列表</h2>

  <div class="endpoint open" id="card-rs-rating">
    <div class="ep-header" onclick="toggleCard(this)">
      <span class="ep-method get">GET</span>
      <span class="ep-path">/api/v1/stocks/rs_rating</span>
      <span class="ep-desc">RS Rating 排行榜</span>
    </div>
    <div class="ep-body">
      <p>获取指定日期的 RS Rating 排行榜数据，支持按评级过滤和限制返回数量。</p>

      <h3>请求参数</h3>
      <table>
        <tr><th>参数</th><th>类型</th><th>默认</th><th>说明</th></tr>
        <tr><td><code>top_n</code></td><td>int</td><td>100</td><td>返回前 N 名 <span class="optional">(1~5000)</span></td></tr>
        <tr><td><code>min_rating</code></td><td>int</td><td>—</td><td>最低 RS Rating <span class="optional">(1~99)</span></td></tr>
        <tr><td><code>target_date</code></td><td>date</td><td>今天</td><td>查询日期，格式 <code>YYYY-MM-DD</code></td></tr>
      </table>

      <div class="response-label">成功响应 200</div>
<pre>{
  "count": 20,
  "date": "2026-02-24",
  "items": [
    {
      "ts_code": "600519.SH",
      "name": "贵州茅台",
      "trade_date": "2026-02-24",
      "rs_rating": 98,
      "score": 95.2,
      "close": 1850.00,
      "pct_change": 2.35,
      "change": 42.50,
      "p3": 0.15,
      "p6": 0.28,
      "p9": 0.35,
      "p12": 0.42
    }
  ]
}</pre>

      <div class="response-label">字段说明</div>
      <table>
        <tr><th>字段</th><th>类型</th><th>说明</th></tr>
        <tr><td><code>ts_code</code></td><td>string</td><td>股票代码（如 600519.SH）</td></tr>
        <tr><td><code>name</code></td><td>string</td><td>股票名称</td></tr>
        <tr><td><code>trade_date</code></td><td>date</td><td>数据对应的交易日期</td></tr>
        <tr><td><code>rs_rating</code></td><td>int</td><td>RS 评级（1~99，越高越强）</td></tr>
        <tr><td><code>score</code></td><td>float</td><td>加权原始分</td></tr>
        <tr><td><code>close</code></td><td>float</td><td>收盘价</td></tr>
        <tr><td><code>pct_change</code></td><td>float</td><td>涨跌幅（%）</td></tr>
        <tr><td><code>change</code></td><td>float</td><td>涨跌额</td></tr>
        <tr><td><code>p3 / p6 / p9 / p12</code></td><td>float</td><td>3/6/9/12 个月涨幅</td></tr>
      </table>

      <div class="try-it">
        <h4>在线测试</h4>
        <div class="params">
          <div><label>X-API-Key</label><input id="t1-key" type="text" placeholder="your-api-key"></div>
          <div><label>top_n</label><input id="t1-topn" type="number" value="20"></div>
          <div><label>min_rating</label><input id="t1-minr" type="number" value="80"></div>
          <div><label>target_date</label><input id="t1-date" type="date"></div>
        </div>
        <button onclick="tryRsRating()">发送请求</button>
        <div class="try-result" id="t1-result"></div>
      </div>
    </div>
  </div>

  <!-- ======== 股票搜索 ======== -->
  <div class="endpoint" id="ep-search">
    <div class="ep-header" onclick="toggleCard(this)">
      <span class="ep-method get">GET</span>
      <span class="ep-path">/api/v1/stocks/search</span>
      <span class="ep-desc">搜索股票 RS Rating</span>
    </div>
    <div class="ep-body">
      <p>按股票代码、名称或拼音首字母搜索，返回匹配股票的 RS Rating 信息。仅返回 RS Rating ≥ 80 的结果。</p>

      <h3>请求参数</h3>
      <table>
        <tr><th>参数</th><th>类型</th><th>默认</th><th>说明</th></tr>
        <tr><td><code>q</code></td><td>string</td><td>— <span class="required">必填</span></td><td>搜索关键词（代码/名称/拼音首字母，1~20字符）</td></tr>
        <tr><td><code>target_date</code></td><td>date</td><td>今天</td><td>查询日期，格式 <code>YYYY-MM-DD</code></td></tr>
      </table>

      <div class="response-label">成功响应 200</div>
<pre>{
  "count": 1,
  "date": "2026-02-24",
  "items": [
    {
      "ts_code": "600519.SH",
      "name": "贵州茅台",
      "rs_rating": 98,
      ...
    }
  ],
  "message": null
}</pre>

      <div class="response-label">message 说明</div>
      <table>
        <tr><th>值</th><th>含义</th></tr>
        <tr><td><code>null</code></td><td>有匹配结果</td></tr>
        <tr><td><code>"您搜索的标的 RS Rating ≤80"</code></td><td>匹配到股票但评级均低于 80</td></tr>
        <tr><td><code>"未找到匹配「xxx」的股票"</code></td><td>无匹配结果</td></tr>
      </table>

      <div class="try-it">
        <h4>在线测试</h4>
        <div class="params">
          <div><label>X-API-Key</label><input id="t2-key" type="text" placeholder="your-api-key"></div>
          <div><label>q <span class="required">必填</span></label><input id="t2-q" type="text" placeholder="600519 / 茅台 / MT"></div>
          <div><label>target_date</label><input id="t2-date" type="date"></div>
        </div>
        <button onclick="trySearch()">发送请求</button>
        <div class="try-result" id="t2-result"></div>
      </div>
    </div>
  </div>

  <!-- ======== 计算状态 ======== -->
  <div class="endpoint" id="ep-status">
    <div class="ep-header" onclick="toggleCard(this)">
      <span class="ep-method get">GET</span>
      <span class="ep-path">/api/v1/stocks/rs_rating/status</span>
      <span class="ep-desc">计算任务状态</span>
    </div>
    <div class="ep-body">
      <p>查询后台 RS Rating 计算任务的运行状态。</p>

      <h3>请求参数</h3>
      <p style="color:var(--text2);font-size:13px">无参数</p>

      <div class="response-label">成功响应 200</div>
<pre>{
  "status": "completed",
  "started_at": "2026-02-25T10:00:00",
  "finished_at": "2026-02-25T10:05:00",
  "count": 5452,
  "message": "RS Rating 计算完成，共 5452 只股票"
}</pre>

      <div class="response-label">status 枚举值</div>
      <table>
        <tr><th>值</th><th>说明</th></tr>
        <tr><td><code>idle</code></td><td>无任务运行</td></tr>
        <tr><td><code>running</code></td><td>计算进行中（额外返回 <code>elapsed_seconds</code>）</td></tr>
        <tr><td><code>completed</code></td><td>计算完成（额外返回 <code>count</code>）</td></tr>
        <tr><td><code>failed</code></td><td>计算失败（额外返回 <code>error</code>）</td></tr>
      </table>

      <div class="try-it">
        <h4>在线测试</h4>
        <div class="params">
          <div><label>X-API-Key</label><input id="t3-key" type="text" placeholder="your-api-key"></div>
        </div>
        <button onclick="tryStatus()">发送请求</button>
        <div class="try-result" id="t3-result"></div>
      </div>
    </div>
  </div>

  <!-- ======== 触发计算 ======== -->
  <div class="endpoint" id="ep-compute">
    <div class="ep-header" onclick="toggleCard(this)">
      <span class="ep-method post">POST</span>
      <span class="ep-path">/api/v1/stocks/rs_rating/compute</span>
      <span class="ep-desc">触发 RS Rating 计算</span>
    </div>
    <div class="ep-body">
      <p>手动触发后台 RS Rating 计算任务。接口立即返回 202，计算在后台异步执行。</p>

      <h3>请求参数</h3>
      <table>
        <tr><th>参数</th><th>类型</th><th>默认</th><th>说明</th></tr>
        <tr><td><code>force</code></td><td>bool</td><td>false</td><td>是否强制重新计算</td></tr>
      </table>

      <div class="response-label">成功响应 202</div>
<pre>{
  "status": "accepted",
  "message": "RS Rating 计算已在后台启动，请通过 GET /api/v1/stocks/rs_rating/status 查看进度"
}</pre>

      <div class="response-label">冲突响应 409</div>
<pre>{
  "status": "conflict",
  "message": "已有计算任务在运行中，请通过 GET /rs_rating/status 查看进度"
}</pre>

      <div class="try-it">
        <h4>在线测试</h4>
        <div class="params">
          <div><label>X-API-Key</label><input id="t4-key" type="text" placeholder="your-api-key"></div>
          <div><label>force</label>
            <select id="t4-force" style="width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:var(--mono);font-size:13px">
              <option value="false">false</option>
              <option value="true">true</option>
            </select>
          </div>
        </div>
        <button onclick="tryCompute()">发送请求</button>
        <div class="try-result" id="t4-result"></div>
      </div>
    </div>
  </div>
</div>

<!-- ======== 错误码 ======== -->
<div class="section" id="errors">
  <h2>错误响应</h2>
  <div class="error-grid">
    <div class="error-card">
      <div class="status s401">401 Unauthorized</div>
      <pre>{"error":"unauthorized","message":"缺少 API Key，请在 Header 中传递 X-API-Key 或 Query 中传递 api_key"}</pre>
    </div>
    <div class="error-card">
      <div class="status s403">403 Forbidden</div>
      <pre>{"error":"forbidden","message":"API Key 无效"}</pre>
    </div>
  </div>
</div>

<!-- ======== 调用示例 ======== -->
<div class="section" id="examples">
  <h2>调用示例</h2>

  <h3>cURL</h3>
<pre># 获取 RS Rating Top 20（评级 ≥ 80）
curl -H "X-API-Key: YOUR_KEY" \
  "https://alphareader.site/api/v1/stocks/rs_rating?top_n=20&amp;min_rating=80"

# 搜索股票
curl -H "X-API-Key: YOUR_KEY" \
  "https://alphareader.site/api/v1/stocks/search?q=600519"

# 触发计算
curl -X POST -H "X-API-Key: YOUR_KEY" \
  "https://alphareader.site/api/v1/stocks/rs_rating/compute?force=true"

# 查看计算状态
curl -H "X-API-Key: YOUR_KEY" \
  "https://alphareader.site/api/v1/stocks/rs_rating/status"</pre>

  <h3>Python</h3>
<pre>import requests

API_KEY = "YOUR_KEY"
BASE = "https://alphareader.site/api/v1"
headers = {"X-API-Key": API_KEY}

# 获取 RS Rating 排行
resp = requests.get(f"{BASE}/stocks/rs_rating",
                    params={"top_n": 50, "min_rating": 85},
                    headers=headers)
data = resp.json()
for item in data["items"]:
    print(f"{item['ts_code']} {item['name']} RS={item['rs_rating']}")</pre>

  <h3>JavaScript</h3>
<pre>const API_KEY = 'YOUR_KEY';
const BASE = 'https://alphareader.site/api/v1';

const resp = await fetch(
  `${BASE}/stocks/rs_rating?top_n=20&min_rating=80`,
  { headers: { 'X-API-Key': API_KEY } }
);
const data = await resp.json();
console.log(`共 ${data.count} 只股票，日期 ${data.date}`);
data.items.forEach(s =>
  console.log(`${s.ts_code} ${s.name} RS=${s.rs_rating}`)
);</pre>
</div>

</div><!-- container -->

<script>
const _API_KEY = '{{ api_key }}';

function toggleCard(header) {
  header.closest('.endpoint').classList.toggle('open');
}

function getKey(inputId) {
  return document.getElementById(inputId).value || _API_KEY || '';
}

async function doRequest(method, url, key, resultId) {
  const el = document.getElementById(resultId);
  el.innerHTML = '<div class="try-meta">请求中...</div>';
  const t0 = performance.now();
  try {
    const h = {};
    if (key) h['X-API-Key'] = key;
    const r = await fetch(url, { method, headers: h });
    const ms = (performance.now() - t0).toFixed(0);
    const json = await r.json();
    el.innerHTML = `<div class="try-meta">${r.status} · ${ms}ms</div><pre>${JSON.stringify(json, null, 2)}</pre>`;
  } catch (e) {
    el.innerHTML = `<div class="try-meta" style="color:var(--red)">请求失败: ${e.message}</div>`;
  }
}

function tryRsRating() {
  const key = getKey('t1-key');
  const topn = document.getElementById('t1-topn').value || '20';
  const minr = document.getElementById('t1-minr').value;
  const dt = document.getElementById('t1-date').value;
  let url = `/api/v1/stocks/rs_rating?top_n=${topn}`;
  if (minr) url += `&min_rating=${minr}`;
  if (dt) url += `&target_date=${dt}`;
  doRequest('GET', url, key, 't1-result');
}

function trySearch() {
  const key = getKey('t2-key');
  const q = document.getElementById('t2-q').value;
  if (!q) { alert('请输入搜索关键词'); return; }
  const dt = document.getElementById('t2-date').value;
  let url = `/api/v1/stocks/search?q=${encodeURIComponent(q)}`;
  if (dt) url += `&target_date=${dt}`;
  doRequest('GET', url, key, 't2-result');
}

function tryStatus() {
  doRequest('GET', '/api/v1/stocks/rs_rating/status', getKey('t3-key'), 't3-result');
}

function tryCompute() {
  const key = getKey('t4-key');
  const force = document.getElementById('t4-force').value;
  doRequest('POST', `/api/v1/stocks/rs_rating/compute?force=${force}`, key, 't4-result');
}

// 自动填充 API Key
window.addEventListener('DOMContentLoaded', () => {
  if (_API_KEY) {
    ['t1-key','t2-key','t3-key','t4-key'].forEach(id => {
      document.getElementById(id).value = _API_KEY;
    });
  }
});
</script>
</body>
</html>"""


@router.get("/api-docs", response_class=HTMLResponse, include_in_schema=False)
async def api_docs_page():
    """RS Rating API 文档页面。"""
    html = _API_DOCS_HTML.replace("{{ api_key }}", settings.NEWS_API_KEY or "")
    return HTMLResponse(html)
