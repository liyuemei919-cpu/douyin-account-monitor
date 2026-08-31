"""
多账号合并真实数据看板生成器

用法:
  python build_multi_account.py [UID1 UID2 ...]   # 指定账号
  python build_multi_account.py --batch            # 从 config.py 读全部
  python build_multi_account.py --batch 1 3        # 从 config.py 读第1、3个

输出:
  reports/multi_account.html  （单文件：总览矩阵 + 下钻明细 + 逐日对比）

依赖: build_single_account.py 中的 fetch_account / compute_comparison / assemble_data
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from build_single_account import (
    load_api_key, load_cookie, fetch_account, compute_comparison, assemble_data,
    TikHubClient, MonitorDB, CST_, HTML_TEMPLATE,
)
from tikhub_client import format_number

# 复用一个简化版的单账号渲染模板（无对比卡片/过滤栏，重用于下钻明细）
DETAIL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>抖音多账号监控看板</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2329; padding: 24px; }
  .wrap { max-width: 1180px; margin: 0 auto; }
  .badge-real { display:inline-block; background:#e8f5e9; color:#1b8a3a; font-size:12px;
                padding:2px 8px; border-radius:10px; margin-left:8px; font-weight:600;}
  .topbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:16px; }
  .topbar h1 { font-size:22px; }
  .global-kpis { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:18px; }
  .gkpi { background:#fff; border-radius:12px; padding:14px; box-shadow:0 2px 8px rgba(0,0,0,.05); text-align:center; }
  .gkpi .v { font-size:22px; font-weight:700; color:#185fa5; }
  .gkpi .l { font-size:12px; color:#8a9099; margin-top:3px; }
  .back-btn { display:none; background:#185fa5; color:#fff; border:none; padding:8px 14px;
              border-radius:8px; cursor:pointer; font-size:13px; margin-bottom:14px; }
  .back-btn:hover { background:#134b85; }
  /* overview matrix */
  .card { background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(0,0,0,.06); padding:20px; margin-bottom:20px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:12px 10px; text-align:left; border-bottom:1px solid #eef1f5; vertical-align:middle; }
  th { color:#8a9099; font-weight:600; background:#fafbfd; }
  tbody tr.matrix-row { cursor:pointer; }
  tbody tr.matrix-row:hover { background:#f0f6ff; }
  .avatar { width:46px; height:46px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; }
  .acc-name { font-weight:700; color:#185fa5; display:flex; align-items:center; gap:6px; }
  .acc-link { color:#185fa5; text-decoration:none; }
  .acc-link:hover { text-decoration:underline; }
  .verify { color:#ffb300; }
  .num { font-variant-numeric:tabular-nums; }
  .chip { display:inline-block; background:#f0f4f9; color:#3a6ea5; font-size:11px;
          padding:2px 8px; border-radius:9px; margin:2px 2px 0 0; }
  .chip.warn { background:#fdecea; color:#c0392b; }
  .chip.ok { background:#e8f5e9; color:#2e7d32; }
  .muted { color:#8a9099; }
  /* detail */
  .profile { display:flex; gap:20px; align-items:center; flex-wrap:wrap; }
  .avatar-lg { width:84px; height:84px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; }
  .pinfo h2 { font-size:24px; display:flex; align-items:center; }
  .open-btn { display:inline-block; margin-left:10px; background:#ff6a00; color:#fff; text-decoration:none;
              font-size:13px; padding:5px 12px; border-radius:8px; font-weight:600; }
  .open-btn:hover { background:#e75f00; }
  .cap-note { font-size:12px; color:#b26a00; background:#fff3e0; border-radius:8px; padding:6px 10px; margin-top:10px; display:inline-block; }
  .meta { color:#8a9099; font-size:13px; margin-top:4px; }
  .sig { color:#5a6068; font-size:14px; margin-top:8px; max-width:620px; }
  .kpis { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-top:18px; }
  .kpi { background:#f7f9fc; border-radius:10px; padding:12px; text-align:center; }
  .kpi .v { font-size:20px; font-weight:700; color:#185fa5; }
  .kpi .l { font-size:12px; color:#8a9099; margin-top:3px; }
  .fbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
  .fbar input, .fbar select { padding:8px 10px; border:1px solid #d9dee5; border-radius:8px; font-size:13px; }
  .fbar input[type=text] { flex:1; min-width:200px; }
  .fbar .info { font-size:13px; color:#8a9099; margin-left:auto; }
  .cover { width:72px; height:96px; object-fit:cover; border-radius:8px; background:#e9edf3; flex-shrink:0; }
  .cap-link { color:#185fa5; text-decoration:none; font-weight:600; }
  .cap-link:hover { text-decoration:underline; }
  .cap-text { display:block; max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tags { margin-top:5px; }
  .tag { display:inline-block; background:#eef3fb; color:#3a6ea5; font-size:11px;
         padding:1px 7px; border-radius:9px; margin-right:4px; }
  .rate-bar { height:5px; background:#e7edf5; border-radius:3px; margin-top:4px; width:80px; overflow:hidden; }
  .rate-bar > i { display:block; height:100%; background:#34a853; }
  .cmp-card { background:#fffaf0; border:1px solid #ffe0b2; }
  .cmp-card h3 { font-size:15px; margin-bottom:10px; color:#b26a00; }
  .cmp-chips { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
  .cmp-chip { background:#fff3e0; border-radius:10px; padding:8px 14px; font-size:13px; color:#8a5a00; }
  .cmp-chip b { font-size:18px; color:#b26a00; margin-left:6px; }
  .del-list { font-size:13px; color:#8a5a00; }
  .del-item { padding:4px 0; border-bottom:1px dashed #ffe0b2; }
  .delta { font-weight:700; font-variant-numeric:tabular-nums; }
  .delta.up { color:#e53935; } .delta.down { color:#2e7d32; }
  .b-new { background:#e3f2fd; color:#1565c0; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-cap { background:#fce4ec; color:#c2185b; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-tag { background:#e8f5e9; color:#2e7d32; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-del { background:#fdecea; color:#c0392b; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .del-row td { background:#faf7f7; }
  .del-row .cap-link { color:#9aa0a8; text-decoration: line-through; }
  .gate-banner { background:#fdecea; color:#c0392b; border:1px solid #f5c6c0; border-radius:10px;
                 padding:10px 14px; font-size:13px; line-height:1.6; margin-bottom:16px; }
  .gate-banner code { background:#fff; padding:1px 5px; border-radius:4px; font-size:12px; }
  /* 逐日下钻弹窗 */
  .mask { position:fixed; inset:0; background:rgba(20,30,45,.45); display:none; align-items:center; justify-content:center; z-index:50; }
  .modal { background:#fff; border-radius:14px; width:min(640px,92vw); max-height:86vh; overflow:auto; padding:22px; box-shadow:0 10px 40px rgba(0,0,0,.2); }
  .modal h3 { font-size:16px; margin-bottom:4px; }
  .modal .sub { font-size:12px; color:#8a9099; margin-bottom:14px; }
  .modal .close { float:right; cursor:pointer; color:#9aa0a8; font-size:20px; line-height:1; }
  .bar { height:6px; background:#e7edf5; border-radius:3px; margin-top:4px; width:90px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:#34a853; }
  footer { text-align:center; color:#9aa0a8; font-size:12px; margin-top:10px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📊 抖音多账号监控看板 <span class="badge-real">真实数据</span></h1>
  </div>

  <div class="global-kpis" id="gkpis"></div>

  <div id="gateBanner" style="display:none" class="gate-banner">
    ⚠️ 部分账号作品被抖音「登录态」挡住（接口返回 not_login_module），当前数据可能不完整。
    如需准确全量数据（如「捏个小鱼丸」真实 4 条作品），请在 <code>douyin-monitor.env.txt</code> 配置
    <code>DOUYIN_COOKIE=</code>（已登录的抖音网页版 Cookie）后重跑。
  </div>

  <button class="back-btn" id="backBtn" onclick="showOverview()">← 返回总览</button>

  <!-- 总览矩阵 -->
  <div class="card" id="overview">
    <table>
      <thead><tr>
        <th>账号</th><th>粉丝</th><th>作品数</th><th>总点赞</th><th>总转发</th>
        <th>逐日对比</th><th>最近更新</th>
      </tr></thead>
      <tbody id="matrix"></tbody>
    </table>
  </div>

  <!-- 下钻明细 -->
  <div id="detail" style="display:none">
    <div class="card">
      <div class="profile" id="d-profile"></div>
      <div class="kpis" id="d-kpis"></div>
    </div>
    <div class="card cmp-card" id="d-cmp" style="display:none"></div>
    <div class="card">
      <div class="fbar">
        <input type="text" id="dq" placeholder="🔍 按文案/标签搜索作品…" oninput="renderDetail()">
        <select id="dsort" onchange="renderDetail()">
          <option value="create_desc">按发布时间（新→旧）</option>
          <option value="digg_desc">按点赞量（高→低）</option>
        </select>
        <span class="info" id="d-info"></span>
      </div>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>封面</th><th>作品（点击↗跳转抖音）</th><th>发布时间</th>
          <th>点赞</th><th>评论</th><th>转发</th><th>收藏</th>
          <th>点赞Δ</th><th>评论Δ</th><th>转发Δ</th><th>收藏Δ</th><th>变化</th><th>操作</th>
        </tr></thead>
        <tbody id="d-tbody"></tbody>
      </table>
      </div>
    </div>
  </div>

  <footer id="footer"></footer>
</div>

<!-- 逐日下钻弹窗 -->
<div class="mask" id="dMask" onclick="if(event.target===this)closeDailyModal()">
  <div class="modal">
    <span class="close" onclick="closeDailyModal()">×</span>
    <h3 id="dmTitle"></h3>
    <div class="sub" id="dmSub"></div>
    <table>
      <thead><tr><th>统计日</th><th>点赞</th><th>评论</th><th>转发</th><th>收藏</th><th>较前一日 Δ</th><th>点赞趋势</th></tr></thead>
      <tbody id="dmBody"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = {DATA_JSON};
function esc(s){ s = (s==null)?'':String(s); return s.replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmt(n){ n=Number(n)||0;
  if(n>=1e8) return (n/1e8).toFixed(1)+'亿';
  if(n>=1e4) return (n/1e4).toFixed(1)+'万';
  return String(n); }
function rateOf(v){ const t=v.digg+v.comm+v.share+v.coll; return (v.play>0)? (t/v.play*100):null; }
function fmtTime(ts){ if(!ts) return '-';
  const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
function delta(n){ if(n==null) return '<span class="muted">—</span>';
  if(n===0) return '0';
  const cls=n>0?'up':'down'; const s=n>0?'+':'';
  return '<span class="delta '+cls+'">'+s+fmt(n)+'</span>'; }
function changeBadges(v){ const c=[];
  if(v.deleted) c.push('<span class="b-del">已删除</span>');
  if(v.is_new) c.push('<span class="b-new">新</span>');
  if(v.caption_changed) c.push('<span class="b-cap">文变</span>');
  if(v.tags_changed) c.push('<span class="b-tag">签变</span>');
  return c.length?c.join(' '):'<span class="muted">—</span>'; }

// ===== 逐日下钻弹窗 =====
function openDailyModal(v){
  if(!v || !(v.daily||[]).length){ return; }
  document.getElementById('dmTitle').textContent = (v.desc||'(无文案)').split('\n')[0];
  const acc = curAccount.profile;
  document.getElementById('dmSub').innerHTML =
    '账号：' + esc(acc.nickname) + ' · 作品 ID：' + esc(v.aweme_id) +
    ' · 共 ' + v.daily.length + ' 个统计日';
  const daily = v.daily||[];
  const maxDigg = Math.max(...daily.map(d=>d.digg),1);
  let prev=null;
  document.getElementById('dmBody').innerHTML = daily.map(d=>{
    let dc='<span class="muted">—</span>';
    if(prev!==null){
      const diff=d.digg-prev;
      if(diff!==0){ const cls=diff>0?'up':'down'; const s=diff>0?'+':'';
        dc='<span class="delta '+cls+'">'+s+fmt(diff)+'</span>'; }
      else dc='<span class="delta flat">0</span>';
    }
    const pct=Math.round(d.digg/maxDigg*100);
    const row='<tr><td class="num">'+d.date+'</td><td class="num">'+fmt(d.digg)+'</td>'+
      '<td class="num">'+fmt(d.comm)+'</td><td class="num">'+fmt(d.share)+'</td>'+
      '<td class="num">'+fmt(d.coll)+'</td><td>'+dc+'</td>'+
      '<td><div class="bar"><i style="width:'+pct+'%"></i></div></td></tr>';
    prev=d.digg; return row;
  }).join('');
  document.getElementById('dMask').style.display='flex';
}
function closeDailyModal(){ document.getElementById('dMask').style.display='none'; }
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeDailyModal(); });

// ===== 总览矩阵 =====
function showOverview(){
  document.getElementById('detail').style.display='none';
  document.getElementById('overview').style.display='block';
  document.getElementById('backBtn').style.display='none';
  document.getElementById('matrix').innerHTML = DATA.accounts.map((a, i)=>{
    const p=a.profile, s=a.summary, cmp=a.comparison||{};
    const av = p.avatar ? `<img class="avatar" src="${esc(p.avatar)}" alt="">` : `<div class="avatar"></div>`;
    const chips=[];
    if(cmp.has_prior){
      if(cmp.new_count) chips.push(`<span class="chip ok">新 ${cmp.new_count}</span>`);
      if(cmp.changed_caption) chips.push(`<span class="chip">文变 ${cmp.changed_caption}</span>`);
      if(cmp.changed_tags) chips.push(`<span class="chip">签变 ${cmp.changed_tags}</span>`);
      if(cmp.deleted_count) chips.push(`<span class="chip warn">删 ${cmp.deleted_count}</span>`);
      if(!chips.length) chips.push('<span class="chip">无变化</span>');
    } else { chips.push('<span class="chip muted">基线</span>'); }
    return `<tr class="matrix-row" onclick="showDetail(${i})">
      <td>${av}<div class="acc-name" style="margin-top:6px">
          <a class="acc-link" href="${esc(p.douyin_url)}" target="_blank" onclick="event.stopPropagation()" title="在抖音打开（新窗口）">${esc(p.nickname)} <span style="color:#ff6a00">↗</span></a>
          ${p.verified?'<span class="verify" title="已认证">✦</span>':''}</div>
          <div class="meta">${esc(p.unique_id||'—')}</div></td>
      <td class="num">${fmt(p.follower_count)}</td>
      <td class="num">${fmt(s.video_count)}${p.total_count>s.video_count?'<div class="muted" style="font-size:11px">/共'+fmt(p.total_count)+'</div>':(p.gated?'<div class="muted" style="font-size:11px">未知(登录限制)</div>':'')}</td>
      <td class="num">${fmt(s.total_digg)}</td>
      <td class="num">${fmt(s.total_share)}</td>
      <td>${chips.join('')}</td>
      <td class="meta">${a.stat_date}</td>
    </tr>`;
  }).join('');
}

// ===== 下钻明细 =====
let curAccount = null;
function showDetail(i){
  curAccount = DATA.accounts[i];
  document.getElementById('overview').style.display='none';
  document.getElementById('detail').style.display='block';
  document.getElementById('backBtn').style.display='inline-block';
  const p=curAccount.profile, s=curAccount.summary;
  // profile
  document.getElementById('d-profile').innerHTML = `
    ${p.avatar?`<img class="avatar-lg" src="${esc(p.avatar)}" alt="">`:`<div class="avatar-lg"></div>`}
    <div class="pinfo">
      <h2>${esc(p.nickname)} ${p.verified?'<span class="verify" title="已认证">✦</span>':''}
          <a class="open-btn" href="${esc(p.douyin_url)}" target="_blank" title="在抖音打开">↗ 在抖音打开</a></h2>
      <div class="meta">抖音号: ${esc(p.unique_id||'—')} · UID: ${esc(p.uid)}</div>
      <div class="sig">${esc(p.signature||'（暂无签名）')}</div>
      ${(p.total_count&&p.total_count>s.video_count)?`<div class="cap-note">⚠️ 该账号真实作品数 ${fmt(p.total_count)}，已按需求仅采集并展示前 ${s.video_count} 条</div>`:(p.gated?`<div class="cap-note" style="background:#fdecea;color:#c0392b">⚠️ 该账号作品受登录态限制，当前展示的 ${s.video_count} 条可能不完整（真实作品数未知）</div>`:'')}
    </div>`;
  const playTxt = '—';
  const rateTxt = '—';
  document.getElementById('d-kpis').innerHTML = [
    ['粉丝', fmt(p.follower_count)], ['关注', fmt(p.following_count)],
    ['已采集作品', fmt(s.video_count)], ['总点赞', fmt(s.total_digg)], ['总转发', fmt(s.total_share)],
  ].map(([l,v])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
  // comparison card
  const cmp=curAccount.comparison;
  if(cmp && cmp.has_prior){
    const chips=[['对比日期',cmp.prior_date],['新增作品',cmp.new_count],['文案变化',cmp.changed_caption],
      ['标签变化',cmp.changed_tags],['删除/隐藏',cmp.deleted_count]]
      .map(([l,v])=>`<div class="cmp-chip">${l}<b>${v}</b></div>`).join('');
    const del = cmp.deleted.length
      ? cmp.deleted.map(d=>`<div class="del-item">🗑️ ${esc(d.desc)||'(无文案)'} <span class="muted">（最后出现 ${cmp.prior_date}，点赞 ${fmt(d.digg)}）</span></div>`).join('')
      : '<div class="muted">无</div>';
    const el=document.getElementById('d-cmp'); el.style.display='block';
    el.innerHTML=`<h3>📊 逐日对比（vs ${cmp.prior_date}）</h3><div class="cmp-chips">${chips}</div><div class="del-list"><b>删除/隐藏的作品：</b>${del}</div>`;
  } else {
    document.getElementById('d-cmp').style.display='none';
  }
  renderDetail();
}

function renderDetail(){
  const D=curAccount; const q=document.getElementById('dq').value.trim().toLowerCase();
  const sort=document.getElementById('dsort').value;
  let rows=D.videos.filter(v=>!q||(v.desc+v.tags).toLowerCase().includes(q));
  const cmp={
    create_desc:(a,b)=>b.create_time-a.create_time,
    digg_desc:(a,b)=>b.digg-a.digg,
  }[sort];
  rows.sort(cmp);
  document.getElementById('d-tbody').innerHTML = rows.map(v=>{
    const tags=v.tags.split(',').filter(Boolean).map(t=>`<span class="tag">#${esc(t)}</span>`).join('');
    const cover=v.cover?`<img class="cover" src="${esc(v.cover)}" loading="lazy" alt="封面">`:`<div class="cover"></div>`;
    const hasDaily = (v.daily||[]).length >= 2;
    return `<tr class="${v.deleted?'del-row':''}">
      <td>${cover}</td>
      <td><a class="cap-link" href="${esc(v.url)}" target="_blank" title="在抖音打开">${esc(v.desc.split('\n')[0]||'(无文案)')} <span style="color:#ff6a00">↗</span></a>
          <div class="tags">${tags}</div></td>
      <td class="num muted">${fmtTime(v.create_time)}</td>
      <td class="num">${fmt(v.digg)}</td>
      <td class="num">${fmt(v.comm)}</td>
      <td class="num">${fmt(v.share)}</td>
      <td class="num">${fmt(v.coll)}</td>
      <td class="num">${delta(v.ddigg)}</td>
      <td class="num">${delta(v.dcomm)}</td>
      <td class="num">${delta(v.dshare)}</td>
      <td class="num">${delta(v.dcoll)}</td>
      <td>${changeBadges(v)}</td>
      <td><button class="open-btn" onclick="openDailyModal(${JSON.stringify(v).replace(/"/g,'&quot;')})"${!hasDaily?' disabled style="opacity:.4;cursor:not-allowed" title="暂无多日数据"':''}>查看每日</button></td>
    </tr>`;
  }).join('');
  document.getElementById('d-info').textContent=`共 ${rows.length} / ${D.videos.length} 条作品`;
}

// 全局 KPI
const totAcc=DATA.accounts.length;
const totVid=DATA.accounts.reduce((s,a)=>s+a.summary.video_count,0);
const totDigg=DATA.accounts.reduce((s,a)=>s+a.summary.total_digg,0);
const totShare=DATA.accounts.reduce((s,a)=>s+a.summary.total_share,0);
const totChanged=DATA.accounts.reduce((s,a)=>s+(a.comparison&&a.comparison.has_prior?a.comparison.new_count+a.comparison.changed_caption+a.comparison.changed_tags+a.comparison.deleted_count:0),0);
document.getElementById('gkpis').innerHTML=[
  ['监控账号', totAcc],['总作品数', totVid],['总点赞', fmt(totDigg)],
  ['总转发', fmt(totShare)],['有变化账号', DATA.accounts.filter(a=>a.comparison&&a.comparison.has_prior).length],
].map(([l,v])=>`<div class="gkpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

document.getElementById('footer').innerHTML=
  `数据来源：TikHub API · 统计日 ${DATA.stat_date} · 共 ${totAcc} 个账号<br>`+
  `点击账号名后的 <span style="color:#ff6a00">↗</span> 直接在抖音打开主页；点击账号行可下钻查看作品与逐日增量。`;

// 登录态限制横幅
if (DATA.accounts.some(a => a.profile && a.profile.gated)) {
  document.getElementById('gateBanner').style.display = 'block';
}

showOverview();
</script>
</body>
</html>
"""


