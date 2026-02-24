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
      <div class="form-group" style="max-width:160px"><label>综合评分 (0-5)</label>
        <input id="a-score" type="number" step="0.1" min="0" max="5" placeholder="如 3.5">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>趋势判断 (200字以内)</label>
        <textarea id="a-trend" maxlength="200" placeholder="描述当前趋势..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>形态识别 (200字以内)</label>
        <textarea id="a-pattern" maxlength="200" placeholder="描述技术形态..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>量价行为 (200字以内)</label>
        <textarea id="a-volprice" maxlength="200" placeholder="描述量价特征..."></textarea>
      </div>
    </div>

    <div style="border-top:1.5px solid var(--border);margin:16px 0;padding-top:16px">
      <h4 style="font-size:15px;margin-bottom:12px;color:var(--text)">纪律与计划</h4>
      <div class="form-row">
        <div class="form-group" style="max-width:180px"><label>动作</label>
          <select id="a-discipline">
            <option value="retain">留存</option>
            <option value="gray">灰度</option>
            <option value="research">用研</option>
            <option value="churn">流失</option>
          </select>
        </div>
        <div class="form-group" style="max-width:140px"><label>风控</label>
          <select id="a-risktype" onchange="toggleRiskFields()">
            <option value="">不设置</option>
            <option value="top">Top</option>
            <option value="bottom">Bottom</option>
          </select>
        </div>
        <div class="form-group risk-field" style="max-width:140px;display:none"><label>风控价格</label>
          <input id="a-riskprice" type="number" step="0.01" placeholder="价格">
        </div>
      </div>
      <div class="form-row risk-field" style="display:none">
        <div class="form-group" style="flex:1"><label>风控说明 (200字以内)</label>
          <textarea id="a-risknote" maxlength="200" placeholder="风控计划说明..."></textarea>
        </div>
      </div>
    </div>

    <div class="form-row">
      <div class="form-group" style="flex:1"><label>亏盈思考 (200字以内)</label>
        <textarea id="a-pnl" maxlength="200" placeholder="对亏盈的思考..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>哨子 Verdict (200字以内)</label>
        <textarea id="a-verdict" maxlength="200" placeholder="最终判断..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <button class="btn btn-primary" onclick="addAnalysis()">提交推演</button>
    </div>
  </div>
  <div class="card">
    <h3>推演记录</h3>
    <div class="form-row" style="margin-bottom:16px">
      <div class="form-group" style="max-width:260px"><label>按股票筛选</label>
        <select id="ah-filter" onchange="loadAnalysisHistory()">
          <option value="">全部股票</option>
        </select>
      </div>
    </div>
    <table>
      <thead><tr><th>日期</th><th>代码</th><th>评分</th><th>动作</th><th>哨子 Verdict</th><th>操作</th></tr></thead>
      <tbody id="analysisBody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>
    </table>
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
      <thead><tr><th>日期</th><th>代码</th><th>名称</th><th>操作</th><th>价格</th><th>股数</th><th>备注</th><th>撤回</th></tr></thead>
      <tbody id="tradesBody"><tr><td colspan="8" class="empty">加载中...</td></tr></tbody>
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
  // 推演筛选下拉框（含全部股票，不只活跃的）
  const ahFilter=document.getElementById('ah-filter');
  const current=ahFilter.value;
  ahFilter.innerHTML='<option value="">全部股票</option>'+allStocks.map(s=>`<option value="${s.id}">${s.ts_code} ${s.name}</option>`).join('');
  ahFilter.value=current;
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

function toggleRiskFields(){
  const show=!!document.getElementById('a-risktype').value;
  document.querySelectorAll('.risk-field').forEach(el=>{el.style.display=show?'':'none'});
  if(!show){document.getElementById('a-riskprice').value='';document.getElementById('a-risknote').value='';}
}

const DISCIPLINE_LABELS={retain:'留存',gray:'灰度',research:'用研',churn:'流失'};
const RISK_LABELS={top:'Top',bottom:'Bottom'};

