"""
抖音多账号「作品汇总面板」生成器（聚合视图 + 按日下钻 + 多维筛选）

数据来源：
  - 仅读取本地数据库 data/douyin_monitor.db（video_daily / snapshots）
  - 不调用任何外部 API，零消耗
  - 保留每个作品的「按日抓取」历史（video_daily 按 stat_date 存储，可逐日回看）

与 build_multi_account.py 的区别：
  - 去掉抓不到的字段：播放量、互动率
  - 所有账号作品聚合到一张可筛选表（账号 / 点赞数 / 发布日期）
  - 点开任意作品下钻其逐日数据（点赞/评论/转发/收藏 + 较前一日 Δ）

用法：
  python build_aggregate.py
输出：
  deploy/aggregate.html  （单文件，CSS/JS 内联，可分享）
"""

import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db")
CST = timezone(timedelta(hours=8))


def load_data():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row

    # ---- 账号档案（取每个 uid 最新一条快照）----
    accts = {}
    for r in c.execute(
        "SELECT account_uid, account_name, follower_count, raw_profile, captured_at "
        "FROM snapshots WHERE account_uid NOT LIKE 'MS4w%' ORDER BY captured_at DESC"
    ):
        uid = r["account_uid"]
        if uid in accts:
            continue
        rawp = {}
        if r["raw_profile"]:
            try:
                rawp = json.loads(r["raw_profile"])
            except Exception:
                rawp = {}
        accts[uid] = {
            "uid": uid,
            "nickname": r["account_name"] or uid,
            "follower": r["follower_count"] or 0,
            "sec_uid": rawp.get("sec_uid", "") or "",
            "avatar": rawp.get("avatar", "") or "",
        }

    # ---- 作品（全部日期，按 uid+aweme_id 聚合）----
    vmap = {}
    for r in c.execute(
        "SELECT account_uid, aweme_id, stat_date, desc, title, tags, create_time, "
        "digg_count, comment_count, share_count, collect_count, cover "
        "FROM video_daily WHERE account_uid NOT LIKE 'MS4w%' "
        "ORDER BY account_uid, aweme_id, stat_date"
    ):
        uid = r["account_uid"]
        if uid not in accts:
            continue  # 跳过没有档案的作品（理论上不应出现）
        key = (uid, r["aweme_id"])
        if key not in vmap:
            vmap[key] = {"uid": uid, "aweme_id": r["aweme_id"], "daily": []}
        vmap[key]["daily"].append({
            "date": r["stat_date"],
            "digg": r["digg_count"] or 0,
            "comm": r["comment_count"] or 0,
            "share": r["share_count"] or 0,
            "coll": r["collect_count"] or 0,
            "desc": r["desc"] or "",
            "tags": r["tags"] or "",
            "create_time": r["create_time"] or 0,
            "cover": r["cover"] or "",
        })

    # ---- 组装每条作品对象 ----
    videos = []
    for key, v in vmap.items():
        daily = sorted(v["daily"], key=lambda x: x["date"])
        latest = daily[-1]
        # 计算较前一日变化（基于最新两个快照）
        prev = daily[-2] if len(daily) >= 2 else None
        ddigg = (latest["digg"] - prev["digg"]) if prev else None
        dcomm = (latest["comm"] - prev["comm"]) if prev else None
        dshare = (latest["share"] - prev["share"]) if prev else None
        dcoll = (latest["coll"] - prev["coll"]) if prev else None
        acc = accts[v["uid"]]
        videos.append({
            "uid": v["uid"],
            "nickname": acc["nickname"],
            "sec_uid": acc["sec_uid"],
            "aweme_id": v["aweme_id"],
            "desc": latest["desc"],
            "tags": latest["tags"],
            "create_time": latest["create_time"],
            "cover": latest["cover"],
            "url": f"https://www.douyin.com/video/{v['aweme_id']}",
            "account_url": f"https://www.douyin.com/user/{acc['sec_uid']}" if acc["sec_uid"] else "",
            "digg": latest["digg"],
            "comm": latest["comm"],
            "share": latest["share"],
            "coll": latest["coll"],
            "eng": latest["digg"] + latest["comm"] + latest["share"] + latest["coll"],
            "ddigg": ddigg, "dcomm": dcomm, "dshare": dshare, "dcoll": dcoll,
            "n_days": len(daily),
            "daily": daily,
        })

    # 账号列表（供筛选下拉）
    accounts = [{"uid": a["uid"], "nickname": a["nickname"], "follower": a["follower"]}
               for a in accts.values()]
    accounts.sort(key=lambda x: x["nickname"])

    # 数据库里出现过的统计日（供说明）
    dates = sorted({d["date"] for v in vmap.values() for d in v["daily"]})

    c.close()
    return {
        "generated_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "stat_dates": dates,
        "accounts": accounts,
        "videos": videos,
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>抖音作品汇总面板</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2329; padding: 22px; }
  .wrap { max-width: 1280px; margin: 0 auto; }
  .topbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
  .topbar h1 { font-size:21px; }
  .badge { display:inline-block; background:#e8f5e9; color:#1b8a3a; font-size:12px;
           padding:2px 9px; border-radius:10px; font-weight:600; }
  .note { font-size:12px; color:#8a9099; margin-left:auto; }
  .kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:14px; }
  .kpi { background:#fff; border-radius:12px; padding:14px; box-shadow:0 2px 8px rgba(0,0,0,.05); text-align:center; }
  .kpi .v { font-size:22px; font-weight:700; color:#185fa5; }
  .kpi .l { font-size:12px; color:#8a9099; margin-top:3px; }
  /* filter bar */
  .filterbar { background:#fff; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.05);
               padding:14px 16px; margin-bottom:14px; display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; }
  .fitem { display:flex; flex-direction:column; gap:4px; }
  .fitem label { font-size:12px; color:#8a9099; }
  .fitem select, .fitem input { padding:7px 9px; border:1px solid #d9dee5; border-radius:8px; font-size:13px; min-width:120px; }
  .fitem input[type=number] { width:110px; }
  .fitem.row2 { flex-direction:row; gap:6px; align-items:flex-end; }
  .fitem.row2 input { width:96px; }
  .btn { background:#185fa5; color:#fff; border:none; padding:8px 16px; border-radius:8px;
         cursor:pointer; font-size:13px; font-weight:600; }
  .btn:hover { background:#134b85; }
  .btn.ghost { background:#eef2f7; color:#3a6ea5; }
  .btn.ghost:hover { background:#e1e8f1; }
  /* table */
  .card { background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(0,0,0,.06); padding:6px 0; overflow:hidden; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:11px 12px; text-align:left; border-bottom:1px solid #eef1f5; vertical-align:middle; }
  th { color:#8a9099; font-weight:600; background:#fafbfd; position:sticky; top:0; cursor:pointer; white-space:nowrap; }
  tbody tr:hover { background:#f0f6ff; }
  .av { width:34px; height:34px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; vertical-align:middle; margin-right:6px; }
  .acc { font-weight:700; color:#185fa5; }
  .acc-link { color:#185fa5; text-decoration:none; }
  .acc-link:hover { text-decoration:underline; }
  .num { font-variant-numeric:tabular-nums; }
  .cover { width:46px; height:62px; object-fit:cover; border-radius:6px; background:#e9edf3; }
  .cap-link { color:#185fa5; text-decoration:none; font-weight:600; }
  .cap-link:hover { text-decoration:underline; }
  .cap-text { display:block; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tags { margin-top:4px; }
  .tag { display:inline-block; background:#eef3fb; color:#3a6ea5; font-size:11px; padding:1px 7px; border-radius:9px; margin-right:4px; }
  .delta { font-weight:700; font-variant-numeric:tabular-nums; font-size:11px; }
  .delta.up { color:#e53935; } .delta.down { color:#2e7d32; } .delta.flat { color:#9aa0a8; }
  .open-btn { display:inline-block; background:#ff6a00; color:#fff; text-decoration:none; font-size:12px;
              padding:4px 10px; border-radius:7px; font-weight:600; }
  .open-btn:hover { background:#e75f00; }
  .daytag { display:inline-block; background:#eef4f9; color:#3a6ea5; font-size:11px; padding:1px 7px; border-radius:9px; }
  .muted { color:#8a9099; }
  .empty { text-align:center; color:#9aa0a8; padding:40px; font-size:14px; }
  /* modal */
  .mask { position:fixed; inset:0; background:rgba(20,30,45,.45); display:none; align-items:center; justify-content:center; z-index:50; }
  .modal { background:#fff; border-radius:14px; width:min(640px,92vw); max-height:86vh; overflow:auto; padding:22px; box-shadow:0 10px 40px rgba(0,0,0,.2); }
  .modal h3 { font-size:16px; margin-bottom:4px; }
  .modal .sub { font-size:12px; color:#8a9099; margin-bottom:14px; }
  .modal .close { float:right; cursor:pointer; color:#9aa0a8; font-size:20px; line-height:1; }
  .modal table { font-size:13px; }
  .modal th, .modal td { padding:8px 10px; }
  .bar { height:6px; background:#e7edf5; border-radius:3px; margin-top:4px; width:90px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:#34a853; }
  footer { text-align:center; color:#9aa0a8; font-size:12px; margin-top:14px; line-height:1.7; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📊 抖音作品汇总面板 <span class="badge">真实数据 · 聚合视图</span></h1>
    <span class="note" id="genNote"></span>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="filterbar">
    <div class="fitem">
      <label>账号</label>
      <select id="fAccount"></select>
    </div>
    <div class="fitem">
      <label>点赞数 ≥</label>
      <input type="number" id="fLikeMin" placeholder="0" min="0" value="0">
    </div>
    <div class="fitem">
      <label>点赞数 ≤</label>
      <input type="number" id="fLikeMax" placeholder="不限" min="0">
    </div>
    <div class="fitem row2">
      <div class="fitem">
        <label>发布日期 从</label>
        <input type="date" id="fDateFrom">
      </div>
      <div class="fitem">
        <label>至</label>
        <input type="date" id="fDateTo">
      </div>
    </div>
    <div class="fitem">
      <label>搜索文案/标签</label>
      <input type="text" id="fSearch" placeholder="关键词…" style="min-width:160px">
    </div>
    <div class="fitem">
      <label>排序</label>
      <select id="fSort">
        <option value="digg_desc">点赞（高→低）</option>
        <option value="digg_asc">点赞（低→高）</option>
        <option value="eng_desc">总互动（高→低）</option>
        <option value="create_desc">发布时间（新→旧）</option>
        <option value="create_asc">发布时间（旧→新）</option>
      </select>
    </div>
    <button class="btn ghost" id="fReset">重置</button>
  </div>

  <div class="card">
    <table>
      <thead><tr>
        <th data-sort="nickname">账号</th>
        <th>作品（↗跳转抖音）</th>
        <th data-sort="create_time">发布时间</th>
        <th data-sort="digg">点赞</th>
        <th data-sort="comm">评论</th>
        <th data-sort="share">转发</th>
        <th data-sort="coll">收藏</th>
        <th data-sort="eng">总互动</th>
        <th>较前一日</th>
        <th>抓取天数</th>
        <th>操作</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="empty" id="empty" style="display:none">没有符合筛选条件的作品</div>
  </div>

  <footer id="footer"></footer>
</div>

<!-- 逐日下钻弹窗 -->
<div class="mask" id="mask" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <span class="close" onclick="closeModal()">×</span>
    <h3 id="mTitle"></h3>
    <div class="sub" id="mSub"></div>
    <table>
      <thead><tr>
        <th>统计日</th><th>点赞</th><th>评论</th><th>转发</th><th>收藏</th>
        <th>较前一日 Δ</th><th>点赞趋势</th>
      </tr></thead>
      <tbody id="mBody"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = {DATA_JSON};
function esc(s){ s=(s==null)?'':String(s); return s.replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmt(n){ n=Number(n)||0;
  if(n>=1e8) return (n/1e8).toFixed(1)+'亿';
  if(n>=1e4) return (n/1e4).toFixed(1)+'万';
  return String(n); }
function dateStr(ts){ if(!ts) return '-';
  const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`; }
function timeStr(ts){ if(!ts) return '-';
  const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
function deltaCell(n){ if(n==null) return '<span class="muted">—</span>';
  if(n===0) return '<span class="delta flat">0</span>';
  const cls=n>0?'up':'down'; const s=n>0?'+':'';
  return `<span class="delta ${cls}">${s}${fmt(n)}</span>`; }

// ---- 顶部说明 / KPI ----
document.getElementById('genNote').textContent = '生成于 ' + DATA.generated_at + ' · 统计日：' + DATA.stat_dates.join('、');
const totVid = DATA.videos.length;
const totDigg = DATA.videos.reduce((s,v)=>s+v.digg,0);
const totAcc = DATA.accounts.length;
const multiDay = DATA.videos.filter(v=>v.n_days>=2).length;
document.getElementById('kpis').innerHTML = [
  ['作品总数', fmt(totVid)],
  ['监控账号', totAcc],
  ['合计点赞', fmt(totDigg)],
  ['有多日数据作品', multiDay + ' / ' + totVid],
].map(([l,v])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

// ---- 账号下拉 ----
const fAccount = document.getElementById('fAccount');
fAccount.innerHTML = '<option value="__all__">全部账号</option>' +
  DATA.accounts.map(a=>`<option value="${a.uid}">${esc(a.nickname)}（${fmt(a.follower)}粉）</option>`).join('');

// ---- 渲染表格 ----
const tbody = document.getElementById('tbody');
function render(){
  const acc = fAccount.value;
  const likeMin = Number(document.getElementById('fLikeMin').value||0);
  const likeMaxRaw = document.getElementById('fLikeMax').value;
  const likeMax = likeMaxRaw? Number(likeMaxRaw): Infinity;
  const df = document.getElementById('fDateFrom').value;
  const dt = document.getElementById('fDateTo').value;
  const q = document.getElementById('fSearch').value.trim().toLowerCase();
  const sort = document.getElementById('fSort').value;

  let rows = DATA.videos.filter(v=>{
    if(acc!=='__all__' && v.uid!==acc) return false;
    if(v.digg < likeMin || v.digg > likeMax) return false;
    const cd = dateStr(v.create_time);
    if(df && cd < df) return false;
    if(dt && cd > dt) return false;
    if(q && !((v.desc||'').toLowerCase().includes(q) || (v.tags||'').toLowerCase().includes(q))) return false;
    return true;
  });

  const cmp = {
    digg_desc:(a,b)=>b.digg-a.digg, digg_asc:(a,b)=>a.digg-b.digg,
    eng_desc:(a,b)=>b.eng-a.eng,
    create_desc:(a,b)=>b.create_time-a.create_time, create_asc:(a,b)=>a.create_time-b.create_time,
    nickname:(a,b)=>a.nickname.localeCompare(b.nickname,'zh'),
  }[sort] || ((a,b)=>b.digg-a.digg);
  rows.sort(cmp);

  if(!rows.length){ tbody.innerHTML=''; document.getElementById('empty').style.display='block'; return; }
  document.getElementById('empty').style.display='none';

  tbody.innerHTML = rows.map((v,i)=>{
    const tags = (v.tags||'').split(',').filter(Boolean).map(t=>`<span class="tag">#${esc(t)}</span>`).join('');
    const cover = v.cover?`<img class="cover" src="${esc(v.cover)}" loading="lazy" alt="">`:`<div class="cover"></div>`;
    const dCell = deltaCell(v.ddigg);
    return `<tr>
      <td><span class="acc">${esc(v.nickname)}</span></td>
      <td>${cover}
        <a class="cap-link" href="${esc(v.url)}" target="_blank" title="在抖音打开">${esc((v.desc||'(无文案)').split('\n')[0])} <span style="color:#ff6a00">↗</span></a>
        <div class="tags">${tags}</div></td>
      <td class="num muted">${timeStr(v.create_time)}</td>
      <td class="num">${fmt(v.digg)}</td>
      <td class="num">${fmt(v.comm)}</td>
      <td class="num">${fmt(v.share)}</td>
      <td class="num">${fmt(v.coll)}</td>
      <td class="num">${fmt(v.eng)}</td>
      <td>${dCell}</td>
      <td><span class="daytag">${v.n_days} 天</span></td>
      <td><button class="open-btn" onclick="openModal('${esc(v.uid)}','${esc(v.aweme_id)}')">查看每日</button></td>
    </tr>`;
  }).join('');
}

// ---- 表头点击排序 ----
document.querySelectorAll('th[data-sort]').forEach(th=>{
  th.onclick = ()=>{
    const m = {nickname:'nickname', create_time:'create_desc', digg:'digg_desc',
               comm:'digg_desc', share:'digg_desc', coll:'digg_desc', eng:'eng_desc'};
    const map = {'nickname':'nickname','create_time':'create_desc','digg':'digg_desc','comm':'digg_desc','share':'digg_desc','coll':'digg_desc','eng':'eng_desc'};
    const key = th.getAttribute('data-sort');
    const sel = document.getElementById('fSort');
    if(key==='nickname') sel.value='nickname';
    else if(key==='create_time') sel.value = (sel.value==='create_desc')?'create_asc':'create_desc';
    else if(key==='digg'||key==='comm'||key==='share'||key==='coll'||key==='eng'){
      if(key==='eng') sel.value = (sel.value==='eng_desc')?'digg_desc':'eng_desc';
      else sel.value = (sel.value==='digg_desc')?'digg_asc':'digg_desc';
    }
    render();
  };
});

// ---- 逐日下钻弹窗 ----
function openModal(uid, awemeId){
  const v = DATA.videos.find(x=>x.uid===uid && x.aweme_id===awemeId);
  if(!v) return;
  document.getElementById('mTitle').textContent = (v.desc||'(无文案)').split('\n')[0];
  document.getElementById('mSub').innerHTML =
    `账号：<a class="acc-link" href="${esc(v.account_url)}" target="_blank">${esc(v.nickname)} ↗</a> · ` +
    `作品 ID：${esc(v.aweme_id)} · 共 ${v.n_days} 个统计日`;
  const maxDigg = Math.max(...v.daily.map(d=>d.digg), 1);
  let prev=null;
  const body = v.daily.map(d=>{
    let dcell='<span class="muted">—</span>';
    if(prev!==null){
      const diff=d.digg-prev;
      if(diff!==0){ const cls=diff>0?'up':'down'; const s=diff>0?'+':'';
        dcell=`<span class="delta ${cls}">${s}${fmt(diff)}</span>`; }
      else dcell='<span class="delta flat">0</span>';
    }
    const pct=Math.round(d.digg/maxDigg*100);
    const row=`<tr>
      <td class="num">${d.date}</td>
      <td class="num">${fmt(d.digg)}</td>
      <td class="num">${fmt(d.comm)}</td>
      <td class="num">${fmt(d.share)}</td>
      <td class="num">${fmt(d.coll)}</td>
      <td>${dcell}</td>
      <td><div class="bar"><i style="width:${pct}%"></i></div></td>
    </tr>`;
    prev=d.digg; return row;
  }).join('');
  document.getElementById('mBody').innerHTML = body;
  document.getElementById('mask').style.display='flex';
}
function closeModal(){ document.getElementById('mask').style.display='none'; }
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeModal(); });

// ---- 事件绑定 ----
['fAccount','fLikeMin','fLikeMax','fDateFrom','fDateTo','fSearch','fSort'].forEach(id=>{
  document.getElementById(id).addEventListener('input', render);
  document.getElementById(id).addEventListener('change', render);
});
document.getElementById('fReset').onclick = ()=>{
  fAccount.value='__all__';
  document.getElementById('fLikeMin').value=0;
  document.getElementById('fLikeMax').value='';
  document.getElementById('fDateFrom').value='';
  document.getElementById('fDateTo').value='';
  document.getElementById('fSearch').value='';
  document.getElementById('fSort').value='digg_desc';
  render();
};

document.getElementById('footer').innerHTML =
  '数据来源：本地数据库（TikHub 抓取快照）· 统计日 ' + DATA.stat_dates.join('、') + '<br>' +
  '已移除无法抓取的「播放量 / 互动率」字段；点「查看每日」可下钻该作品逐日数据。' +
  (DATA.stat_dates.length<2 ? '<br>当前仅 1 个统计日，逐日曲线将在多次抓取后变丰富。' : '');

render();
</script>
</body>
</html>
"""


def main():
    data = load_data()
    html = TEMPLATE.replace("{DATA_JSON}", json.dumps(data, ensure_ascii=False))
    out_dir = os.path.join(SCRIPT_DIR, "deploy")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "aggregate.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 汇总面板已生成: {out}")
    print(f"   账号数={len(data['accounts'])} 作品数={len(data['videos'])} "
          f"统计日={data['stat_dates']} 多日数据作品={sum(1 for v in data['videos'] if v['n_days']>=2)}")


if __name__ == "__main__":
    main()
