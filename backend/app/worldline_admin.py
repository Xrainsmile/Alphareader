"""世界线管理台 — 密码保护的独立 HTML 页面。

复用 Dashboard 的 cookie 认证机制，与 sandbox-admin 同构。
路径: /worldline-admin

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
  padding:24px;max-width:1400px;margin:0 auto}
h1{font-size:26px;font-weight:800;margin-bottom:4px}
.header{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:20px;flex-wrap:wrap;gap:12px}
.sub{color:var(--muted);font-size:14px;margin-bottom:20px}
.nav{display:flex;gap:10px;align-items:center}
.nav a{color:var(--blue);text-decoration:none;font-size:14px;font-weight:600}
.nav a:hover{text-decoration:underline}
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{padding:10px 20px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;
  border:1.5px solid var(--border);background:#fff;color:var(--muted);transition:all .2s}
.tab.active{background:var(--text);color:#fff;border-color:var(--text)}
.tab:hover:not(.active){background:#f8f8fc}
.section{display:none}.section.active{display:block}
.card{background:var(--card);border-radius:var(--radius);padding:24px;
  box-shadow:0 1px 8px rgba(0,0,0,.04);margin-bottom:20px}
.card h3{font-size:16px;margin-bottom:14px;display:flex;align-items:center;
  justify-content:space-between;gap:10px;flex-wrap:wrap}
.card h3 .hint{font-size:12px;color:var(--muted);font-weight:500}
.form-row{display:flex;gap:12px;margin-bottom:12px;align-items:flex-end;flex-wrap:wrap}
.form-group{display:flex;flex-direction:column;gap:4px;flex:1;min-width:150px}
.form-group label{font-size:13px;color:var(--muted);font-weight:600}
.form-group input,.form-group select,.form-group textarea{padding:10px 14px;
  border:1.5px solid var(--border);border-radius:8px;font-size:14px;outline:none;
  transition:border .2s;background:#fff;font-family:inherit;width:100%}
.form-group input:focus,.form-group select:focus,.form-group textarea:focus{
  border-color:var(--blue)}
.form-group textarea{min-height:70px;resize:vertical}
.btn{padding:10px 22px;border:none;border-radius:8px;font-size:14px;font-weight:600;
  cursor:pointer;transition:all .2s;white-space:nowrap}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn-primary{background:var(--blue);color:#fff}
.btn-primary:hover:not(:disabled){background:#2563eb}
.btn-danger{background:var(--red);color:#fff}
.btn-danger:hover:not(:disabled){background:#dc2626}
.btn-green{background:var(--green);color:#fff}
.btn-green:hover:not(:disabled){background:#16a34a}
.btn-amber{background:var(--amber);color:#fff}
.btn-amber:hover:not(:disabled){background:#d97706}
.btn-purple{background:var(--purple);color:#fff}
.btn-purple:hover:not(:disabled){background:#7c3aed}
.btn-ghost{background:#fff;color:var(--text);border:1.5px solid var(--border)}
.btn-ghost:hover:not(:disabled){background:#f8f8fc}
.btn-sm{padding:6px 12px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;padding:10px 12px;border-bottom:2px solid var(--border);
  color:var(--muted);font-weight:600;white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:top}
tr:hover td{background:#f8f8fc}
.badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;
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
.msg{padding:12px 16px;border-radius:8px;margin-bottom:16px;font-size:14px;
  display:none;font-weight:500}
.msg.ok{background:#dcfce7;color:#16a34a;display:block}
.msg.err{background:#fee2e2;color:#dc2626;display:block}
.empty{color:var(--muted);font-size:14px;padding:24px;text-align:center}
.mono{font-family:'SF Mono',Menlo,monospace;font-size:12px}
.chk{display:flex;align-items:center;gap:6px;cursor:pointer}
.chk input{width:auto;cursor:pointer}
.split-wrap{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:900px){.split-wrap{grid-template-columns:1fr}}
.audit-item{padding:10px 12px;border-left:3px solid var(--border);margin-bottom:8px;
  background:#fafafc;border-radius:0 8px 8px 0;font-size:13px}
.audit-item .op{font-weight:700;color:var(--text)}
.audit-item .meta{color:var(--muted);font-size:12px;margin-top:3px}
.thread-sel{background:#fffbeb;border-left:3px solid var(--amber);padding:12px 16px;
  border-radius:0 8px 8px 0;margin-bottom:16px;font-size:14px}
.thread-sel b{color:var(--text)}
.scroll{max-height:420px;overflow-y:auto}
.pager{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:14px}
.pager button{padding:6px 14px;border:1.5px solid var(--border);background:#fff;
  border-radius:8px;cursor:pointer;font-size:13px;font-weight:600}
.pager button:disabled{opacity:.4;cursor:not-allowed}
.pager span{font-size:13px;color:var(--muted)}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>世界线管理台</h1>
    <div class="sub">人工维护：置顶 / 合并 / 拆分 / 事件调度 / 审计追溯</div>
  </div>
  <div class="nav">
    <a href="/sandbox-admin">模拟仓管理</a>
    <a href="/dashboard">Dashboard</a>
  </div>
</div>

<div class="tabs">
  <div class="tab active" data-sec="list">线列表</div>
  <div class="tab" data-sec="pin">置顶/字段锁</div>
  <div class="tab" data-sec="merge">合并</div>
  <div class="tab" data-sec="split">拆分</div>
  <div class="tab" data-sec="event">事件调度</div>
  <div class="tab" data-sec="audit">审计日志</div>
</div>

<div id="msg" class="msg"></div>

<!-- ══════════ 线列表 ══════════ -->
<div class="section active" id="sec-list">
  <div class="card">
    <h3>世界线列表 <span class="hint">点击「选中」把该线带入右侧操作页</span></h3>
    <div class="form-row">
      <div class="form-group">
        <label>搜索（标题 / 标的）</label>
        <input id="f-q" placeholder="如：胡塞、石油、沙特">
      </div>
      <div class="form-group" style="max-width:170px">
        <label>状态</label>
        <select id="f-status">
          <option value="">全部</option>
          <option value="embryo">embryo 萌芽</option>
          <option value="active">active 活跃</option>
          <option value="dormant">dormant 休眠</option>
          <option value="resolved">resolved 已了结</option>
          <option value="merged">merged 已合并</option>
          <option value="split">split 已拆分</option>
        </select>
      </div>
      <div class="form-group" style="max-width:150px">
        <label>置顶</label>
        <select id="f-pinned">
          <option value="">全部</option>
          <option value="true">仅置顶</option>
          <option value="false">仅未置顶</option>
        </select>
      </div>
      <button class="btn btn-primary" onclick="loadThreads(0)">搜索</button>
      <button class="btn btn-ghost" onclick="clearFilter()">清空</button>
    </div>
    <div id="list-box"><div class="empty">加载中…</div></div>
    <div class="pager">
      <button id="p-prev" onclick="pagePrev()">上一页</button>
      <span id="p-info">-</span>
      <button id="p-next" onclick="pageNext()">下一页</button>
    </div>
  </div>
</div>

<!-- ══════════ 置顶 / 字段锁 ══════════ -->
<div class="section" id="sec-pin">
  <div id="pin-sel" class="thread-sel">未选中世界线 — 请先到「线列表」点「选中」</div>
  <div class="card">
    <h3>置顶与字段锁
      <span class="hint">置顶=高质量模型+高频摘要；字段锁=算法不得覆盖（人工否决权）</span></h3>
    <div class="form-row">
      <div class="form-group">
        <label>锁定字段（可多选，锁后算法不得改）</label>
        <div style="display:flex;gap:16px;flex-wrap:wrap;padding:8px 0">
          <label class="chk"><input type="checkbox" id="pf-title" value="title"> title 标题</label>
          <label class="chk"><input type="checkbox" id="pf-mech" value="mechanism_key"> mechanism_key 机制</label>
          <label class="chk"><input type="checkbox" id="pf-asset" value="contested_asset"> contested_asset 标的</label>
          <label class="chk"><input type="checkbox" id="pf-status" value="status"> status 状态</label>
        </div>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>操作人</label>
        <input id="pin-op" value="human" placeholder="human">
      </div>
      <div class="form-group">
        <label>原因（可选）</label>
        <input id="pin-reason" placeholder="如：主线重点关注">
      </div>
    </div>
    <div class="form-row">
      <button class="btn btn-amber" onclick="doPin()">置顶（含字段锁）</button>
      <button class="btn btn-ghost" onclick="doUnpin()">解钉并解锁</button>
    </div>
    <div style="font-size:12px;color:var(--muted);margin-top:8px">
      ★ 解钉即解锁：pinned_fields 会被清空，避免「UI 显示未钉住但算法仍被锁」的隐形约束。
    </div>
  </div>
</div>

<!-- ══════════ 合并 ══════════ -->
<div class="section" id="sec-merge">
  <div class="card">
    <h3>合并两条世界线
      <span class="hint">源线章节迁入目标线，源线置 merged 并留重定向指针（不删除）</span></h3>
    <div class="form-row">
      <div class="form-group">
        <label>源线 ID（章节迁出，合并后置 merged）</label>
        <input id="m-src" class="mono" placeholder="点右侧「用选中线」填入">
        <button class="btn btn-ghost btn-sm" style="margin-top:6px"
                onclick="fillSel('m-src')">用选中线</button>
      </div>
      <div class="form-group">
        <label>目标线 ID（章节迁入，保留存活）</label>
        <input id="m-dst" class="mono" placeholder="粘贴目标线 UUID">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>操作人</label>
        <input id="m-op" value="human">
      </div>
      <div class="form-group">
        <label>原因（必填）</label>
        <input id="m-reason" placeholder="如：实为同一事件链">
      </div>
    </div>
    <button class="btn btn-danger" onclick="doMerge()">执行合并</button>
    <div style="font-size:12px;color:var(--muted);margin-top:10px">
      ★ 合并不可撤销。chapter_id 迁移时保持不变（传导链/观察点按它引用）；
      章节冲突时跳过，不覆盖目标线已有的人工判定。
    </div>
  </div>
</div>

<!-- ══════════ 拆分 ══════════ -->
<div class="section" id="sec-split">
  <div id="split-sel" class="thread-sel">未选中世界线</div>
  <div class="split-wrap">
    <div class="card">
      <h3>① 选择要迁出的章节</h3>
      <div id="split-chapters"><div class="empty">选中线后加载章节</div></div>
    </div>
    <div class="card">
      <h3>② 拆分到新子线</h3>
      <div class="form-row">
        <div class="form-group">
          <label>新线标题（必填）</label>
          <input id="s-title" placeholder="如：胡塞武装袭击沙特石油设施">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>操作人</label>
          <input id="s-op" value="human">
        </div>
        <div class="form-group">
          <label>原因（必填）</label>
          <input id="s-reason" placeholder="如：独立的军事冲突支线">
        </div>
      </div>
      <div style="margin:12px 0">
        <button class="btn btn-primary btn-sm" onclick="toggleAllChapters(true)">全选</button>
        <button class="btn btn-ghost btn-sm" onclick="toggleAllChapters(false)">全不选</button>
        <span id="s-count" style="font-size:13px;color:var(--muted);margin-left:8px">已选 0 章</span>
      </div>
      <button class="btn btn-purple" onclick="doSplit()">执行拆分</button>
      <div style="font-size:12px;color:var(--muted);margin-top:10px">
        ★ 原线保持 active（只是瘦身，不是消失）；已选章节迁入新子线，
        chapter_id 保持不变。
      </div>
    </div>
  </div>
</div>

<!-- ══════════ 事件调度 ══════════ -->
<div class="section" id="sec-event">
  <div id="ev-sel" class="thread-sel">未选中世界线</div>
  <div class="card">
    <h3>事件移除 / 恢复
      <span class="hint">移除=人工判定「挂错了」，并写排除标记防算法重新挂回</span></h3>
    <div class="form-row">
      <div class="form-group">
        <label>事件 ID</label>
        <input id="e-id" class="mono" placeholder="从下方章节表点「用此事件」">
      </div>
      <div class="form-group">
        <label>操作人</label>
        <input id="e-op" value="human">
      </div>
      <div class="form-group">
        <label>原因</label>
        <input id="e-reason" placeholder="如：与主线无关">
      </div>
    </div>
    <div class="form-row">
      <button class="btn btn-danger" onclick="doRemove()">移除事件</button>
      <button class="btn btn-green" onclick="doRestore()">恢复事件</button>
    </div>
  </div>
  <div class="card">
    <h3>移动事件到另一条线
      <span class="hint">同时写两条留痕（源线 remove + 目标线 move）</span></h3>
    <div class="form-row">
      <div class="form-group">
        <label>源线 ID</label>
        <input id="mv-from" class="mono" placeholder="点「用选中线」">
        <button class="btn btn-ghost btn-sm" style="margin-top:6px"
                onclick="fillSel('mv-from')">用选中线</button>
      </div>
      <div class="form-group">
        <label>目标线 ID</label>
        <input id="mv-to" class="mono" placeholder="粘贴目标线 UUID">
      </div>
      <div class="form-group">
        <label>事件 ID</label>
        <input id="mv-event" class="mono" placeholder="粘贴事件 UUID">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>操作人</label>
        <input id="mv-op" value="human">
      </div>
      <div class="form-group">
        <label>原因</label>
        <input id="mv-reason" placeholder="如：归属错误，应归到能源线">
      </div>
    </div>
    <button class="btn btn-amber" onclick="doMove()">执行移动</button>
    <div style="font-size:12px;color:var(--muted);margin-top:10px">
      ★ 移动会对源线写排除标记，防止归线算法立刻把事件挂回原线。
    </div>
  </div>
  <div class="card">
    <h3>当前线章节（点「用此事件」填入上方）</h3>
    <div id="ev-chapters"><div class="empty">选中线后加载</div></div>
  </div>
</div>

<!-- ══════════ 审计日志 ══════════ -->
<div class="section" id="sec-audit">
  <div id="au-sel" class="thread-sel">未选中世界线</div>
  <div class="card">
    <h3>操作留痕
      <span class="hint">所有人工操作的完整追溯记录</span></h3>
    <div class="form-row">
      <div class="form-group" style="max-width:200px">
        <label>操作类型</label>
        <select id="a-op-type">
          <option value="">全部</option>
          <option value="pin">pin 置顶</option>
          <option value="unpin">unpin 解钉</option>
          <option value="merge">merge 合并</option>
          <option value="split">split 拆分</option>
          <option value="move">move 移动</option>
          <option value="remove">remove 移除</option>
          <option value="restore">restore 恢复</option>
        </select>
      </div>
      <button class="btn btn-primary" onclick="loadAudit()">查询</button>
      <button class="btn btn-ghost" onclick="loadThreadSel()">刷新选中线</button>
    </div>
    <div id="audit-box" class="scroll"><div class="empty">选中线后加载</div></div>
  </div>
</div>

<script>
const THREADS='/api/v1/threads';
const _API_KEY='{{ api_key }}';

// ── 全局状态 ──
let SEL=null;            // 当前选中的线 {id,title,...}
let _offset=0, _total=0;
const PAGE=20;

// ── 工具 ──
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
  m.scrollIntoView({behavior:'smooth',block:'nearest'});
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

// ── Tab 切换 ──
document.querySelectorAll('.tab').forEach(t=>{
  t.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));
    t.classList.add('active');
    $('sec-'+t.dataset.sec).classList.add('active');
    // 进入相关页签时按需刷新
    if(t.dataset.sec==='split'&&SEL) loadChapters('split-chapters',true);
    if(t.dataset.sec==='event'&&SEL) loadChapters('ev-chapters',false);
    if(t.dataset.sec==='audit'&&SEL) loadAudit();
  };
});

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
    renderThreads(d.items||[]);
    $('p-info').textContent=`第 ${off+1}-${Math.min(off+PAGE,_total)} 条 / 共 ${_total} 条`;
    $('p-prev').disabled=off<=0;
    $('p-next').disabled=off+PAGE>=_total;
  }catch(e){ $('list-box').innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>' }
}

function statusBadge(s){
  const m={embryo:'b-embryo',active:'b-active',dormant:'b-dormant',
    resolved:'b-resolved',merged:'b-merged',split:'b-split'};
  return '<span class="badge '+(m[s]||'b-dormant')+'">'+esc(s||'-')+'</span>';
}

function renderThreads(items){
  if(!items.length){ $('list-box').innerHTML='<div class="empty">无匹配世界线</div>'; return }
  let h='<table><thead><tr><th>标题</th><th>状态</th><th>置顶</th><th>章节</th>'+
        '<th>最近事件</th><th>操作</th></tr></thead><tbody>';
  items.forEach(t=>{
    h+='<tr>'+
      '<td><b>'+esc(t.title)+'</b>'+
        (t.contested_asset?'<br><span style="color:var(--muted);font-size:12px">标的：'+
          esc(t.contested_asset)+'</span>':'')+
        '<br><span class="mono" style="color:var(--muted)">'+esc(t.id)+'</span></td>'+
      '<td>'+statusBadge(t.status)+'</td>'+
      '<td>'+(t.pinned?'<span class="badge b-pinned">已置顶</span>':
        '<span style="color:var(--muted)">-</span>')+'</td>'+
      '<td>'+(t.chapter_count||0)+'</td>'+
      '<td>'+fmtDate(t.last_event_at)+'</td>'+
      '<td><button class="btn btn-primary btn-sm" onclick=\'selectThread('+
        JSON.stringify(t).replace(/'/g,"&#39;")+')}\'>选中</button></td>'+
    '</tr>';
  });
  $('list-box').innerHTML=h+'</tbody></table>';
}

function selectThread(t){
  SEL=t;
  ['pin-sel','split-sel','ev-sel','au-sel'].forEach(id=>{
    $(id).innerHTML='当前选中：<b>'+esc(t.title)+'</b> '+
      '<span class="mono">'+esc(t.id)+'</span> '+
      statusBadge(t.status)+' '+(t.pinned?'<span class="badge b-pinned">已置顶</span>':'');
  });
  // 回填 pin 复选框
  const pf=(t.pinned_fields&&typeof t.pinned_fields==='object')?t.pinned_fields:{};
  ['title','mechanism_key','contested_asset','status'].forEach(k=>{
    const el=$('pf-'+({'title':'title','mechanism_key':'mechanism',
      'contested_asset':'asset','status':'status'}[k]));
    if(el) el.checked=!!pf[k];
  });
  showMsg('已选中：'+t.title,true);
  loadChapters('split-chapters',true);
  loadChapters('ev-chapters',false);
  loadAudit();
}

function fillSel(targetId){ if(SEL) $(targetId).value=SEL.id; else showMsg('请先选中一条线',false) }
function clearFilter(){
  $('f-q').value=''; $('f-status').value=''; $('f-pinned').value='';
  loadThreads(0);
}
function pagePrev(){ if(_offset>0) loadThreads(Math.max(0,_offset-PAGE)) }
function pageNext(){ if(_offset+PAGE<_total) loadThreads(_offset+PAGE) }

// ── 操作人/原因 收集 ──
function opBody(prefix,extra){
  const b={operator:($(prefix+'-op').value||'human').trim()};
  const r=$(prefix+'-reason')?$(prefix+'-reason').value.trim():'';
  if(r) b.reason=r;
  return Object.assign(b,extra||{});
}

// ── 置顶 / 解钉 ──
async function doPin(){
  if(!SEL) return showMsg('请先选中一条线',false);
  const pf={};
  if($('pf-title').checked) pf.title=true;
  if($('pf-mechanism').checked) pf.mechanism_key=true;
  if($('pf-asset').checked) pf.contested_asset=true;
  if($('pf-status').checked) pf.status=true;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/pin',{
      method:'POST',body:opBody('pin',{pinned_fields:Object.keys(pf).length?pf:null})});
    showMsg('置顶成功'+(Object.keys(pf).length?'，锁定字段：'+Object.keys(pf).join(', '):''),true);
    loadThreads(_offset);
  }catch(e){ showMsg('置顶失败：'+e.message,false) }
}

async function doUnpin(){
  if(!SEL) return showMsg('请先选中一条线',false);
  if(!confirm('解钉将同时清空所有字段锁，确认？')) return;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/unpin',{method:'POST',body:opBody('pin')});
    showMsg('已解钉并解锁',true);
    ['pf-title','pf-mechanism','pf-asset','pf-status'].forEach(id=>$(id).checked=false);
    loadThreads(_offset);
  }catch(e){ showMsg('解钉失败：'+e.message,false) }
}

// ── 合并 ──
async function doMerge(){
  const src=$('m-src').value.trim(), dst=$('m-dst').value.trim();
  const reason=$('m-reason').value.trim();
  if(!src||!dst) return showMsg('源线与目标线 ID 都要填',false);
  if(src===dst) return showMsg('源线与目标线不能相同',false);
  if(!reason) return showMsg('合并必须填原因',false);
  if(!confirm('确认合并？源线将被置为 merged（不可撤销）。')) return;
  try{
    await apiCall(THREADS+'/merge',{method:'POST',
      body:opBody('m',{source_thread_id:src,target_thread_id:dst})});
    showMsg('合并成功',true);
    loadThreads(_offset);
  }catch(e){ showMsg('合并失败：'+e.message,false) }
}

// ── 章节（拆分 / 事件页共用）──
async function loadChapters(boxId,withCheck){
  if(!SEL) return;
  try{
    const d=await apiCall(THREADS+'/'+SEL.id+'/chapters?limit=200');
    renderChapters(boxId,d.items||[],withCheck);
  }catch(e){ $(boxId).innerHTML='<div class="empty">章节加载失败：'+esc(e.message)+'</div>' }
}

function renderChapters(boxId,items,withCheck){
  if(!items.length){ $(boxId).innerHTML='<div class="empty">该线暂无章节</div>'; return }
  let h='<table><thead><tr>'+(withCheck?'<th style="width:40px">选</th>':'')+
        '<th>#</th><th>标题</th><th>角色</th><th>来源</th><th>时间</th>'+
        (withCheck?'':'<th>操作</th>')+'</tr></thead><tbody>';
  items.forEach(c=>{
    h+='<tr>'+
      (withCheck?'<td><input type="checkbox" class="c-chk" value="'+esc(c.chapter_id)+'"></td>':'')+
      '<td>'+(c.chapter_no!=null?c.chapter_no:'-')+'</td>'+
      '<td>'+esc(c.title||'-')+'</td>'+
      '<td>'+esc(c.role||'core')+'</td>'+
      '<td><span class="badge '+(c.assigned_by==='manual'?'b-manual':'b-algo')+'">'+
        esc(c.assigned_by||'algo')+'</span></td>'+
      '<td>'+fmtDate(c.occurred_at)+'</td>'+
      (withCheck?'':'<td><button class="btn btn-ghost btn-sm" onclick="setEvent(\''+
        esc(c.event_id)+'\')">用此事件</button></td>')+
    '</tr>';
  });
  $(boxId).innerHTML=h+'</tbody></table>';
  if(withCheck){
    document.querySelectorAll('.c-chk').forEach(x=>x.onchange=updateSplitCount);
    updateSplitCount();
  }
}

function updateSplitCount(){
  const n=document.querySelectorAll('.c-chk:checked').length;
  const el=$('s-count'); if(el) el.textContent='已选 '+n+' 章';
}
function toggleAllChapters(v){
  document.querySelectorAll('.c-chk').forEach(x=>x.checked=v);
  updateSplitCount();
}
function setEvent(eid){
  if(!eid||eid==='null') return showMsg('该章节无关联事件 ID',false);
  $('e-id').value=eid; $('mv-event').value=eid;
  showMsg('已填入事件 ID：'+eid,true);
}

// ── 拆分 ──
async function doSplit(){
  if(!SEL) return showMsg('请先选中一条线',false);
  const title=$('s-title').value.trim();
  const ids=[...document.querySelectorAll('.c-chk:checked')].map(x=>x.value);
  const reason=$('s-reason').value.trim();
  if(!title) return showMsg('新线标题必填',false);
  if(!ids.length) return showMsg('至少勾选一个章节',false);
  if(!reason) return showMsg('拆分必须填原因',false);
  if(!confirm('确认拆分？这 '+ids.length+' 章将迁入新子线。')) return;
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
  if(!SEL) return showMsg('请先选中一条线',false);
  const eid=$('e-id').value.trim();
  if(!eid) return showMsg('请填事件 ID',false);
  if(!confirm('确认从该线移除此事件？会写排除标记，算法不会重新挂回。')) return;
  try{
    await apiCall(THREADS+'/'+SEL.id+'/events/remove',{method:'POST',
      body:opBody('e',{event_id:eid})});
    showMsg('事件已移除',true);
    loadChapters('ev-chapters',false);
  }catch(e){ showMsg('移除失败：'+e.message,false) }
}

async function doRestore(){
  if(!SEL) return showMsg('请先选中一条线',false);
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
  const from=$('mv-from').value.trim();
  const to=$('mv-to').value.trim();
  const eid=$('mv-event').value.trim();
  if(!from||!to||!eid) return showMsg('源线、目标线、事件 ID 都要填',false);
  if(from===to) return showMsg('源线与目标线不能相同',false);
  if(!confirm('确认移动事件到目标线？')) return;
  try{
    await apiCall(THREADS+'/events/move',{method:'POST',
      body:opBody('mv',{event_id:eid,from_thread_id:from,to_thread_id:to})});
    showMsg('事件已移动',true);
    loadChapters('ev-chapters',false);
  }catch(e){ showMsg('移动失败：'+e.message,false) }
}

// ── 审计日志 ──
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
        '<span style="color:var(--muted)">→ '+esc(a.target_type||a.entity_type||'')+'</span>'+
        (a.reason?'<div style="margin-top:4px">原因：'+esc(a.reason)+'</div>':'')+
        '<div class="meta">'+(a.operator?'操作人：'+esc(a.operator):'')+
          ' · '+fmtDate(a.created_at||a.timestamp)+
          (a.details?' · <span class="mono">'+esc(JSON.stringify(a.details))+'</span>':'')+
        '</div></div>';
    });
    $('audit-box').innerHTML=h;
  }catch(e){ $('audit-box').innerHTML='<div class="empty">审计加载失败：'+esc(e.message)+'</div>' }
}

function loadThreadSel(){ if(SEL) loadThreads(_offset) }

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
