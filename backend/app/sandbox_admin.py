"""模拟仓后台管理 — 密码保护的独立 HTML 页面。

复用 Dashboard 的 cookie 认证机制。
路径: /sandbox-admin
功能: 管理观察池、录入推演、录入交易、触发NAV计算
"""

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dashboard import _verify_token

router = APIRouter(tags=["sandbox-admin"])

SANDBOX_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>模拟仓管理</title>
<style>
:root{--bg:#f0f2f5;--card:#fff;--text:#1a1a2e;--muted:#8c8c9a;--border:#e8e8f0;
  --blue:#3b82f6;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:'SF Pro Display','PingFang SC',-apple-system,sans-serif;
  padding:24px;max-width:1100px;margin:0 auto}
h1{font-size:26px;font-weight:800;margin-bottom:4px}
.header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}
.sub{color:var(--muted);font-size:14px;margin-bottom:24px}
.tabs{display:flex;gap:8px;margin-bottom:24px}
.tab{padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;
  border:1.5px solid var(--border);background:#fff;color:var(--muted);transition:all .2s}
.tab.active{background:var(--text);color:#fff;border-color:var(--text)}
.tab:hover:not(.active){background:#f8f8fc}
.section{display:none}.section.active{display:block}
.card{background:var(--card);border-radius:var(--radius);padding:24px;
  box-shadow:0 1px 8px rgba(0,0,0,.04);margin-bottom:24px}
.card h3{font-size:16px;margin-bottom:16px}
.form-row{display:flex;gap:12px;margin-bottom:12px;align-items:flex-end;flex-wrap:wrap}
.form-group{display:flex;flex-direction:column;gap:4px;flex:1;min-width:140px}
.form-group label{font-size:13px;color:var(--muted);font-weight:600}
.form-group input,.form-group select,.form-group textarea{padding:10px 14px;border:1.5px solid var(--border);
  border-radius:8px;font-size:14px;outline:none;transition:border .2s;background:#fff;font-family:inherit}
.form-group input:focus,.form-group select:focus,.form-group textarea:focus{border-color:var(--blue)}
.form-group textarea{min-height:80px;resize:vertical}
.btn{padding:10px 24px;border:none;border-radius:8px;font-size:14px;font-weight:600;
  cursor:pointer;transition:all .2s;white-space:nowrap}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-danger{background:var(--red);color:#fff}
.btn-danger:hover{background:#dc2626}
.btn-green{background:var(--green);color:#fff}
.btn-green:hover{background:#16a34a}
.btn-sm{padding:6px 14px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;padding:10px 12px;border-bottom:2px solid var(--border);color:var(--muted);font-weight:600}
td{padding:10px 12px;border-bottom:1px solid var(--border)}
tr:hover td{background:#f8f8fc}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600}
.badge-holding{background:#dcfce7;color:#16a34a}
.badge-watching{background:#dbeafe;color:#2563eb}
.badge-exited{background:#f3f4f6;color:#6b7280}
.badge-bullish{background:#dcfce7;color:#16a34a}
.badge-bearish{background:#fee2e2;color:#dc2626}
.badge-neutral{background:#f3f4f6;color:#6b7280}
.badge-buy{background:#dcfce7;color:#16a34a}
.badge-sell{background:#fee2e2;color:#dc2626}
.toast{position:fixed;top:24px;right:24px;padding:14px 24px;border-radius:10px;
  color:#fff;font-size:14px;font-weight:600;z-index:9999;opacity:0;transition:opacity .3s;
  pointer-events:none}
.toast.show{opacity:1}
.toast-ok{background:var(--green)}
.toast-err{background:var(--red)}
.empty{color:var(--muted);text-align:center;padding:40px;font-size:14px}
@media(max-width:600px){body{padding:16px}.form-row{flex-direction:column}}
</style>
</head>
<body>

<div class="header">
  <div><h1>模拟仓管理</h1></div>
  <a href="/dashboard" style="color:var(--blue);font-size:14px;text-decoration:none">← 返回 Dashboard</a>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('stocks')">观察池</div>
  <div class="tab" onclick="switchTab('analysis')">录入推演</div>
  <div class="tab" onclick="switchTab('trade')">录入交易</div>
  <div class="tab" onclick="switchTab('nav')">净值计算</div>
</div>

<div id="toast" class="toast"></div>

<!-- ═══ 观察池 Tab ═══ -->
<div id="section-stocks" class="section active">
  <div class="card">
    <h3>添加股票到观察池</h3>
    <div class="form-row">
      <div class="form-group"><label>股票代码</label><input id="add-code" placeholder="如 000001"></div>
      <div class="form-group"><label>名称</label><input id="add-name" placeholder="如 平安银行"></div>
      <div class="form-group" style="flex:2"><label>加入理由</label><input id="add-reason" placeholder="可选"></div>
      <button class="btn btn-primary" onclick="addStock()">添加</button>
    </div>
  </div>
  <div class="card">
    <h3>观察池列表</h3>
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>状态</th><th>理由</th><th>加入时间</th><th>操作</th></tr></thead>
      <tbody id="stocksBody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ═══ 录入推演 Tab ═══ -->
<div id="section-analysis" class="section">
  <div class="card">
    <h3>新增推演记录</h3>
    <div class="form-row">
      <div class="form-group"><label>选择股票</label><select id="a-stock"></select></div>
      <div class="form-group"><label>方向</label>
        <select id="a-direction">
          <option value="bullish">看多</option>
          <option value="bearish">看空</option>
          <option value="neutral">中性</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:3"><label>标题</label><input id="a-title" placeholder="推演标题"></div>
      <div class="form-group"><label>目标价</label><input id="a-target" type="number" step="0.01" placeholder="可选"></div>
      <div class="form-group"><label>止损价</label><input id="a-stoploss" type="number" step="0.01" placeholder="可选"></div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>摘要</label><textarea id="a-summary" placeholder="简要分析结论"></textarea></div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>正文 (Markdown, 可选)</label><textarea id="a-content" rows="6" placeholder="详细分析..."></textarea></div>
    </div>
    <div class="form-row">
      <button class="btn btn-primary" onclick="addAnalysis()">提交推演</button>
    </div>
  </div>
  <div class="card">
    <h3>最近推演记录</h3>
    <div id="analysisHistory" class="empty">加载中...</div>
  </div>
</div>

<!-- ═══ 录入交易 Tab ═══ -->
<div id="section-trade" class="section">
  <div class="card">
    <h3>新增交易</h3>
    <div class="form-row">
      <div class="form-group"><label>选择股票</label><select id="t-stock"></select></div>
      <div class="form-group"><label>操作</label>
        <select id="t-action">
          <option value="buy">买入</option>
          <option value="sell">卖出</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>价格</label><input id="t-price" type="number" step="0.01"></div>
      <div class="form-group"><label>股数</label><input id="t-shares" type="number" step="100" placeholder="如 1000"></div>
      <div class="form-group"><label>交易日期</label><input id="t-date" type="date"></div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:2"><label>备注</label><input id="t-note" placeholder="可选"></div>
      <button class="btn btn-green" onclick="addTrade()">提交交易</button>
    </div>
  </div>
  <div class="card">
    <h3>最近交易记录</h3>
    <table>
      <thead><tr><th>日期</th><th>代码</th><th>操作</th><th>价格</th><th>股数</th><th>备注</th></tr></thead>
      <tbody id="tradesBody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ═══ 净值计算 Tab ═══ -->
<div id="section-nav" class="section">
  <div class="card">
    <h3>触发 NAV 计算</h3>
    <div class="form-row">
      <div class="form-group"><label>计算日期 (默认今天)</label><input id="nav-date" type="date"></div>
      <button class="btn btn-primary" onclick="computeNav()">计算净值</button>
    </div>
    <div id="nav-result" style="margin-top:16px"></div>
  </div>
</div>

<script>
const API='/api/v1/sandbox';
let allStocks=[];

function switchTab(name){
  const tabs=['stocks','analysis','trade','nav'];
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',tabs[i]===name)});
  document.querySelectorAll('.section').forEach((s,i)=>{s.classList.toggle('active',tabs[i]===name)});
}

function showToast(msg,ok=true){
  const t=document.getElementById('toast');
  t.textContent=msg;
  t.className='toast show '+(ok?'toast-ok':'toast-err');
  setTimeout(()=>{t.className='toast'},3000);
}

function fmtDate(iso){
  if(!iso) return '-';
  return new Date(iso).toLocaleDateString('zh-CN');
}

async function api(path,opts={}){
  const r=await fetch(API+path,{
    method:opts.method||'GET',
    headers:opts.body?{'Content-Type':'application/json'}:{},
    body:opts.body?JSON.stringify(opts.body):undefined,
    credentials:'same-origin',
  });
  if(!r.ok){
    const e=await r.json().catch(()=>({}));
    throw new Error(e.detail||r.status);
  }
  return r.json();
}

// ── 观察池 ──

async function loadStocks(){
  try{
    const d=await api('/stocks');
    allStocks=d.items||[];
    renderStocks();
    populateStockSelects();
  }catch(e){console.error(e)}
}

function statusBadge(s){
  const m={holding:'badge-holding',watching:'badge-watching',exited:'badge-exited'};
  const l={holding:'持仓',watching:'观察',exited:'退出'};
  return `<span class="badge ${m[s]||''}">${l[s]||s}</span>`;
}

function renderStocks(){
  const body=document.getElementById('stocksBody');
  if(!allStocks.length){body.innerHTML='<tr><td colspan="6" class="empty">暂无数据</td></tr>';return;}
  body.innerHTML=allStocks.map(s=>`<tr>
    <td>${s.ts_code}</td><td>${s.name}</td><td>${statusBadge(s.status)}</td>
    <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.reason||'-'}</td>
    <td>${fmtDate(s.added_at)}</td>
    <td>${s.status!=='exited'?`<button class="btn btn-danger btn-sm" onclick="removeStock(${s.id})">退出</button>`:'-'}</td>
  </tr>`).join('');
}

function populateStockSelects(){
  const active=allStocks.filter(s=>s.status!=='exited');
  ['a-stock','t-stock'].forEach(id=>{
    const sel=document.getElementById(id);
    sel.innerHTML=active.map(s=>`<option value="${s.id}" data-code="${s.ts_code}">${s.ts_code} ${s.name}</option>`).join('');
  });
}

async function addStock(){
  const code=document.getElementById('add-code').value.trim();
  const name=document.getElementById('add-name').value.trim();
  const reason=document.getElementById('add-reason').value.trim();
  if(!code){showToast('请填写股票代码',false);return;}
  try{
    await api('/admin/stocks',{method:'POST',body:{ts_code:code,name:name,reason:reason||null}});
    showToast(`${code} 已添加`);
    document.getElementById('add-code').value='';
    document.getElementById('add-name').value='';
    document.getElementById('add-reason').value='';
    loadStocks();
  }catch(e){showToast(e.message,false)}
}

async function removeStock(id){
  if(!confirm('确认退出该股票？')) return;
  try{
    await api(`/admin/stocks/${id}`,{method:'DELETE'});
    showToast('已标记退出');
    loadStocks();
  }catch(e){showToast(e.message,false)}
}

// ── 推演 ──

async function addAnalysis(){
  const sel=document.getElementById('a-stock');
  if(!sel.value){showToast('请先添加股票',false);return;}
  const body={
    stock_id:parseInt(sel.value),
    ts_code:sel.options[sel.selectedIndex].dataset.code,
    title:document.getElementById('a-title').value.trim(),
    direction:document.getElementById('a-direction').value,
    summary:document.getElementById('a-summary').value.trim(),
    content:document.getElementById('a-content').value.trim()||null,
    target_price:parseFloat(document.getElementById('a-target').value)||null,
    stop_loss:parseFloat(document.getElementById('a-stoploss').value)||null,
  };
  if(!body.title||!body.summary){showToast('标题和摘要必填',false);return;}
  try{
    await api('/admin/analyses',{method:'POST',body});
    showToast('推演已提交');
    ['a-title','a-summary','a-content','a-target','a-stoploss'].forEach(id=>document.getElementById(id).value='');
    loadAnalysisHistory();
  }catch(e){showToast(e.message,false)}
}

async function loadAnalysisHistory(){
  const div=document.getElementById('analysisHistory');
  try{
    // 展示每只股票最新推演
    let html='';
    for(const s of allStocks.filter(s=>s.latest_analysis)){
      const a=s.latest_analysis;
      const dirBadge=`<span class="badge badge-${a.direction}">${{bullish:'看多',bearish:'看空',neutral:'中性'}[a.direction]}</span>`;
      html+=`<div style="padding:12px 0;border-bottom:1px solid var(--border)">
        <strong>${s.ts_code} ${s.name}</strong> ${dirBadge}
        <span style="color:var(--muted);font-size:12px;margin-left:8px">${fmtDate(a.created_at)}</span>
        <div style="font-size:14px;margin-top:6px"><strong>${a.title}</strong></div>
        <div style="font-size:13px;color:var(--muted);margin-top:4px">${a.summary}</div>
      </div>`;
    }
    div.innerHTML=html||'<div class="empty">暂无推演记录</div>';
  }catch(e){div.innerHTML='<div class="empty">加载失败</div>'}
}

// ── 交易 ──

async function addTrade(){
  const sel=document.getElementById('t-stock');
  if(!sel.value){showToast('请先添加股票',false);return;}
  const body={
    stock_id:parseInt(sel.value),
    ts_code:sel.options[sel.selectedIndex].dataset.code,
    action:document.getElementById('t-action').value,
    price:parseFloat(document.getElementById('t-price').value),
    shares:parseInt(document.getElementById('t-shares').value),
    trade_date:document.getElementById('t-date').value,
    note:document.getElementById('t-note').value.trim()||null,
  };
  if(!body.price||!body.shares||!body.trade_date){showToast('价格、股数、日期必填',false);return;}
  try{
    const r=await api('/admin/trades',{method:'POST',body});
    showToast(`交易已提交 (净持仓:${r.net_shares})`);
    ['t-price','t-shares','t-note'].forEach(id=>document.getElementById(id).value='');
    loadTrades();
    loadStocks(); // 刷新状态
  }catch(e){showToast(e.message,false)}
}

async function loadTrades(){
  // 展示所有持仓/观察股票的最近交易
  const body=document.getElementById('tradesBody');
  try{
    let allTrades=[];
    for(const s of allStocks){
      const d=await api(`/stocks/${s.id}`);
      if(d.trades) allTrades=allTrades.concat(d.trades.map(t=>({...t,name:s.name})));
    }
    allTrades.sort((a,b)=>b.trade_date.localeCompare(a.trade_date));
    if(!allTrades.length){body.innerHTML='<tr><td colspan="6" class="empty">暂无交易</td></tr>';return;}
    body.innerHTML=allTrades.slice(0,20).map(t=>`<tr>
      <td>${t.trade_date}</td><td>${t.ts_code||''}</td>
      <td><span class="badge badge-${t.action}">${t.action==='buy'?'买入':'卖出'}</span></td>
      <td>${t.price}</td><td>${t.shares}</td><td>${t.note||'-'}</td>
    </tr>`).join('');
  }catch(e){body.innerHTML='<tr><td colspan="6" class="empty">加载失败</td></tr>'}
}

// ── NAV ──

async function computeNav(){
  const dateVal=document.getElementById('nav-date').value;
  const div=document.getElementById('nav-result');
  div.innerHTML='<span style="color:var(--muted)">计算中...</span>';
  try{
    const params=dateVal?`?target_date=${dateVal}`:'';
    const r=await api(`/nav/compute${params}`,{method:'POST'});
    div.innerHTML=`<div style="font-size:16px;font-weight:700">
      日期: ${r.date} &nbsp;|&nbsp; NAV: <span style="color:var(--blue)">${r.nav}</span>
      &nbsp;|&nbsp; 收益: <span style="color:${r.total_pnl>=0?'var(--green)':'var(--red)'}">${r.total_pnl}%</span>
      &nbsp;|&nbsp; 市值: ¥${Number(r.market_value).toLocaleString()}
      &nbsp;|&nbsp; 现金: ¥${Number(r.cash).toLocaleString()}
    </div>`;
    showToast('NAV计算完成');
  }catch(e){div.innerHTML=`<span style="color:var(--red)">${e.message}</span>`;showToast(e.message,false)}
}

// ── Init ──
document.getElementById('t-date').value=new Date().toISOString().slice(0,10);
loadStocks().then(()=>{loadAnalysisHistory();loadTrades()});
</script>
</body></html>"""


@router.get("/sandbox-admin", response_class=HTMLResponse)
async def sandbox_admin_page(dash_token: str = Cookie(None)):
    """模拟仓管理页面 — 复用 Dashboard cookie 认证。"""
    if settings.DASHBOARD_PASSWORD and not _verify_token(dash_token or ""):
        return RedirectResponse("/dashboard/login", status_code=303)
    return HTMLResponse(SANDBOX_ADMIN_HTML)
