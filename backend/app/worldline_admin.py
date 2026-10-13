"""世界线管理台 — 密码保护的独立 HTML 页面。

复用 Dashboard 的 cookie 认证机制，与 sandbox-admin 同构。
路径: /worldline-admin

布局为左右分栏：左侧线列表，右侧操作面板。
★ 选中即展开全部操作，无需切换页签——页签式设计强迫用户在
  「查看」和「操作」之间反复横跳，是人工维护台最忌讳的交互。

功能（对应 threads.py 的 7 个写接口 + 只读查询）:
  1. 线列表/搜索/筛选
  2. 置顶(pin) / 解钉(unpin)，含字段锁 pinned_fields
  3. 合并(merge) 两条线
  4. 拆分(split)：选定章节迁到新子线
  5. 移除事件(remove) / 恢复事件(restore)
  6. 移动事件到另一条线(move)
  7. 审计日志(history) 追溯
"""

from fastapi import APIRouter, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dashboard import _verify_token

router = APIRouter(tags=["worldline-admin"])

WORLDLINE_ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>世界线管理台</title>
<style>
:root{--bg:#f0f2f5;--card:#fff;--text:#1a1a2e;--muted:#8c8c9a;--border:#e8e8f0;
  --blue:#3b82f6;--green:#22c55e;--amber:#f59e0b;--red:#ef4444;--purple:#8b5cf6;
  --radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);
  font-family:'SF Pro Display','PingFang SC',-apple-system,sans-serif;
  padding:20px;max-width:1600px;margin:0 auto}
h1{font-size:24px;font-weight:800;margin-bottom:2px}
.sub{color:var(--muted);font-size:13px}
.header{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:18px;flex-wrap:wrap;gap:12px}
.nav a{color:var(--blue);text-decoration:none;font-size:14px;font-weight:600;
  margin-left:14px}
.nav a.purple{color:var(--purple)}
.layout{display:grid;grid-template-columns:minmax(420px,1fr) minmax(480px,1.1fr);
  gap:18px;align-items:start}