async function addAnalysis(){
  const sel=document.getElementById('a-stock');
  if(!sel.value){showToast('请先添加股票',false);return;}
  const score=parseFloat(document.getElementById('a-score').value);
  if(isNaN(score)||score<0||score>5){showToast('评分须为 0-5',false);return;}
  const trend=document.getElementById('a-trend').value.trim();
  const pattern=document.getElementById('a-pattern').value.trim();
  const volprice=document.getElementById('a-volprice').value.trim();
  const pnl=document.getElementById('a-pnl').value.trim();
  const verdict=document.getElementById('a-verdict').value.trim();
  if(!trend||!pattern||!volprice||!pnl||!verdict){showToast('趋势/形态/量价/亏盈/哨子均为必填',false);return;}
  const riskType=document.getElementById('a-risktype').value||null;
  const body={
    stock_id:parseInt(sel.value),
    ts_code:sel.options[sel.selectedIndex].dataset.code,
    score:Math.round(score*10)/10,
    trend,pattern,volume_price:volprice,
    discipline_action:document.getElementById('a-discipline').value,
    risk_type:riskType,
    risk_price:riskType?parseFloat(document.getElementById('a-riskprice').value)||null:null,
    risk_note:riskType?document.getElementById('a-risknote').value.trim()||null:null,
    pnl_thinking:pnl,verdict,
  };
  try{
    await api('/admin/analyses',{method:'POST',body});
    showToast('推演已提交');
    ['a-score','a-trend','a-pattern','a-volprice','a-riskprice','a-risknote','a-pnl','a-verdict'].forEach(id=>document.getElementById(id).value='');
    document.getElementById('a-risktype').value='';toggleRiskFields();
    loadAnalysisHistory();
  }catch(e){showToast(e.message,false)}
}

async function loadAnalysisHistory(){
  const body=document.getElementById('analysisBody');
  const filterId=document.getElementById('ah-filter').value;
  try{
    const params=filterId?`?stock_id=${filterId}`:'';
    const d=await api(`/admin/analyses${params}`);
    const items=d.items||[];
    if(!items.length){body.innerHTML='<tr><td colspan="6" class="empty">暂无推演记录</td></tr>';return;}
    // 构建股票名称映射
    const nameMap={};
    allStocks.forEach(s=>{nameMap[s.ts_code]=s.name});
    body.innerHTML=items.map(a=>{
      const scoreBg=a.score>=4?'var(--green)':a.score>=2.5?'var(--amber)':'var(--red)';
      const actionLabel=DISCIPLINE_LABELS[a.discipline_action]||a.discipline_action;
      return `<tr>
        <td style="white-space:nowrap">${fmtDate(a.created_at)}</td>
        <td><strong>${a.ts_code}</strong><br><span style="color:var(--muted);font-size:12px">${nameMap[a.ts_code]||''}</span></td>
        <td><span style="display:inline-block;background:${scoreBg};color:#fff;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:700">${a.score}</span></td>
        <td><span class="badge badge-watching">${actionLabel}</span></td>
        <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(a.verdict||'').replace(/"/g,'&quot;')}">${a.verdict||'-'}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteAnalysis(${a.id},'${a.ts_code}')">删除</button></td>
      </tr>`;
    }).join('');
  }catch(e){body.innerHTML='<tr><td colspan="6" class="empty">加载失败</td></tr>'}
}

async function deleteAnalysis(id,code){
  if(!confirm(`确认删除 ${code} 的推演记录 #${id}？删除后不可恢复。`)) return;
  try{
    await api(`/admin/analyses/${id}`,{method:'DELETE'});
    showToast('推演记录已删除');
    loadAnalysisHistory();
    loadStocks(); // 刷新最新推演摘要
  }catch(e){showToast(e.message,false)}
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
  const body=document.getElementById('tradesBody');
  try{
    // 构建名称映射
    const nameMap={};
    allStocks.forEach(s=>{nameMap[s.ts_code]=s.name});
    let allTrades=[];
    for(const s of allStocks){
      try{
        const d=await api(`/stocks/${s.id}`);
        if(d.trades) allTrades=allTrades.concat(d.trades.map(t=>({...t,name:s.name})));
      }catch(e){console.warn('loadTrades skip',s.ts_code,e)}
    }
    allTrades.sort((a,b)=>b.trade_date.localeCompare(a.trade_date));
    if(!allTrades.length){body.innerHTML='<tr><td colspan="8" class="empty">暂无交易</td></tr>';return;}
    body.innerHTML=allTrades.slice(0,20).map(t=>`<tr>
      <td>${t.trade_date}</td><td>${t.ts_code||''}</td><td>${t.name||nameMap[t.ts_code]||''}</td>
      <td><span class="badge badge-${t.action}">${t.action==='buy'?'买入':'卖出'}</span></td>
      <td>${t.price}</td><td>${t.shares}</td><td>${t.note||'-'}</td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteTrade(${t.id},'${t.ts_code}')">撤回</button></td>
    </tr>`).join('');
  }catch(e){body.innerHTML='<tr><td colspan="8" class="empty">加载失败</td></tr>'}
}

async function deleteTrade(id,code){
  if(!confirm(`确认撤回 ${code} 的交易记录 #${id}？撤回后持仓和净值将重新计算。`)) return;
  try{
    await api(`/admin/trades/${id}`,{method:'DELETE'});
    showToast('交易已撤回');
    loadTrades();
    loadStocks();
  }catch(e){showToast(e.message,false)}
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
