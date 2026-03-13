"""Dashboard — 统计仪表盘（密码保护的独立 HTML 页面）。

访问 /dashboard 时：
  1. 未登录 → 显示密码输入页
  2. 输入正确密码 → 设置 cookie（2h 有效），跳转仪表盘
  3. 仪表盘页面通过 JS 调用 /api/v1/analytics/* 获取数据，用 Chart.js 渲染
"""

import hashlib
import secrets
import time

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings

router = APIRouter(tags=["dashboard"])

# 简单的 token 签名：HMAC(password + timestamp)
_TOKEN_TTL = 7200  # 2 小时


def _make_token() -> str:
    ts = str(int(time.time()))
    sig = hashlib.sha256(f"{settings.DASHBOARD_PASSWORD}:{ts}".encode()).hexdigest()[:16]
    return f"{ts}:{sig}"


def _verify_token(token: str) -> bool:
    if not token or not settings.DASHBOARD_PASSWORD:
        return False
    try:
        ts_str, sig = token.split(":", 1)
        ts = int(ts_str)
        if time.time() - ts > _TOKEN_TTL:
            return False
        expected = hashlib.sha256(f"{settings.DASHBOARD_PASSWORD}:{ts_str}".encode()).hexdigest()[:16]
        return secrets.compare_digest(sig, expected)
    except Exception:
        return False


# ── 登录页 ──

LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:#f0f2f5;font-family:'SF Pro Display','PingFang SC',sans-serif}
.card{background:#fff;padding:48px 40px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);
  width:360px;text-align:center}
