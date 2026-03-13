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
/* ── 搜索选择组件 ── */
.stock-picker{position:relative;flex:1;min-width:200px}
.stock-picker input{width:100%;padding:10px 14px;border:1.5px solid var(--border);border-radius:8px;
  font-size:14px;outline:none;transition:border .2s;background:#fff;font-family:inherit;box-sizing:border-box}
.stock-picker input:focus{border-color:var(--blue)}
.stock-picker .sp-dropdown{position:absolute;top:100%;left:0;right:0;max-height:240px;overflow-y:auto;
  background:#fff;border:1.5px solid var(--border);border-top:none;border-radius:0 0 8px 8px;
  box-shadow:0 4px 16px rgba(0,0,0,.1);z-index:100;display:none}
.stock-picker .sp-dropdown.show{display:block}
.stock-picker .sp-item{padding:10px 14px;cursor:pointer;font-size:14px;display:flex;justify-content:space-between;
  border-bottom:1px solid #f5f5f5;transition:background .15s}
.stock-picker .sp-item:hover,.stock-picker .sp-item.active{background:#f0f5ff}
.stock-picker .sp-item .sp-code{font-weight:700;color:var(--text)}
.stock-picker .sp-item .sp-name{color:var(--muted);font-size:13px}
.stock-picker .sp-empty{padding:16px;text-align:center;color:var(--muted);font-size:13px}
.stock-picker .sp-selected{display:flex;align-items:center;gap:8px;margin-top:6px}
.stock-picker .sp-tag{display:inline-flex;align-items:center;gap:4px;background:#e8f0fe;color:var(--blue);
  padding:4px 12px;border-radius:6px;font-size:13px;font-weight:600}
.stock-picker .sp-clear{cursor:pointer;color:var(--muted);font-size:16px;line-height:1}
.stock-picker .sp-clear:hover{color:var(--red)}
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
  <div class="tab" onclick="switchTab('value')">录入价投</div>
  <div class="tab" onclick="switchTab('nav')">净值计算</div>
</div>

<div id="toast" class="toast"></div>

<!-- ═══ 观察池 Tab ═══ -->
<div id="section-stocks" class="section active">
  <div class="card">
    <h3>添加股票到观察池</h3>
    <div class="form-row">
      <div class="form-group">
        <label>搜索股票</label>
        <div class="stock-picker" id="picker-add">
          <input placeholder="输入代码或名称搜索..." oninput="onPickerInput(this,'picker-add')" onfocus="onPickerFocus('picker-add')">
          <div class="sp-dropdown"></div>
          <div class="sp-selected"></div>
        </div>
      </div>
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
      <div class="form-group">
        <label>选择股票</label>
        <div class="stock-picker" id="picker-analysis" data-source="sandbox">
          <input placeholder="输入代码或名称搜索..." oninput="onPickerInput(this,'picker-analysis')" onfocus="onPickerFocus('picker-analysis')">
          <div class="sp-dropdown"></div>
          <div class="sp-selected"></div>
        </div>
      </div>
      <div class="form-group" style="max-width:160px"><label>综合评分 (0-5)</label>
        <input id="a-score" type="number" step="0.1" min="0" max="5" placeholder="如 3.5">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>趋势判断 (500字以内)</label>
        <textarea id="a-trend" maxlength="500" placeholder="描述当前趋势..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>形态识别 (500字以内)</label>
        <textarea id="a-pattern" maxlength="500" placeholder="描述技术形态..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>量价行为 (500字以内)</label>
        <textarea id="a-volprice" maxlength="500" placeholder="描述量价特征..."></textarea>
      </div>
    </div>

    <div class="form-row">
      <div class="form-group" style="flex:1"><label>交易计划 Plan (500字以内)</label>
        <textarea id="a-plan" maxlength="500" placeholder="描述交易计划，如：突破1900加仓，跌破1800止损，目标2200..."></textarea>
      </div>
    </div>

    <div class="form-row">
      <div class="form-group" style="flex:1"><label>亏盈思考 (500字以内)</label>
        <textarea id="a-pnl" maxlength="500" placeholder="对亏盈的思考..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group" style="flex:1"><label>哨子 Verdict (500字以内)</label>
        <textarea id="a-verdict" maxlength="500" placeholder="最终判断..."></textarea>
      </div>
    </div>
    <div class="form-row">
      <button class="btn btn-primary" onclick="addAnalysis()">提交推演</button>
    </div>
  </div>

  <!-- 批量导入推演 -->
  <div class="card">
    <h3>批量导入推演</h3>
    <p style="font-size:13px;color:var(--muted);margin-bottom:16px">
      通过 CSV 文件批量录入推演记录。请先下载模板，按格式填写后上传。<br>
      <strong>注意：</strong>CSV 中的 ts_code 必须已在观察池中，否则该行会被跳过。
    </p>
    <div class="form-row" style="align-items:center;gap:16px">
      <button class="btn btn-primary" onclick="downloadCsvTemplate()" style="background:var(--amber)">
        📥 下载 CSV 模板
      </button>
      <div style="position:relative">
        <input type="file" id="csv-upload" accept=".csv" style="display:none" onchange="uploadCsv(this)">
        <button class="btn btn-green" onclick="document.getElementById('csv-upload').click()">
          📤 上传 CSV 批量导入
        </button>
      </div>
    </div>
    <div id="batch-result" style="margin-top:16px"></div>
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
      <thead><tr><th>日期</th><th>代码</th><th>评分</th><th>哨子 Verdict</th><th>操作</th></tr></thead>
      <tbody id="analysisBody"><tr><td colspan="5" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ═══ 录入交易 Tab ═══ -->
<div id="section-trade" class="section">
  <div class="card">
    <h3>新增交易</h3>
    <div class="form-row">
      <div class="form-group">
        <label>选择股票</label>
        <div class="stock-picker" id="picker-trade" data-source="sandbox">
          <input placeholder="输入代码或名称搜索..." oninput="onPickerInput(this,'picker-trade')" onfocus="onPickerFocus('picker-trade')">
          <div class="sp-dropdown"></div>
          <div class="sp-selected"></div>
        </div>
      </div>
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

<!-- ═══ 录入价投 Tab ═══ -->
<div id="section-value" class="section">
  <div class="card">
    <h3>添加价投标的</h3>
    <p style="font-size:13px;color:var(--muted);margin-bottom:16px">
      搜索股票代码或名称，选中后录入价值投资标的。价投标的不会出现在模拟仓观察池的 swing 列表中，仅显示在前端「价投」Tab。
    </p>
    <div class="form-row">
      <div class="form-group">
        <label>搜索股票</label>
        <div class="stock-picker" id="picker-value">
          <input placeholder="输入代码或名称搜索..." oninput="onPickerInput(this,'picker-value')" onfocus="onPickerFocus('picker-value')">
          <div class="sp-dropdown"></div>
          <div class="sp-selected"></div>
        </div>
      </div>
      <div class="form-group" style="flex:2"><label>投资理由</label><textarea id="value-reason" rows="2" placeholder="描述价值投资逻辑..."></textarea></div>
    </div>
    <div class="form-row">
      <button class="btn btn-primary" onclick="addValueStock()">录入价投</button>
    </div>
  </div>
  <div class="card">
    <h3>已录入价投标的</h3>
    <table>
      <thead><tr><th>代码</th><th>名称</th><th>状态</th><th>投资理由</th><th>加入时间</th><th>操作</th></tr></thead>
      <tbody id="valueBody"><tr><td colspan="6" class="empty">加载中...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ═══ 净值计算 Tab ═══ -->
<div id="section-nav" class="section">
  <div class="card">
    <h3>触发 NAV 计算</h3>
    <div class="form-row">
      <div class="form-group"><label>计算日期 (默认今天)</label><input id="nav-date" type="date"></div>
      <div class="form-group"><label>实际现金余额 (可选，补偿手续费)</label><input id="nav-cash" type="number" step="0.01" placeholder="留空则从交易推算"></div>
      <div class="form-group"><label>持仓市值 (可选，行情获取失败时填写)</label><input id="nav-mv" type="number" step="0.01" placeholder="留空则自动获取行情"></div>
      <button class="btn btn-primary" onclick="computeNav()">计算净值</button>
    </div>
    <p style="font-size:12px;color:var(--muted);margin-top:8px">
      💡 填写券商账户的实际可用资金，系统将用此值替代从交易推算的现金（自动补偿佣金、印花税等差异）。留空则按交易记录推算。<br>
      💡 持仓市值优先通过<b>新浪财经接口</b>获取不复权价格。若行情获取失败，可手动填写券商账户中的持仓市值。
    </p>
    <div id="nav-result" style="margin-top:16px"></div>
  </div>
</div>

<script>
const API='/api/v1/sandbox';
const _API_KEY='{{ api_key }}';
let allStocks=[];
const pickerState={};  // {pickerId: {ts_code, name, stock_id}}

function switchTab(name){
  const tabs=['stocks','analysis','trade','value','nav'];
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',tabs[i]===name)});
  document.querySelectorAll('.section').forEach((s,i)=>{s.classList.toggle('active',tabs[i]===name)});
  if(name==='value') loadValueStocks();
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

async function apiCall(path,opts={}){
  const h=opts.body?{'Content-Type':'application/json'}:{};
  if(_API_KEY) h['X-API-Key']=_API_KEY;
  const r=await fetch(API+path,{
    method:opts.method||'GET',
    headers:h,
    body:opts.body?JSON.stringify(opts.body):undefined,
    credentials:'same-origin',
  });
  if(!r.ok){
    const e=await r.json().catch(()=>({}));
    throw new Error(e.detail||r.status);
  }
  return r.json();
}
// keep old name for compatibility
const api=apiCall;

// ── Stock Picker 通用搜索选择组件 ──

let _pickerTimer=null;

function onPickerInput(input,pickerId){
  clearTimeout(_pickerTimer);
  const q=input.value.trim();
  if(q.length<1){hideDropdown(pickerId);return;}
  _pickerTimer=setTimeout(()=>searchForPicker(pickerId,q),300);
}

function onPickerFocus(pickerId){
  const input=document.querySelector('#'+pickerId+' input');
  if(input.value.trim().length>=1) searchForPicker(pickerId,input.value.trim());
}

async function searchForPicker(pickerId,q){
  const picker=document.getElementById(pickerId);
  const dropdown=picker.querySelector('.sp-dropdown');
  const source=picker.dataset.source;

  try{
    let items=[];
    if(source==='sandbox'){
      // 从观察池搜索（已有的 allStocks）
      const kw=q.toUpperCase();
      items=allStocks.filter(s=>(s.ts_code.includes(kw)||s.name.toUpperCase().includes(kw)))
        .map(s=>({ts_code:s.ts_code,name:s.name,stock_id:s.id}));
    } else {
      // 从全市场搜索
      const d=await api('/stock-search?q='+encodeURIComponent(q));
      items=(d.items||[]).map(s=>({ts_code:s.ts_code,name:s.name}));
    }

    if(!items.length){
      dropdown.innerHTML='<div class="sp-empty">未找到匹配股票</div>';
    } else {
      dropdown.innerHTML=items.map((s,i)=>`<div class="sp-item" data-code="${s.ts_code}" data-name="${s.name}" ${s.stock_id?'data-id="'+s.stock_id+'"':''} onclick="selectPicker('${pickerId}',this)">
        <span class="sp-code">${s.ts_code}</span><span class="sp-name">${s.name}</span>
      </div>`).join('');
    }
    dropdown.classList.add('show');
  }catch(e){
    dropdown.innerHTML='<div class="sp-empty">搜索失败</div>';
    dropdown.classList.add('show');
  }
}

function selectPicker(pickerId,el){
  const code=el.dataset.code;
  const name=el.dataset.name;
  const stockId=el.dataset.id||null;
  pickerState[pickerId]={ts_code:code,name:name,stock_id:stockId?parseInt(stockId):null};

  const picker=document.getElementById(pickerId);
  const input=picker.querySelector('input');
  input.value='';
  hideDropdown(pickerId);

  const sel=picker.querySelector('.sp-selected');
  sel.innerHTML=`<span class="sp-tag">${code} ${name}</span><span class="sp-clear" onclick="clearPicker('${pickerId}')">&times;</span>`;
}

function clearPicker(pickerId){
  delete pickerState[pickerId];
  const picker=document.getElementById(pickerId);
  picker.querySelector('.sp-selected').innerHTML='';
  picker.querySelector('input').value='';
}

function hideDropdown(pickerId){
  document.querySelector('#'+pickerId+' .sp-dropdown').classList.remove('show');
}

// 全局点击关闭下拉
document.addEventListener('click',function(e){
  if(!e.target.closest('.stock-picker')){
    document.querySelectorAll('.sp-dropdown.show').forEach(d=>d.classList.remove('show'));
  }
});

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
  // 推演筛选下拉框（含全部股票，不只活跃的）
  const ahFilter=document.getElementById('ah-filter');
  const current=ahFilter.value;
  ahFilter.innerHTML='<option value="">全部股票</option>'+allStocks.map(s=>`<option value="${s.id}">${s.ts_code} ${s.name}</option>`).join('');
  ahFilter.value=current;
}

async function addStock(){
  const picked=pickerState['picker-add'];
  if(!picked){showToast('请先搜索并选择股票',false);return;}
  const reason=document.getElementById('add-reason').value.trim();
  try{
    await api('/admin/stocks',{method:'POST',body:{ts_code:picked.ts_code,name:picked.name,reason:reason||null}});
    showToast(`${picked.ts_code} ${picked.name} 已添加`);
    clearPicker('picker-add');
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
  const picked=pickerState['picker-analysis'];
  if(!picked||!picked.stock_id){showToast('请先搜索并选择观察池中的股票',false);return;}
  const score=parseFloat(document.getElementById('a-score').value);
  if(isNaN(score)||score<0||score>5){showToast('评分须为 0-5',false);return;}
  const trend=document.getElementById('a-trend').value.trim();
  const pattern=document.getElementById('a-pattern').value.trim();
  const volprice=document.getElementById('a-volprice').value.trim();
  const plan=document.getElementById('a-plan').value.trim();
  const pnl=document.getElementById('a-pnl').value.trim();
  const verdict=document.getElementById('a-verdict').value.trim();
  if(!trend||!pattern||!volprice||!pnl||!verdict){showToast('趋势/形态/量价/亏盈/哨子均为必填',false);return;}
  const body={
    stock_id:picked.stock_id,
    ts_code:picked.ts_code,
    score:Math.round(score*10)/10,
    trend,pattern,volume_price:volprice,
    plan:plan||null,
    pnl_thinking:pnl,verdict,
  };
  try{
    await api('/admin/analyses',{method:'POST',body});
    showToast('推演已提交');
    ['a-score','a-trend','a-pattern','a-volprice','a-plan','a-pnl','a-verdict'].forEach(id=>document.getElementById(id).value='');
    loadAnalysisHistory();
  }catch(e){showToast(e.message,false)}
}

// ── 批量导入推演 ──

function downloadCsvTemplate(){
  const h={'X-API-Key':_API_KEY};
  fetch(API+'/admin/analyses/csv-template',{headers:h,credentials:'same-origin'})
    .then(r=>{
      if(!r.ok) throw new Error('下载失败');
      return r.blob();
    })
    .then(blob=>{
      const a=document.createElement('a');
      a.href=URL.createObjectURL(blob);
      a.download='analysis_template.csv';
      a.click();
      URL.revokeObjectURL(a.href);
      showToast('模板已下载');
    })
    .catch(e=>showToast(e.message,false));
}

async function uploadCsv(input){
  const file=input.files[0];
  if(!file){return;}
  const resultDiv=document.getElementById('batch-result');
  resultDiv.innerHTML='<span style="color:var(--muted)">正在导入...</span>';

  const formData=new FormData();
  formData.append('file',file);

  try{
    const h={};
    if(_API_KEY) h['X-API-Key']=_API_KEY;
    const r=await fetch(API+'/admin/analyses/batch',{
      method:'POST',
      headers:h,
      body:formData,
      credentials:'same-origin',
    });
    const d=await r.json();
    if(!r.ok) throw new Error(d.detail||'导入失败');

    let html=`<div style="font-size:14px;font-weight:700;color:var(--green)">
      ✅ 成功导入 ${d.imported} 条，共 ${d.total_rows} 行</div>`;
    if(d.errors&&d.errors.length>0){
      html+=`<div style="margin-top:8px;font-size:13px;color:var(--red)">
        <strong>⚠️ ${d.errors.length} 行有错误：</strong><ul style="margin:4px 0 0 16px">`;
      d.errors.forEach(e=>{
        html+=`<li>第 ${e.row} 行${e.ts_code?' ('+e.ts_code+')':''}：${e.error}</li>`;
      });
      html+='</ul></div>';
    }
    resultDiv.innerHTML=html;
    if(d.imported>0){
      showToast(`成功导入 ${d.imported} 条推演`);
      loadAnalysisHistory();
    }
  }catch(e){
    resultDiv.innerHTML=`<span style="color:var(--red)">❌ ${e.message}</span>`;
    showToast(e.message,false);
  }
  // 重置 input 以便重复上传同一文件
  input.value='';
}

async function loadAnalysisHistory(){
  const body=document.getElementById('analysisBody');
  const filterId=document.getElementById('ah-filter').value;
  try{
    const params=filterId?`?stock_id=${filterId}`:'';
    const d=await api(`/admin/analyses${params}`);
    const items=d.items||[];
    if(!items.length){body.innerHTML='<tr><td colspan="5" class="empty">暂无推演记录</td></tr>';return;}
    // 构建股票名称映射
    const nameMap={};
    allStocks.forEach(s=>{nameMap[s.ts_code]=s.name});
    body.innerHTML=items.map(a=>{
      const scoreBg=a.score>=4?'var(--green)':a.score>=2.5?'var(--amber)':'var(--red)';
      return `<tr>
        <td style="white-space:nowrap">${fmtDate(a.created_at)}</td>
        <td><strong>${a.ts_code}</strong><br><span style="color:var(--muted);font-size:12px">${nameMap[a.ts_code]||''}</span></td>
        <td><span style="display:inline-block;background:${scoreBg};color:#fff;padding:2px 10px;border-radius:10px;font-size:12px;font-weight:700">${a.score}</span></td>
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
  const picked=pickerState['picker-trade'];
  if(!picked||!picked.stock_id){showToast('请先搜索并选择观察池中的股票',false);return;}
  const body={
    stock_id:picked.stock_id,
    ts_code:picked.ts_code,
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
    loadStocks();
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
  const cashVal=document.getElementById('nav-cash').value;
  const mvVal=document.getElementById('nav-mv').value;
  const div=document.getElementById('nav-result');
  div.innerHTML='<span style="color:var(--muted)">计算中（获取行情可能需要几秒）...</span>';
  try{
    const params=new URLSearchParams();
    if(dateVal) params.set('target_date',dateVal);
    if(cashVal) params.set('cash_balance',cashVal);
    if(mvVal) params.set('market_value',mvVal);
    const qs=params.toString()?`?${params.toString()}`:'';
    const r=await api(`/nav/compute${qs}`,{method:'POST'});
    let detailHtml='';
    if(r.holdings_detail && r.holdings_detail.length>0){
      detailHtml='<div style="margin-top:12px;font-size:13px;color:var(--muted);border-top:1px solid #eee;padding-top:8px"><b>持仓明细:</b><br>'+r.holdings_detail.join('<br>')+'</div>';
    }
    div.innerHTML=`<div style="font-size:16px;font-weight:700">
      日期: ${r.date} &nbsp;|&nbsp; NAV: <span style="color:var(--blue)">${r.nav}</span>
      &nbsp;|&nbsp; 收益: <span style="color:${r.total_pnl>=0?'var(--green)':'var(--red)'}">${r.total_pnl}%</span>
      &nbsp;|&nbsp; 市值: ¥${Number(r.market_value).toLocaleString()}
      &nbsp;|&nbsp; 现金: ¥${Number(r.cash).toLocaleString()}
      &nbsp;|&nbsp; 总资产: ¥${Number(r.total_assets).toLocaleString()}
    </div>${detailHtml}`;
    showToast('NAV计算完成');
  }catch(e){div.innerHTML=`<span style="color:var(--red)">${e.message}</span>`;showToast(e.message,false)}
}

// ── 价投 ──

async function addValueStock(){
  const picked=pickerState['picker-value'];
  if(!picked){showToast('请先搜索并选择股票',false);return;}
  const reason=document.getElementById('value-reason').value.trim();
  try{
    await api('/admin/value-stocks',{method:'POST',body:{ts_code:picked.ts_code,name:picked.name,reason:reason||null}});
    showToast(`${picked.ts_code} ${picked.name} 已录入价投`);
    clearPicker('picker-value');
    document.getElementById('value-reason').value='';
    loadValueStocks();
  }catch(e){showToast(e.message,false)}
}

async function loadValueStocks(){
  const body=document.getElementById('valueBody');
  try{
    const d=await api('/stocks?strategy=value');
    const items=d.items||[];
    if(!items.length){body.innerHTML='<tr><td colspan="6" class="empty">暂无价投标的</td></tr>';return;}
    body.innerHTML=items.map(s=>`<tr>
      <td>${s.ts_code}</td><td>${s.name}</td><td>${statusBadge(s.status)}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(s.reason||'').replace(/"/g,'&quot;')}">${s.reason||'-'}</td>
      <td>${fmtDate(s.added_at)}</td>
      <td>${s.status!=='exited'?`<button class="btn btn-danger btn-sm" onclick="removeValueStock(${s.id})">退出</button>`:'-'}</td>
    </tr>`).join('');
  }catch(e){body.innerHTML='<tr><td colspan="6" class="empty">加载失败</td></tr>'}
}

async function removeValueStock(id){
  if(!confirm('确认退出该价投标的？')) return;
  try{
    await api(`/admin/stocks/${id}`,{method:'DELETE'});
    showToast('已标记退出');
    loadValueStocks();
  }catch(e){showToast(e.message,false)}
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
    html = SANDBOX_ADMIN_HTML.replace("{{ api_key }}", settings.NEWS_API_KEY or "")
    return HTMLResponse(html)