def analyze_account(account: dict) -> dict:
    """
    对单个账号做「规律推断」（基于已采集作品 + 逐日对比）。
    重点回答用户关心的两点：
      1) 流量好的作品是否带品牌/营销标签（即是否存在「按数据好坏增删标签」的行为）；
      2) 数据差的作品是否被隐藏/删除（基于逐日对比中的 deleted_count）。
    并给出可落地的「提高数据」建议。
    注意：播放量恒为 0（公开接口不返回），互动量以 赞+评+转+藏 的合计代理。
    """
    videos = account.get("videos", []) or []
    cmp = account.get("comparison") or {}
    # 本次采集是否受限（被裁剪到前10 / 或受登录态限制）→ 删除检测不可靠
    capped = bool(account.get("capped"))

    if not videos:
        return {
            "available": False,
            "reason": "无已采集作品，无法分析。该账号作品可能被登录态挡住，"
                      "请在 env 配置 DOUYIN_COOKIE（已登录的抖音网页 Cookie）后重跑。",
            "findings": [], "suggestions": [],
            "brand_tags": [], "deleted_signal": False,
            "tagged_avg_eng": 0, "untagged_avg_eng": 0,
            "high_tag_pct": 0, "low_tag_pct": 0,
        }

    # 计算每条互动量（代理指标），构造带 _eng 的副本列表再排序/分组
    enriched = []
    for v in videos:
        e = dict(v)
        # assemble_data 已将 *_count 转为短字段名 digg/comm/share/coll
        e["_eng"] = (e.get("digg", 0) or 0) + (e.get("comm", 0) or 0) + \
                    (e.get("share", 0) or 0) + (e.get("coll", 0) or 0)
        enriched.append(e)
    sv = sorted(enriched, key=lambda x: x["_eng"], reverse=True)
    n = len(sv)
    half = max(1, n // 2)
    high = sv[:half]
    low = sv[half:]

    def tagstat(g):
        if not g:
            return 0, 0.0
        tagged = [x for x in g if (x.get("tags") or "").strip()]
        avg = sum(len([t for t in (x.get("tags") or "").split(",") if t]) for x in g) / len(g)
        return len(tagged), avg

    h_tagged, _ = tagstat(high)
    l_tagged, _ = tagstat(low)
    high_tag_pct = round(h_tagged / len(high) * 100)
    low_tag_pct = round(l_tagged / len(low) * 100) if low else 0

    tagged = [x for x in enriched if (x.get("tags") or "").strip()]
    untagged = [x for x in enriched if not (x.get("tags") or "").strip()]
    tv = round(sum(x["_eng"] for x in tagged) / len(tagged)) if tagged else 0
    uv = round(sum(x["_eng"] for x in untagged) / len(untagged)) if untagged else 0

    def tags_of(g):
        s = set()
        for x in g:
            for t in (x.get("tags") or "").split(","):
                if t:
                    s.add(t)
        return s

    high_tags = tags_of(high)
    low_tags = tags_of(low)
    brand_tags = sorted(high_tags - low_tags)          # 只在高互动作品出现的标签
    top_video_tags = sorted(tags_of([sv[0]]))           # 最佳作品标签

    def fmt_eng(x):
        return format_number(x)

    findings = []
    suggestions = []

    top = sv[0]
    findings.append(
        f"互动量最高的作品《{(top.get('desc') or '')[:18]}…》互动量 {fmt_eng(top['_eng'])}，"
        + (f"带标签：{'、'.join('#' + t for t in top_video_tags)}" if top_video_tags
           else "未带标签") + "。"
    )
    if brand_tags:
        findings.append(
            f"以下标签只出现在高互动作品、未出现在低互动作品，疑似「品牌/营销标签」："
            f"{'、'.join('#' + t for t in brand_tags)}。"
            f"→ 流量好的作品更倾向带这些标签，存在「按数据好坏增删标签」的迹象。"
        )
    if tv and uv:
        ratio = f"（约 {round(tv / uv, 1)}x）" if uv else ""
        findings.append(f"带标签作品平均互动量 {fmt_eng(tv)}，不带标签 {fmt_eng(uv)}{ratio}。")
    if high_tag_pct or low_tag_pct:
        rel = "正相关" if high_tag_pct >= low_tag_pct else "无明显正相关"
        findings.append(
            f"高互动作品 {high_tag_pct}% 带标签，低互动作品 {low_tag_pct}% 带标签，"
            f"标签使用与互动量{rel}。"
        )

    # 删除/隐藏信号（仅当本次完整采集、且确有逐日对比时才可信）
    deleted_signal = bool(cmp.get("has_prior") and cmp.get("deleted_count") and not capped)
    if cmp.get("has_prior") and cmp.get("deleted_count") and capped:
        findings.append(
            f"逐日对比发现 {cmp['deleted_count']} 条作品在前次完整采集中存在、本次未出现；"
            f"但因本次仅采集前 10 / 受登录态限制，无法判定是「被删除/隐藏」还是「被新作品挤出前 10」。"
        )
    elif deleted_signal:
        d0 = (cmp.get("deleted") or [{}])[0]
        findings.append(
            f"逐日对比发现 {cmp['deleted_count']} 条作品消失（被删除/隐藏），"
            f"其最后出现时点赞 {fmt_eng(d0.get('digg', 0))}，疑似「数据差的作品被清理」。"
        )
        suggestions.append(
            "被隐藏/删除的作品互动普遍偏低，印证「数据差即清理」策略；"
            "建议在发布前用小号或私密测款，避免公开试错损耗账号权重。"
        )

    # 建议
    if brand_tags or (tv and uv and tv > uv):
        tag_hint = "、".join(brand_tags[:5]) or "品牌/营销"
        suggestions.append(
            f"高互动作品普遍带「{tag_hint}」类标签，建议新作品沿用已被验证有效的标签组合，"
            f"并在发布后 1–2 小时内根据实时数据补/撤标签。"
        )
    if top["_eng"] > 0:
        suggestions.append(
            f"最佳作品互动量 {fmt_eng(top['_eng'])}，可拆解其选题 / 文案结构 / 发布时段，"
            f"复制到后续内容。"
        )
    if low:
        suggestions.append(
            f"最弱作品互动量仅 {fmt_eng(low[0]['_eng'])}，明显拖累账号均值；"
            f"可考虑隐藏/删除或翻新重发。"
        )
    suggestions.append(
        "保持固定更新节奏、前 3 秒强钩子、结尾引导互动（点赞/收藏），可系统性提升互动率。"
    )
    if not (brand_tags or (tv and uv and tv > uv)):
        suggestions.append(
            "当前样本中标签与互动量关联不明显，建议做 A/B：同一选题带不同标签发布，"
            "观察 24h 数据再决定标签策略。"
        )

    return {
        "available": True,
        "n_collected": n,
        "high_tag_pct": high_tag_pct, "low_tag_pct": low_tag_pct,
        "tagged_avg_eng": tv, "untagged_avg_eng": uv,
        "brand_tags": brand_tags, "top_video_tags": top_video_tags,
        "deleted_signal": deleted_signal,
        "findings": findings, "suggestions": suggestions,
    }


def collect_account_data(client, uid, name_hint, db, stat_date, cookie=""):
    """抓取并组装单个账号的完整数据对象（不写 HTML）"""
    captured_at = datetime.now(CST_).strftime("%Y-%m-%d %H:%M:%S")
    profile, videos, total_count, gated = fetch_account(client, uid, name_hint, cookie=cookie)

    db.save_snapshot(uid, profile.get("nickname", name_hint), profile)
    db.save_video_daily(uid, videos, stat_date)

    # 本次采集是否受限：被裁剪到前10，或受登录态限制 → 删除检测不可靠
    capped = (total_count is not None and total_count > len(videos)) or gated

    # 逐日对比
    comparison = {"has_prior": False, "prior_date": "", "new_count": 0,
                  "changed_caption": 0, "changed_tags": 0, "deleted_count": 0, "deleted": []}
    dates = db.get_distinct_dates(uid)
    prior_date = next((d for d in dates if d < stat_date), None)
    if prior_date:
        prior_records = db.get_records_by_date(uid, prior_date)
        comparison = compute_comparison(videos, prior_records, prior_date, capped=capped)
        print(f"🔍 {uid} 对比基线 {prior_date}：新增 {comparison['new_count']} · "
              f"文案 {comparison['changed_caption']} · 标签 {comparison['changed_tags']} · "
              f"删除 {comparison['deleted_count']}"
              + ("（采集受限，删除判定不可靠）" if capped else ""))

    data = assemble_data(profile, videos, stat_date, captured_at, comparison, total_count, gated)
    data["capped"] = capped
    return data


def load_account_from_db(db, uid, stat_date):
    """从数据库加载已采集数据（保留历史全量，不重新抓取、不覆盖旧数据）。

    关键特性：即使视频被删除/隐藏，只要数据库里曾经抓到过，就【保留其数据留存】——
    作品列表取该账号「跨所有统计日」出现过的全部视频（按 aweme_id 去重），
    已删除/隐藏的视频（最后出现日 < 基准日）仍保留、显示并置灰标记，逐日历史也保留。
    若 stat_date 无数据，自动回退到该 uid 最新的可用统计日。
    """
    # 1. 基准日当天记录（用于回退与「当天可见集合」）
    rows = db.get_records_by_date(uid, stat_date)
    used_date = stat_date
    if not rows:
        dates = db.get_distinct_dates(uid)
        if dates:
            used_date = max(dates)
            rows = db.get_records_by_date(uid, used_date)
            print(f"  ℹ️ {uid} 回退到最新可用日期 {used_date}")
    if not rows:
        return None
    day_ids = {r["aweme_id"] for r in rows}

    # 2. 全量去重集合：取每个视频「最后出现」的那条记录（所有统计日，升序覆盖→最近一次）
    conn = db._get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT aweme_id, stat_date, desc, title, tags, create_time, play_count, "
        "digg_count, comment_count, share_count, collect_count, cover "
        "FROM video_daily WHERE account_uid=? ORDER BY aweme_id, stat_date",
        (uid,),
    )
    last_by_aid = {}
    for r in c.fetchall():
        last_by_aid[r["aweme_id"]] = r
    conn.close()
    if not last_by_aid:
        return None

    videos = []
    deleted_ids = set()
    for aid, r in last_by_aid.items():
        last_date = r["stat_date"]
        is_deleted = last_date < used_date
        if is_deleted:
            deleted_ids.add(aid)
        videos.append({
            "aweme_id": aid,
            "desc": r["desc"] or "",
            "title": r["title"] or "",
            "tags": r["tags"] or "",
            "create_time": r["create_time"] or 0,
            "play_count": r["play_count"] or 0,
            "digg_count": r["digg_count"] or 0,
            "comment_count": r["comment_count"] or 0,
            "share_count": r["share_count"] or 0,
            "collect_count": r["collect_count"] or 0,
            "cover": r["cover"] or "",
            "deleted": is_deleted,
        })

    # 3. 逐日历史（全部统计日，供「查看每日」下钻；已删视频也保留历史曲线）
    conn = db._get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT aweme_id, stat_date, digg_count, comment_count, share_count, collect_count "
        "FROM video_daily WHERE account_uid=? AND aweme_id IN ("
        + ",".join("?" for _ in videos) + ") ORDER BY aweme_id, stat_date",
        [uid] + [v["aweme_id"] for v in videos],
    )
    daily_map = {}
    for dr in c.fetchall():
        daily_map.setdefault(dr["aweme_id"], []).append({
            "date": dr["stat_date"],
            "digg": dr["digg_count"] or 0,
            "comm": dr["comment_count"] or 0,
            "share": dr["share_count"] or 0,
            "coll": dr["collect_count"] or 0,
        })
    conn.close()
    for v in videos:
        v["daily"] = sorted(daily_map.get(v["aweme_id"], []), key=lambda x: x["date"])

    # 4. 最新资料快照
    conn = db._get_conn()
    c = conn.cursor()
    c.execute("SELECT raw_profile FROM snapshots WHERE account_uid=? "
              "ORDER BY captured_at DESC LIMIT 1", (uid,))
    srow = c.fetchone()
    conn.close()
    profile = {}
    if srow and srow["raw_profile"]:
        try:
            profile = json.loads(srow["raw_profile"])
        except Exception:
            profile = {}
    if not profile or not profile.get("nickname"):
        profile = {"nickname": uid, "uid": uid, "sec_uid": "", "avatar": "",
                   "unique_id": "", "signature": "", "verified": False,
                   "follower_count": 0, "following_count": 0,
                   "total_favorited": 0, "aweme_count": len(videos)}

    # 5. 逐日对比：用「当天可见集合」vs「前一天完整集合」算新增/变化/删除
    total_count = len(videos)
    capped = False  # 历史全量数据，删除检测可靠
    comparison = {"has_prior": False, "prior_date": "", "new_count": 0,
                  "changed_caption": 0, "changed_tags": 0, "deleted_count": 0,
                  "deleted": [], "deletion_limited": False}
    dates = db.get_distinct_dates(uid)
    prior_date = next((d for d in dates if d < used_date), None)
    if prior_date:
        prior_records = db.get_records_by_date(uid, prior_date)
        day_videos = [v for v in videos if v["aweme_id"] in day_ids]
        comparison = compute_comparison(day_videos, prior_records, prior_date, capped=capped)
        # compute_comparison 已就地给 day_videos（即 videos 子集）写入 is_new/ddigg 等

    # 6. 已删除视频：清除相对基准日的 Δ（无意义），确保变化标记为空
    for v in videos:
        if v.get("deleted"):
            v["is_new"] = False
            v["caption_changed"] = False
            v["tags_changed"] = False
            v["ddigg"] = v["dcomm"] = v["dshare"] = v["dcoll"] = None

    captured_at = datetime.now(CST_).strftime("%Y-%m-%d %H:%M:%S")
    data = assemble_data(profile, videos, used_date, captured_at, comparison,
                         total_count, gated=False)
    # 把 deleted 标记透传到前端（assemble_data 不保留该字段）
    amap = {v["aweme_id"]: v["deleted"] for v in videos}
    for outv in data["videos"]:
        outv["deleted"] = amap.get(outv["aweme_id"], False)
    data["summary"]["deleted_count"] = len(deleted_ids)
    data["capped"] = capped
    data["from_db"] = True
    return data