h2{font-size:22px;color:#1a1a2e;margin-bottom:8px}
.sub{color:#8c8c9a;font-size:14px;margin-bottom:32px}
input{width:100%;padding:14px 16px;border:1.5px solid #e0e0e8;border-radius:10px;font-size:16px;
  outline:none;transition:border .2s;margin-bottom:16px}
input:focus{border-color:#1a1a2e}
button{width:100%;padding:14px;background:#1a1a2e;color:#fff;border:none;border-radius:10px;
  font-size:16px;font-weight:600;cursor:pointer;transition:background .2s}
button:hover{background:#2d2d4e}
.err{color:#e53935;font-size:13px;margin-top:12px;display:none}
</style>
</head>
<body>
<div class="card">
  <h2>AlphaReader Dashboard</h2>
  <p class="sub">请输入访问密码</p>
  <form method="POST" action="/dashboard/login">
    <input type="password" name="password" placeholder="密码" autofocus required>
    <button type="submit">进入</button>
  </form>
  <p class="err" id="err">密码错误</p>
</div>
<script>
if(location.search.includes('error=1'))document.getElementById('err').style.display='block';
</script>
</body></html>"""


@router.get("/dashboard/login", response_class=HTMLResponse)
async def dashboard_login_page():
    if not settings.DASHBOARD_PASSWORD:
        return RedirectResponse("/dashboard")
    return HTMLResponse(LOGIN_HTML)


from starlette.requests import Request


@router.post("/dashboard/login", response_class=HTMLResponse)
async def dashboard_do_login(request: Request):
    form = await request.form()
    pwd = form.get("password", "")
    if pwd == settings.DASHBOARD_PASSWORD and settings.DASHBOARD_PASSWORD:
        token = _make_token()
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("dash_token", token, max_age=_TOKEN_TTL, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/dashboard/login?error=1", status_code=303)


# ── 仪表盘主页 ──

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AlphaReader Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f0f2f5;--card:#fff;--text:#1a1a2e;--muted:#8c8c9a;--border:#e8e8f0;
  --blue:#3b82f6;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'SF Pro Display','PingFang SC',-apple-system,sans-serif;
  padding:24px;max-width:1200px;margin:0 auto}
h1{font-size:26px;font-weight:800;margin-bottom:4px}
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}
.header-left h1{display:inline}
.header-right select{padding:8px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:14px;
  background:#fff;cursor:pointer}
.sub{color:var(--muted);font-size:14px;margin-bottom:24px}
.tabs{display:flex;gap:8px;margin-bottom:24px}
.tab{padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;
  border:1.5px solid var(--border);background:#fff;color:var(--muted);transition:all .2s}
.tab.active{background:var(--text);color:#fff;border-color:var(--text)}
.tab:hover:not(.active){background:#f8f8fc}
.section{display:none}.section.active{display:block}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.kpi{background:var(--card);border-radius:var(--radius);padding:20px 24px;
  box-shadow:0 1px 8px rgba(0,0,0,.04)}
.kpi-label{font-size:13px;color:var(--muted);margin-bottom:6px}
.kpi-value{font-size:28px;font-weight:800;line-height:1.2}
.kpi-value.blue{color:var(--blue)}.kpi-value.green{color:var(--green)}
.kpi-value.amber{color:var(--amber)}.kpi-value.red{color:var(--red)}
.chart-card{background:var(--card);border-radius:var(--radius);padding:24px;
  box-shadow:0 1px 8px rgba(0,0,0,.04);margin-bottom:24px}
.chart-card h3{font-size:16px;margin-bottom:16px}
canvas{max-height:300px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;padding:10px 12px;border-bottom:2px solid var(--border);color:var(--muted);font-weight:600}
td{padding:10px 12px;border-bottom:1px solid var(--border)}
tr:hover td{background:#f8f8fc}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600}
.badge-ok{background:#dcfce7;color:#16a34a}.badge-err{background:#fee2e2;color:#dc2626}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:14px}
.loading{text-align:center;padding:60px;color:var(--muted)}
@media(max-width:600px){body{padding:16px}.kpi-row{grid-template-columns:1fr 1fr}
  .kpi-value{font-size:22px}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left"><h1>AlphaReader Dashboard</h1></div>
  <div class="header-right">
    <select id="daysPicker" onchange="refresh()">
      <option value="1">今天</option>
      <option value="7" selected>近 7 天</option>
      <option value="30">近 30 天</option>
    </select>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('user')">用户行为</div>
  <div class="tab" onclick="switchTab('pipeline')">Pipeline 爬取</div>
</div>

<!-- ═══ 用户行为 Tab ═══ -->
<div id="section-user" class="section active">
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">页面访问量 (PV)</div><div class="kpi-value blue" id="kpi-pv">-</div></div>
    <div class="kpi"><div class="kpi-label">新闻点击量</div><div class="kpi-value green" id="kpi-click">-</div></div>
    <div class="kpi"><div class="kpi-label">新闻曝光量</div><div class="kpi-value amber" id="kpi-imp">-</div></div>
    <div class="kpi"><div class="kpi-label">平均停留时长</div><div class="kpi-value" id="kpi-dur">-</div></div>
  </div>
  <div class="chart-card"><h3>趋势</h3><canvas id="userTrendChart"></canvas></div>
  <div class="chart-card">
    <h3>热门新闻 Top 10（按点击）</h3>
    <table>
      <thead><tr><th>#</th><th>标题</th><th>曝光</th><th>点击</th><th>CTR</th></tr></thead>
      <tbody id="topNewsBody"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ═══ Pipeline Tab ═══ -->
<div id="section-pipeline" class="section">
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">运行次数</div><div class="kpi-value blue" id="kpi-runs">-</div></div>
    <div class="kpi"><div class="kpi-label">抓取总量</div><div class="kpi-value green" id="kpi-fetched">-</div></div>
    <div class="kpi"><div class="kpi-label">入库总量</div><div class="kpi-value amber" id="kpi-stored">-</div></div>
    <div class="kpi"><div class="kpi-label">保留率</div><div class="kpi-value" id="kpi-retention">-</div></div>
  </div>
  <div class="chart-card">
    <h3>各信源统计</h3>
    <canvas id="sourceChart"></canvas>
    <table style="margin-top:16px">
      <thead><tr><th>信源</th><th>抓取</th><th>通过</th><th>保留率</th></tr></thead>
      <tbody id="sourceBody"><tr><td colspan="4" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
  <div class="chart-card"><h3>评分分布</h3><canvas id="scoreChart"></canvas></div>
  <div class="chart-card">
    <h3>最近运行记录</h3>
    <div style="overflow-x:auto">
    <table>
      <thead><tr><th>时间</th><th>耗时</th><th>抓取</th><th>去重</th><th>评分通过</th><th>入库</th><th>状态</th></tr></thead>
      <tbody id="runsBody"><tr><td colspan="7" class="empty">加载中...</td></tr></tbody>
    </table>
    </div>
  </div>
</div>

<script>
const API = '/api/v1/analytics';
const _API_KEY = '{{ api_key }}';
let userTrendChart, sourceChart, scoreChart;

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',i===(name==='user'?0:1))});
  document.querySelectorAll('.section').forEach((s,i)=>{s.classList.toggle('active',i===(name==='user'?0:1))});
}

function getDays(){ return document.getElementById('daysPicker').value }

function fmtDur(sec){
  if(sec<60) return sec+'s';
  const m=Math.floor(sec/60),s=Math.round(sec%60);
  return m+'m '+s+'s';
}

function fmtTime(iso){
  const d=new Date(iso);
  return d.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}

async function fetchJSON(url){
  const h=_API_KEY?{'X-API-Key':_API_KEY}:{};
  const r=await fetch(url,{headers:h});
  if(!r.ok) throw new Error(r.status);
  return r.json();
}

async function loadUserStats(){
  try{
    const d=await fetchJSON(`${API}/user_stats?days=${getDays()}`);
    document.getElementById('kpi-pv').textContent=d.today.page_view.toLocaleString();
    document.getElementById('kpi-click').textContent=d.today.news_click.toLocaleString();
    document.getElementById('kpi-imp').textContent=d.today.news_impression.toLocaleString();
    document.getElementById('kpi-dur').textContent=fmtDur(d.today.avg_duration_sec);

    // 趋势图
    const dates=Object.keys(d.trend).sort();
    const pvData=dates.map(dt=>(d.trend[dt]||{}).page_view||0);
    const clickData=dates.map(dt=>(d.trend[dt]||{}).news_click||0);
    const labels=dates.map(dt=>dt.slice(5));

    if(userTrendChart) userTrendChart.destroy();
    userTrendChart=new Chart(document.getElementById('userTrendChart'),{
      type:'line',
      data:{labels,datasets:[
        {label:'PV',data:pvData,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,.1)',fill:true,tension:.3},
        {label:'点击',data:clickData,borderColor:'#22c55e',backgroundColor:'rgba(34,197,94,.1)',fill:true,tension:.3}
      ]},
      options:{responsive:true,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true}}}
    });

    // Top News
    const tbody=document.getElementById('topNewsBody');
    if(!d.top_news||d.top_news.length===0){
      tbody.innerHTML='<tr><td colspan="5" class="empty">暂无数据</td></tr>';
    }else{
      tbody.innerHTML=d.top_news.map((n,i)=>`<tr>
        <td>${i+1}</td>
        <td style="max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${n.title}</td>
        <td>${n.impressions}</td><td>${n.clicks}</td><td>${n.ctr}%</td>
      </tr>`).join('');
    }
  }catch(e){console.error('loadUserStats',e)}
}

async function loadPipelineStats(){
  try{
    const d=await fetchJSON(`${API}/pipeline_stats?days=${getDays()}`);
    const o=d.overview;
    document.getElementById('kpi-runs').textContent=o.runs.toLocaleString();
    document.getElementById('kpi-fetched').textContent=o.total_fetched.toLocaleString();
    document.getElementById('kpi-stored').textContent=o.total_stored.toLocaleString();
    document.getElementById('kpi-retention').textContent=o.retention_rate+'%';

    // 信源柱状图
    const srcLabels=d.by_source.map(s=>s.source);
    const srcFetched=d.by_source.map(s=>s.fetched);
    const srcPassed=d.by_source.map(s=>s.passed);
    if(sourceChart) sourceChart.destroy();
    sourceChart=new Chart(document.getElementById('sourceChart'),{
      type:'bar',
      data:{labels:srcLabels,datasets:[
        {label:'抓取',data:srcFetched,backgroundColor:'rgba(59,130,246,.7)'},
        {label:'通过',data:srcPassed,backgroundColor:'rgba(34,197,94,.7)'}
      ]},
      options:{responsive:true,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true}}}
    });

    // 信源表格
    const srcBody=document.getElementById('sourceBody');
    if(d.by_source.length===0){
      srcBody.innerHTML='<tr><td colspan="4" class="empty">暂无数据</td></tr>';
    }else{
      srcBody.innerHTML=d.by_source.map(s=>`<tr>
        <td>${s.source}</td><td>${s.fetched}</td><td>${s.passed}</td><td>${s.retention}%</td>
      </tr>`).join('');
    }

    // 评分分布饼图
    const scoreLabels=Object.keys(d.score_distribution).map(k=>k+'分');
    const scoreData=Object.values(d.score_distribution);
    const colors=['#94a3b8','#a0a0b0','#5ac778','#f0b429','#ff9500','#e53935'];
    if(scoreChart) scoreChart.destroy();
    scoreChart=new Chart(document.getElementById('scoreChart'),{
      type:'doughnut',
      data:{labels:scoreLabels,datasets:[{data:scoreData,
        backgroundColor:scoreLabels.map((_,i)=>colors[i%colors.length])}]},
      options:{responsive:true,plugins:{legend:{position:'bottom'}}}
    });

    // 运行记录表
    const runsBody=document.getElementById('runsBody');
    if(!d.recent_runs||d.recent_runs.length===0){
      runsBody.innerHTML='<tr><td colspan="7" class="empty">暂无数据</td></tr>';
    }else{
      runsBody.innerHTML=d.recent_runs.map(r=>{
        const hasErr=r.errors&&r.errors.length>0;
        const badge=hasErr?'<span class="badge badge-err">有错误</span>':'<span class="badge badge-ok">成功</span>';
        return `<tr>
          <td>${fmtTime(r.started_at)}</td><td>${r.duration_sec}s</td>
          <td>${r.fetched}</td><td>${r.deduped}</td><td>${r.scored}</td><td>${r.stored}</td>
          <td>${badge}</td>
        </tr>`;
      }).join('');
    }
  }catch(e){console.error('loadPipelineStats',e)}
}

function refresh(){loadUserStats();loadPipelineStats()}
refresh();
</script>
</body></html>"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(dash_token: str = Cookie(None)):
    # 如果设置了密码且 token 验证失败，跳转登录
    if settings.DASHBOARD_PASSWORD and not _verify_token(dash_token or ""):
        return RedirectResponse("/dashboard/login", status_code=303)
    html = DASHBOARD_HTML.replace("{{ api_key }}", settings.NEWS_API_KEY or "")
    return HTMLResponse(html)