@media(max-width:1100px){.layout{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:var(--radius);padding:18px;
  box-shadow:0 1px 8px rgba(0,0,0,.04);margin-bottom:16px}
.card h3{font-size:15px;margin-bottom:12px;display:flex;align-items:center;
  justify-content:space-between;gap:10px;flex-wrap:wrap}
.card h3 .hint{font-size:12px;color:var(--muted);font-weight:500}
.form-row{display:flex;gap:10px;margin-bottom:10px;align-items:flex-end;flex-wrap:wrap}
.form-group{display:flex;flex-direction:column;gap:4px;flex:1;min-width:130px}
.form-group label{font-size:12px;color:var(--muted);font-weight:600}
.form-group input,.form-group select{padding:8px 12px;border:1.5px solid var(--border);
  border-radius:8px;font-size:13px;outline:none;transition:border .2s;background:#fff;
  font-family:inherit;width:100%}
.form-group input:focus,.form-group select:focus{border-color:var(--blue)}
.btn{padding:8px 16px;border:none;border-radius:8px;font-size:13px;font-weight:600;
  cursor:pointer;transition:all .2s;white-space:nowrap}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-danger{background:var(--red);color:#fff}
.btn-danger:hover{background:#dc2626}
.btn-green{background:var(--green);color:#fff}
.btn-green:hover{background:#16a34a}
.btn-amber{background:var(--amber);color:#fff}
.btn-amber:hover{background:#d97706}
.btn-purple{background:var(--purple);color:#fff}
.btn-purple:hover{background:#7c3aed}
.btn-ghost{background:#fff;color:var(--text);border:1.5px solid var(--border)}
.btn-ghost:hover{background:#f8f8fc}
.btn-sm{padding:5px 11px;font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:8px 10px;border-bottom:2px solid var(--border);
  color:var(--muted);font-weight:600;white-space:nowrap;position:sticky;top:0;background:#fff}
td{padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover td{background:#f8f8fc}
tr.sel td{background:#eff6ff}
.badge{display:inline-block;padding:2px 8px;border-radius:11px;font-size:11px;
  font-weight:600;white-space:nowrap}
.b-embryo{background:#f3e8ff;color:#7c3aed}
.b-active{background:#dcfce7;color:#16a34a}
.b-dormant{background:#f1f5f9;color:#64748b}
.b-resolved{background:#dbeafe;color:#2563eb}
.b-merged{background:#fef3c7;color:#d97706}
.b-split{background:#ffe4e6;color:#e11d48}
.b-pinned{background:#fef3c7;color:#d97706}
.b-manual{background:#e0e7ff;color:#4f46e5}
.b-algo{background:#f1f5f9;color:#64748b}
.msg{padding:11px 15px;border-radius:8px;margin-bottom:14px;font-size:13px;
  display:none;font-weight:500}
.msg.ok{background:#dcfce7;color:#16a34a;display:block}
.msg.err{background:#fee2e2;color:#dc2626;display:block}
.empty{color:var(--muted);font-size:14px;padding:30px 16px;text-align:center;line-height:1.7}
.mono{font-family:'SF Mono',Menlo,monospace;font-size:11px}
.chk{display:flex;align-items:center;gap:5px;cursor:pointer;font-size:13px}
.chk input{width:auto;cursor:pointer}
.thread-bar{background:#eff6ff;border-left:4px solid var(--blue);padding:12px 15px;
  border-radius:0 10px 10px 0;margin-bottom:14px}
.thread-bar .t{font-size:15px;font-weight:700;margin-bottom:3px}
.thread-bar .id{font-size:11px;color:var(--muted);font-family:'SF Mono',Menlo,monospace}
.audit-item{padding:9px 11px;border-left:3px solid var(--border);margin-bottom:7px;
  background:#fafafc;border-radius:0 8px 8px 0;font-size:12px}
.audit-item .op{font-weight:700}
.audit-item .meta{color:var(--muted);font-size:11px;margin-top:3px}
.scroll{max-height:340px;overflow-y:auto}
.scroll-lg{max-height:420px;overflow-y:auto}
.pager{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:12px}
.pager button{padding:5px 12px;border:1.5px solid var(--border);background:#fff;
  border-radius:8px;cursor:pointer;font-size:12px;font-weight:600}
.pager button:disabled{opacity:.4;cursor:not-allowed}
.pager span{font-size:12px;color:var(--muted)}
.note{font-size:11px;color:var(--muted);margin-top:8px;line-height:1.6}
.rowline{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>世界线管理台</h1>
    <div class="sub">左选线 · 右操作 · 选中即展开，无需切换页签</div>
  </div>
  <div class="nav">
    <a class="purple" href="/sandbox-admin">模拟仓管理</a>
    <a href="/dashboard">Dashboard</a>
  </div>
</div>

<div id="msg" class="msg"></div>

<div class="layout">
  <!-- ══════════ 左：线列表 ══════════ -->
  <div>
    <div class="card">
      <h3>世界线列表 <span class="hint">点击任意一行即选中</span></h3>
      <div class="form-row">
        <div class="form-group">
          <label>搜索（标题 / 标的）</label>
          <input id="f-q" placeholder="如：胡塞、石油">
        </div>
        <div class="form-group" style="max-width:130px">
          <label>状态</label>
          <select id="f-status">
            <option value="">全部</option>
            <option value="embryo">embryo</option>
            <option value="active">active</option>
            <option value="dormant">dormant</option>
            <option value="resolved">resolved</option>
            <option value="merged">merged</option>
            <option value="split">split</option>
          </select>
        </div>
        <div class="form-group" style="max-width:110px">
          <label>置顶</label>
          <select id="f-pinned">
            <option value="">全部</option>
            <option value="true">置顶</option>
            <option value="false">未置顶</option>
          </select>
        </div>
      </div>
      <div class="rowline">
        <button class="btn btn-primary btn-sm" onclick="loadThreads(0)">搜索</button>
        <button class="btn btn-ghost btn-sm" onclick="clearFilter()">清空</button>
      </div>
      <div id="list-box" class="scroll-lg" style="margin-top:12px">
        <div class="empty">加载中…</div>
      </div>
      <div class="pager">
        <button id="p-prev" onclick="pagePrev()">上一页</button>
        <span id="p-info">-</span>
        <button id="p-next" onclick="pageNext()">下一页</button>
      </div>
    </div>
  </div>

  <!-- ══════════ 右：操作面板 ══════════ -->
  <div>
    <div id="panel-empty" class="card">
      <div class="empty">← 从左侧点击一条世界线<br>选中后这里会展开全部维护操作</div>
    </div>

    <div id="panel" style="display:none">
      <div class="thread-bar">
        <div class="t" id="sel-title">-</div>
        <div class="id" id="sel-id">-</div>
        <div style="margin-top:6px" id="sel-meta"></div>
      </div>

      <!-- 置顶 -->
      <div class="card">
        <h3>置顶与字段锁
          <span class="hint">字段锁 = 算法不得覆盖（人工否决权）</span></h3>
        <div class="rowline" style="margin-bottom:10px">
          <label class="chk"><input type="checkbox" id="pf-title"> title</label>
          <label class="chk"><input type="checkbox" id="pf-mech"> mechanism_key</label>
          <label class="chk"><input type="checkbox" id="pf-asset"> contested_asset</label>
          <label class="chk"><input type="checkbox" id="pf-status"> status</label>
        </div>
        <div class="form-row">
          <div class="form-group"><label>操作人</label>
            <input id="pin-op" value="human"></div>
          <div class="form-group"><label>原因</label>
            <input id="pin-reason" placeholder="如：主线重点关注"></div>
        </div>
        <div class="rowline">
          <button class="btn btn-amber btn-sm" onclick="doPin()">置顶（含字段锁）</button>
          <button class="btn btn-ghost btn-sm" onclick="doUnpin()">解钉并解锁</button>
        </div>
        <div class="note">★ 解钉即解锁：pinned_fields 会被清空，避免「UI 显示未钉住但算法仍被锁」。</div>
      </div>

      <!-- 合并 -->
      <div class="card">
        <h3>合并到另一条线
          <span class="hint">当前线并入目标线后置 merged</span></h3>
        <div class="form-row">
          <div class="form-group"><label>目标线 ID（存活方）</label>
            <input id="m-dst" class="mono" placeholder="粘贴目标线 UUID"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>操作人</label><input id="m-op" value="human"></div>
          <div class="form-group"><label>原因（必填）</label>
            <input id="m-reason" placeholder="如：实为同一事件链"></div>
        </div>
        <button class="btn btn-danger btn-sm" onclick="doMerge()">执行合并</button>
        <div class="note">★ 不可撤销。chapter_id 保持不变；冲突章节跳过，不覆盖目标线人工判定。</div>
      </div>

      <!-- 拆分 -->
      <div class="card">
        <h3>拆分出子线 <span class="hint">勾选章节迁到新线，原线保持 active</span></h3>
        <div id="split-chapters" class="scroll">
          <div class="empty">选中线后加载章节</div>
        </div>
        <div class="rowline">
          <button class="btn btn-ghost btn-sm" onclick="toggleAll(true)">全选</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleAll(false)">全不选</button>
          <span id="s-count" style="font-size:12px;color:var(--muted)">已选 0 章</span>
        </div>
        <div class="form-row" style="margin-top:10px">
          <div class="form-group"><label>新线标题（必填）</label>
            <input id="s-title" placeholder="如：胡塞袭击沙特石油设施"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>操作人</label><input id="s-op" value="human"></div>
          <div class="form-group"><label>原因（必填）</label>
            <input id="s-reason" placeholder="如：独立军事支线"></div>
        </div>
        <button class="btn btn-purple btn-sm" onclick="doSplit()">执行拆分</button>
      </div>

      <!-- 事件调度 -->
      <div class="card">
        <h3>事件调度 <span class="hint">移除会自动写排除标记，防算法重新挂回</span></h3>
        <div class="form-row">
          <div class="form-group"><label>事件 ID</label>
            <input id="e-id" class="mono" placeholder="从下方章节点「用此事件」"></div>
          <div class="form-group" style="max-width:110px"><label>操作人</label>
            <input id="e-op" value="human"></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label>原因</label>
            <input id="e-reason" placeholder="如：与主线无关"></div>
        </div>
        <div class="rowline">
          <button class="btn btn-danger btn-sm" onclick="doRemove()">移除事件</button>
          <button class="btn btn-green btn-sm" onclick="doRestore()">恢复事件</button>
        </div>
        <div class="form-row" style="margin-top:12px">
          <div class="form-group"><label>移动到目标线 ID</label>
            <input id="mv-to" class="mono" placeholder="粘贴目标线 UUID"></div>
        </div>
        <div class="rowline">
          <button class="btn btn-amber btn-sm" onclick="doMove()">移动事件到目标线</button>
        </div>
        <div id="ev-chapters" class="scroll" style="margin-top:12px">
          <div class="empty">选中线后加载</div>
        </div>
      </div>

      <!-- 审计 -->
      <div class="card">
        <h3>操作留痕
          <span class="hint">人工操作完整追溯</span></h3>
        <div class="form-row">
          <div class="form-group" style="max-width:150px"><label>类型</label>
            <select id="a-op-type">
              <option value="">全部</option>
              <option value="pin">pin</option>
              <option value="unpin">unpin</option>
              <option value="merge">merge</option>
              <option value="split">split</option>
              <option value="move">move</option>
              <option value="remove">remove</option>
              <option value="restore">restore</option>
            </select>
          </div>
          <button class="btn btn-primary btn-sm" onclick="loadAudit()">查询</button>
        </div>
        <div id="audit-box" class="scroll"><div class="empty">选中线后加载</div></div>
      </div>
    </div>
  </div>
</div>

<script>
const THREADS='/api/v1/threads';
const _API_KEY='{{ api_key }}';

let SEL=null;
let ROWS=[];
let _offset=0,_total=0;
const PAGE=20;

function $(id){return document.getElementById(id)}
function esc(s){return s==null?'':String(s).replace(/[&<>"]/g,c=>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function fmtDate(iso){
  if(!iso) return '-';
  return new Date(iso).toLocaleString('zh-CN',{hour12:false});
}
function showMsg(txt,ok){
  const m=$('msg');
  m.textContent=txt;
  m.className='msg '+(ok?'ok':'err');
  window.scrollTo({top:0,behavior:'smooth'});
  if(ok) setTimeout(()=>{m.className='msg'},6000);
}

async function apiCall(path,opts={}){
  const h=opts.body?{'Content-Type':'application/json'}:{};
  if(_API_KEY) h['X-API-Key']=_API_KEY;
  const r=await fetch(path,{
    method:opts.method||'GET',
    headers:h,
    body:opts.body?JSON.stringify(opts.body):undefined,
    credentials:'same-origin',
  });
  if(!r.ok){
    const e=await r.json().catch(()=>({}));
    throw new Error(e.detail||e.message||('HTTP '+r.status));
  }
  return r.json();
}

// ── 线列表 ──
async function loadThreads(off){
  off=off||0; _offset=off;
  const p=new URLSearchParams({limit:PAGE,offset:off});
  const q=$('f-q').value.trim();
  const st=$('f-status').value;
  const pn=$('f-pinned').value;
  if(q) p.set('q',q);
  if(st) p.set('status',st);
  if(pn) p.set('pinned',pn);
  try{
    const d=await apiCall(THREADS+'?'+p.toString());
    _total=d.total||0;
    ROWS=d.items||[];
    renderThreads();
    $('p-info').textContent=`${off+1}-${Math.min(off+PAGE,_total)} / 共 ${_total}`;
    $('p-prev').disabled=off<=0;
    $('p-next').disabled=off+PAGE>=_total;
  }catch(e){ $('list-box').innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>' }
}

function statusBadge(s){
  const m={embryo:'b-embryo',active:'b-active',dormant:'b-dormant',
    resolved:'b-resolved',merged:'b-merged',split:'b-split'};
  return '<span class="badge '+(m[s]||'b-dormant')+'">'+esc(s||'-')+'</span>';
}

function renderThreads(){
  if(!ROWS.length){ $('list-box').innerHTML='<div class="empty">无匹配世界线</div>'; return }
  let h='<table><thead><tr><th>标题 / 标的</th><th>状态</th><th>顶</th><th>章</th></tr></thead><tbody>';
  ROWS.forEach((t,i)=>{
    const cur=SEL&&SEL.id===t.id;
    h+='<tr class="'+(cur?'sel':'')+'" data-idx="'+i+'" style="cursor:pointer">'+
      '<td><b>'+esc(t.title)+'</b>'+
        (t.contested_asset?'<br><span style="color:var(--muted);font-size:11px">'+
          esc(t.contested_asset)+'</span>':'')+'</td>'+
      '<td>'+statusBadge(t.status)+'</td>'+
      '<td>'+(t.pinned?'<span class="badge b-pinned">顶</span>':
        '<span style="color:var(--muted)">-</span>')+'</td>'+
      '<td>'+(t.chapter_count||0)+'</td>'+
    '</tr>';
  });
  $('list-box').innerHTML=h+'</tbody></table>';
  bindRows();
}

// ★ 事件委托：彻底避免内联 onclick 的引号嵌套问题
function bindRows(){
  document.querySelectorAll('#list-box tr[data-idx]').forEach(tr=>{
    tr.onclick=()=>selectThread(ROWS[parseInt(tr.dataset.idx,10)]);
  });
}

async function selectThread(t){
  SEL=t;
  $('panel-empty').style.display='none';
  $('panel').style.display='block';
  $('sel-title').textContent=t.title;
  $('sel-id').textContent=t.id;
  $('sel-meta').innerHTML=statusBadge(t.status)+' '+
    (t.pinned?'<span class="badge b-pinned">已置顶</span>':'')+
    ' <span style="color:var(--muted);font-size:12px">'+(t.chapter_count||0)+' 章</span>';
  renderThreads();
  try{
    const d=await apiCall(THREADS+'/'+t.id);
    const pf=(d.pinned_fields&&typeof d.pinned_fields==='object')?d.pinned_fields:{};
    $('pf-title').checked=!!pf.title;
    $('pf-mech').checked=!!pf.mechanism_key;
    $('pf-asset').checked=!!pf.contested_asset;
    $('pf-status').checked=!!pf.status;
  }catch(e){}
  loadChapters('split-chapters',true);
  loadChapters('ev-chapters',false);
  loadAudit();
  showMsg('已选中：'+t.title,true);
}

function clearFilter(){
  $('f-q').value=''; $('f-status').value=''; $('f-pinned').value='';
  loadThreads(0);
}
function pagePrev(){ if(_offset>0) loadThreads(Math.max(0,_offset-PAGE)) }
function pageNext(){ if(_offset+PAGE<_total) loadThreads(_offset+PAGE) }

function opBody(p,extra){
  const b={operator:($(p+'-op')&&$(p+'-op').value||'human').trim()};
  const rEl=$(p+'-reason');
  const r=rEl?rEl.value.trim():'';
  if(r) b.reason=r;
  return Object.assign(b,extra||{});
}
function needSel(){ if(!SEL){ showMsg('请先从左侧选中一条世界线',false); return false } return true }

// ── 置顶 / 解钉 ──
async function doPin(){
  if(!needSel()) return;
  const pf={};
  if($('pf-title').checked) pf.title=true;
  if($('pf-mech').checked) pf.mechanism_key=true;
  if($('pf-asset').checked) pf.contested_asset=true;
  if($('pf-status').checked) pf.status=true;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/pin',{method:'POST',
      body:opBody('pin',{pinned_fields:Object.keys(pf).length?pf:null})});
    showMsg('置顶成功'+(Object.keys(pf).length?'，锁定：'+Object.keys(pf).join(', '):''),true);
    loadThreads(_offset);
  }catch(e){ showMsg('置顶失败：'+e.message,false) }
}

async function doUnpin(){
  if(!needSel()) return;
  if(!confirm('解钉将同时清空所有字段锁，确认？')) return;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/unpin',{method:'POST',body:opBody('pin')});
    showMsg('已解钉并解锁',true);
    ['pf-title','pf-mech','pf-asset','pf-status'].forEach(id=>$(id).checked=false);
    loadThreads(_offset);
  }catch(e){ showMsg('解钉失败：'+e.message,false) }
}

// ── 合并（当前线 → 目标线）──
async function doMerge(){
  if(!needSel()) return;
  const dst=$('m-dst').value.trim();
  const reason=$('m-reason').value.trim();
  if(!dst) return showMsg('请填目标线 ID',false);
  if(dst===SEL.id) return showMsg('目标线不能是当前线',false);
  if(!reason) return showMsg('合并必须填原因',false);
  if(!confirm('确认把「'+SEL.title+'」并入目标线？\n当前线将置为 merged，不可撤销。')) return;
  try{
    await apiCall(THREADS+'/merge',{method:'POST',
      body:opBody('m',{source_thread_id:SEL.id,target_thread_id:dst})});
    showMsg('合并成功',true);
    loadThreads(_offset);
  }catch(e){ showMsg('合并失败：'+e.message,false) }
}

// ── 章节 ──
async function loadChapters(boxId,withCheck){
  if(!SEL) return;
  try{
    const d=await apiCall(THREADS+'/'+SEL.id+'/chapters?limit=200');
    renderChapters(boxId,d.items||[],withCheck);
  }catch(e){ $(boxId).innerHTML='<div class="empty">章节加载失败：'+esc(e.message)+'</div>' }
}

function renderChapters(boxId,items,withCheck){
  if(!items.length){ $(boxId).innerHTML='<div class="empty">该线暂无章节</div>'; return }
  let h='<table><thead><tr>'+(withCheck?'<th style="width:32px"></th>':'')+
        '<th>#</th><th>标题</th>'+(withCheck?'':'<th></th>')+'</tr></thead><tbody>';
  items.forEach(c=>{
    h+='<tr>'+
      (withCheck?'<td><input type="checkbox" class="c-chk" value="'+esc(c.chapter_id)+'"></td>':'')+
      '<td style="color:var(--muted)">'+(c.chapter_no!=null?c.chapter_no:'-')+'</td>'+
      '<td>'+esc((c.title||'-').slice(0,60))+
        '<br><span class="badge '+(c.assigned_by==='manual'?'b-manual':'b-algo')+'">'+
        esc(c.assigned_by||'algo')+'</span></td>'+
      (withCheck?'':'<td><button class="btn btn-ghost btn-sm" data-eid="'+
        esc(c.event_id||'')+'">用此事件</button></td>')+
    '</tr>';
  });
  $(boxId).innerHTML=h+'</tbody></table>';
  if(withCheck){
    document.querySelectorAll('#'+boxId+' .c-chk').forEach(x=>x.onchange=updateCount);
    updateCount();
  }else{
    document.querySelectorAll('#'+boxId+' button[data-eid]').forEach(b=>{
      b.onclick=()=>setEvent(b.dataset.eid);
    });
  }
}

function updateCount(){
  const n=document.querySelectorAll('.c-chk:checked').length;
  const el=$('s-count'); if(el) el.textContent='已选 '+n+' 章';
}
function toggleAll(v){
  document.querySelectorAll('.c-chk').forEach(x=>x.checked=v);
  updateCount();
}
function setEvent(eid){
  if(!eid||eid==='null') return showMsg('该章节无关联事件 ID',false);
  $('e-id').value=eid;
  showMsg('已填入事件 ID：'+eid,true);
}

// ── 拆分 ──
async function doSplit(){
  if(!needSel()) return;
  const title=$('s-title').value.trim();
  const ids=[...document.querySelectorAll('.c-chk:checked')].map(x=>x.value);
  const reason=$('s-reason').value.trim();
  if(!title) return showMsg('新线标题必填',false);
  if(!ids.length) return showMsg('至少勾选一个章节',false);
  if(!reason) return showMsg('拆分必须填原因',false);
  if(!confirm('确认拆分？'+ids.length+' 章将迁入新子线。')) return;
  try{
    const d=await apiCall(THREADS+'/'+SEL.id+'/split',{method:'POST',
      body:opBody('s',{new_title:title,chapter_ids:ids})});
    showMsg('拆分成功，新线 ID：'+(d.new_thread_id||d.thread_id||'见列表'),true);
    $('s-title').value='';
    loadThreads(_offset); loadChapters('split-chapters',true);
  }catch(e){ showMsg('拆分失败：'+e.message,false) }
}

// ── 事件移除 / 恢复 ──
async function doRemove(){
  if(!needSel()) return;
  const eid=$('e-id').value.trim();
  if(!eid) return showMsg('请填事件 ID',false);
  if(!confirm('确认从当前线移除此事件？会写排除标记，算法不会重新挂回。')) return;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/events/remove',{method:'POST',
      body:opBody('e',{event_id:eid})});
    showMsg('事件已移除',true);
    loadChapters('ev-chapters',false);
  }catch(e){ showMsg('移除失败：'+e.message,false) }
}

async function doRestore(){
  if(!needSel()) return;
  const eid=$('e-id').value.trim();
  if(!eid) return showMsg('请填事件 ID',false);
  try{
    await apiCall(THREADS+'/'+SEL.id+'/events/restore',{method:'POST',
      body:opBody('e',{event_id:eid})});
    showMsg('事件已恢复',true);
    loadChapters('ev-chapters',false);
  }catch(e){ showMsg('恢复失败：'+e.message,false) }
}

// ── 移动事件 ──
async function doMove(){
  if(!needSel()) return;
  const eid=$('e-id').value.trim();
  const to=$('mv-to').value.trim();
  if(!eid) return showMsg('请填事件 ID',false);
  if(!to) return showMsg('请填目标线 ID',false);
  if(to===SEL.id) return showMsg('目标线不能是当前线',false);
  if(!confirm('确认把该事件移动到目标线？')) return;
  try{
    await apiCall(THREADS+'/events/move',{method:'POST',
      body:opBody('e',{event_id:eid,from_thread_id:SEL.id,to_thread_id:to})});
    showMsg('事件已移动',true);
    loadChapters('ev-chapters',false);
  }catch(e){ showMsg('移动失败：'+e.message,false) }
}

// ── 审计 ──
async function loadAudit(){
  if(!SEL) return;
  const p=new URLSearchParams({limit:100});
  const ot=$('a-op-type').value;
  if(ot) p.set('operation',ot);
  try{
    const d=await apiCall(THREADS+'/'+SEL.id+'/history?'+p.toString());
    const items=d.items||d.operations||d||[];
    if(!items.length){ $('audit-box').innerHTML='<div class="empty">暂无操作留痕</div>'; return }
    let h='';
    items.forEach(a=>{
      h+='<div class="audit-item">'+
        '<span class="op">'+esc(a.operation||a.op||'-')+'</span> '+
        (a.reason?'<span style="color:var(--muted)">· '+esc(a.reason)+'</span>':'')+
        '<div class="meta">'+(a.operator?esc(a.operator):'')+
          ' · '+fmtDate(a.created_at||a.timestamp)+'</div></div>';
    });
    $('audit-box').innerHTML=h;
  }catch(e){ $('audit-box').innerHTML='<div class="empty">审计加载失败：'+esc(e.message)+'</div>' }
}

$('f-q').addEventListener('keydown',e=>{ if(e.key==='Enter') loadThreads(0) });

// ── Init ──
loadThreads(0);
</script>
</body></html>"""


@router.get("/worldline-admin", response_class=HTMLResponse)
async def worldline_admin_page(dash_token: str = Cookie(None)):
    """世界线管理台 — 复用 Dashboard cookie 认证。"""
    if settings.DASHBOARD_PASSWORD and not _verify_token(dash_token or ""):
        return RedirectResponse("/dashboard/login", status_code=303)
    html = WORLDLINE_ADMIN_HTML.replace("{{ api_key }}", "")
    return HTMLResponse(html)