def main():
    api_key = load_api_key()
    if not api_key:
        print("❌ 未找到 TikHub API Key")
        sys.exit(1)
    cookie = load_cookie()
    if cookie:
        print("🍪 已加载抖音登录 Cookie（将用于解锁被登录态挡住的作品）")
    else:
        print("ℹ️ 未配置 DOUYIN_COOKIE：私密/新号可能返回 0 作品（如捏个小鱼丸）")

    client = TikHubClient(api_key=api_key, base_url="https://api.tikhub.dev")
    stat_date = datetime.now(CST_).strftime("%Y-%m-%d")
    db = MonitorDB(os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db"))
    os.makedirs(os.path.join(SCRIPT_DIR, "reports"), exist_ok=True)
    deploy_dir = os.path.join(SCRIPT_DIR, "deploy")
    os.makedirs(deploy_dir, exist_ok=True)

    # 解析要跑的账号（把 -- 开头的 flag 与真正的 UID 参数分开）
    args = sys.argv[1:]
    from_db = "--from-db" in args
    batch = "--batch" in args
    uid_args = [a for a in args if not a.startswith("--")]
    uids, names = [], {}
    if batch:
        from config import MONITOR_ACCOUNTS
        idx_filter = None
        digits = [int(x) for x in uid_args if x.isdigit()]
        if digits:
            idx_filter = set(digits)
        for i, acc in enumerate(MONITOR_ACCOUNTS):
            uid = str(acc.get("uid", ""))
            if not uid or (idx_filter and (i + 1) not in idx_filter):
                continue
            uids.append(uid)
            names[uid] = acc.get("name", uid)
    elif not uid_args:
        uids, names = ["397396233431257"], {"397396233431257": "等晴天"}
    else:
        for a in uid_args:
            if a.isdigit() or a.startswith("MS4w"):
                uids.append(a)
                names.setdefault(a, f"UID_{a[:8]}")

    print(f"🚀 合并看板：共 {len(uids)} 个账号 | 统计日 {stat_date}"
          + (" | 数据源=数据库(保留历史全量)" if from_db else " | 数据源=实时API"))
    accounts = []
    for uid in uids:
        try:
            if from_db:
                d = load_account_from_db(db, uid, stat_date)
                if not d:
                    print(f"⚠️ {uid} 数据库无 {stat_date} 数据，跳过")
                    continue
            else:
                d = collect_account_data(client, uid, names.get(uid, uid), db, stat_date, cookie=cookie)
            accounts.append(d)
            print(f"✅ {uid} 昵称={d['profile']['nickname']} 作品={d['summary']['video_count']}/真实{d['profile'].get('total_count')}")
        except Exception as e:
            print(f"❌ {uid} 失败: {e}")
        time.sleep(1.5)

    if not accounts:
        print("❌ 无可用账号数据")
        sys.exit(1)

    # 合并看板
    data = {"stat_date": stat_date, "accounts": accounts}
    html = DETAIL_TEMPLATE.replace("{DATA_JSON}", json.dumps(data, ensure_ascii=False))
    out = os.path.join(SCRIPT_DIR, "reports", "multi_account.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    # 部署用：同一份写入 deploy/index.html（生成可分享链接）
    deploy_out = os.path.join(deploy_dir, "index.html")
    with open(deploy_out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📄 合并看板已生成: {out}")
    print(f"📦 部署副本: {deploy_out}")
    print(f"✅ 完成：{len(accounts)} 个账号")


if __name__ == "__main__":
    main()
