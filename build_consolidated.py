"""
抖音多账号监控看板 —— 合并版（单文件）

把「账号总览矩阵 + 账号下钻」与「全部作品汇总 + 多维筛选」融合到同一个
单文件 HTML 里，顶部用 Tab 切换，两个视图共用「查看每日」逐日下钻弹窗。

数据来源：仅读取本地 data/douyin_monitor.db，零 API 调用、零消耗。
字段：已移除无法抓取的「播放量 / 互动率」，仅保留真实可取的
      粉丝 / 作品数 / 点赞 / 评论 / 转发 / 收藏 + 逐日增量。

用法：
  python build_consolidated.py
输出：
  deploy/index.html  （合并后的单文件看板，可分享）
"""

import os
import sys
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_multi_account import load_account_from_db, MonitorDB, CST_

DB_PATH = os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db")

# 监控账号列表：单一数据源改为 accounts.json（网页操作面板可读写）
# 仅在 accounts.json 缺失/为空时回退到下方兜底列表
_FALLBACK_UIDS = [
    "2697552638795803",      # 小杏福
    "7650684889516180529",  # 發財喵
    "1716801736283996",     # 捏个小鱼丸
    "7674544304131425329",
    "3762968190780163",
    "1096648367808554",
    "7629528523569693745",
    "7676013645696123963",
    "2697517525905482",
    "3014201962932036",
    "7675642921655567397",  # 白咪饭
    "1694786943199561",     # 幸运百分百。
    "3049374778393848",     # 油饼久吃
    "604067175866235",      # 泥不要哇哇叫
    "7668478121516123194",  # 今天一定早睡
    "1083498019428832",     # 小小皮
    "7662902822904562746",  # 咪否
    "7650764311963681841",  # 青提涩
    "3313257525808732",     # 凡夫柿子
    "7660691145656239153",  # 带明第一神童
    "2574399090487555",     # u米
    "2860267033869440",     # 巧克力zz
]
try:
    from accounts import load_uids
    MONITOR_UIDS = load_uids() or _FALLBACK_UIDS
except Exception:
    MONITOR_UIDS = _FALLBACK_UIDS


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>抖音多账号监控看板（总览 + 汇总）</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2329; padding: 24px; }
  .wrap { max-width: 1280px; margin: 0 auto; }
  .badge-real { display:inline-block; background:#e8f5e9; color:#1b8a3a; font-size:12px;
                padding:2px 8px; border-radius:10px; margin-left:8px; font-weight:600;}
  .topbar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
  .topbar h1 { font-size:22px; }
  .tabs { display:flex; gap:8px; margin-bottom:16px; }
  .tab { background:#eef2f7; color:#3a6ea5; border:none; padding:9px 18px; border-radius:10px;
         cursor:pointer; font-size:14px; font-weight:600; }
  .tab:hover { background:#e1e8f1; }
  .tab.active { background:#185fa5; color:#fff; }
  .global-kpis { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:18px; }
  .gkpi { background:#fff; border-radius:12px; padding:14px; box-shadow:0 2px 8px rgba(0,0,0,.05); text-align:center; }
  .gkpi .v { font-size:22px; font-weight:700; color:#185fa5; }
  .gkpi .l { font-size:12px; color:#8a9099; margin-top:3px; }
  .back-btn { display:none; background:#185fa5; color:#fff; border:none; padding:8px 14px;
              border-radius:8px; cursor:pointer; font-size:13px; margin-bottom:14px; }
  .back-btn:hover { background:#134b85; }
  .card { background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(0,0,0,.06); padding:20px; margin-bottom:20px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:12px 10px; text-align:left; border-bottom:1px solid #eef1f5; vertical-align:middle; }
  th { color:#8a9099; font-weight:600; background:#fafbfd; cursor:default; white-space:nowrap; }
  th.sortable { cursor:pointer; }
  tbody tr.matrix-row { cursor:pointer; }
  tbody tr.matrix-row:hover { background:#f0f6ff; }
  tbody tr:hover { background:#f7faff; }
  .avatar { width:46px; height:46px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; }
  .acc-name { font-weight:700; color:#185fa5; display:flex; align-items:center; gap:6px; }
  .acc-link { color:#185fa5; text-decoration:none; }
  .acc-link:hover { text-decoration:underline; }
  .acc { font-weight:700; color:#185fa5; }
  .verify { color:#ffb300; }
  .num { font-variant-numeric:tabular-nums; }
  .chip { display:inline-block; background:#f0f4f9; color:#3a6ea5; font-size:11px;
          padding:2px 8px; border-radius:9px; margin:2px 2px 0 0; }
  .chip.warn { background:#fdecea; color:#c0392b; }
  .chip.ok { background:#e8f5e9; color:#2e7d32; }
  .muted { color:#8a9099; }
  .profile { display:flex; gap:20px; align-items:center; flex-wrap:wrap; }
  .avatar-lg { width:84px; height:84px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; }
  .pinfo h2 { font-size:24px; display:flex; align-items:center; }
  .open-btn { display:inline-block; margin-left:10px; background:#ff6a00; color:#fff; text-decoration:none;
              font-size:13px; padding:5px 12px; border-radius:8px; font-weight:600; cursor:pointer; }
  .open-btn:hover { background:#e75f00; }
  .open-btn:disabled { opacity:.4; cursor:not-allowed; }
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
  .cmp-card { background:#fffaf0; border:1px solid #ffe0b2; }
  .cmp-card h3 { font-size:15px; margin-bottom:10px; color:#b26a00; }
  .cmp-chips { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
  .cmp-chip { background:#fff3e0; border-radius:10px; padding:8px 14px; font-size:13px; color:#8a5a00; }
  .cmp-chip b { font-size:18px; color:#b26a00; margin-left:6px; }
  .del-list { font-size:13px; color:#8a5a00; }
  .del-item { padding:4px 0; border-bottom:1px dashed #ffe0b2; }
  .delta { font-weight:700; font-variant-numeric:tabular-nums; }
  .delta.up { color:#e53935; } .delta.down { color:#2e7d32; } .delta.flat { color:#9aa0a8; }
  .b-new { background:#e3f2fd; color:#1565c0; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-cap { background:#fce4ec; color:#c2185b; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-tag { background:#e8f5e9; color:#2e7d32; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .b-del { background:#fdecea; color:#c0392b; border-radius:6px; padding:1px 6px; font-size:11px; font-weight:700; }
  .del-row td { background:#faf7f7; }
  .del-row .cap-link { color:#9aa0a8; text-decoration: line-through; }
  .gate-banner { background:#fdecea; color:#c0392b; border:1px solid #f5c6c0; border-radius:10px;
                 padding:10px 14px; font-size:13px; line-height:1.6; margin-bottom:16px; }
  .gate-banner code { background:#fff; padding:1px 5px; border-radius:4px; font-size:12px; }
  /* 全部作品筛选器 */
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
  .daytag { display:inline-block; background:#eef4f9; color:#3a6ea5; font-size:11px; padding:1px 7px; border-radius:9px; }
  .empty { text-align:center; color:#9aa0a8; padding:40px; font-size:14px; }
  /* modal */
  .mask { position:fixed; inset:0; background:rgba(20,30,45,.45); display:none; align-items:center; justify-content:center; z-index:50; }
  .modal { background:#fff; border-radius:14px; width:min(680px,92vw); max-height:86vh; overflow:auto; padding:22px; box-shadow:0 10px 40px rgba(0,0,0,.2); }
  .modal h3 { font-size:16px; margin-bottom:4px; }
  .modal .sub { font-size:12px; color:#8a9099; margin-bottom:14px; }
  .modal .close { float:right; cursor:pointer; color:#9aa0a8; font-size:20px; line-height:1; }
  .modal table { font-size:13px; }
  .modal th, .modal td { padding:8px 10px; }
  .bar { height:6px; background:#e7edf5; border-radius:3px; margin-top:4px; width:90px; overflow:hidden; }
  .bar > i { display:block; height:100%; background:#34a853; }
  footer { text-align:center; color:#9aa0a8; font-size:12px; margin-top:10px; line-height:1.7; }
  /* 可选对比日期 */
  .cmpbar { display:flex; gap:18px; align-items:center; flex-wrap:wrap; background:#fff;
            border:1px solid #e3e9f2; border-radius:12px; padding:10px 16px; margin-bottom:14px;
            box-shadow:0 1px 6px rgba(0,0,0,.04); }
  .cmpbar .cmp-label { font-size:13px; color:#5a6068; }
  .cmpbar .cmp-label b { color:#185fa5; }
  .cmpbar select { padding:6px 10px; border:1px solid #d9dee5; border-radius:8px; font-size:13px; background:#fafbfd; }
  .cmpbar .cmp-note { font-size:12px; color:#8a9099; margin-left:auto; }
  .cmpbar .cmp-note.warn { color:#c0392b; }
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📊 抖音多账号监控看板 <span class="badge-real">真实数据</span></h1>
  </div>

  <div class="tabs">
    <button class="tab active" id="tabOverview" onclick="switchTab('overview')">📋 账号总览</button>
    <button class="tab" id="tabAll" onclick="switchTab('all')">📊 全部作品汇总</button>
  </div>

  <div class="cmpbar">
    <span class="cmp-label">📅 对比基准（最新）：<b id="cmpBase">—</b></span>
    <span class="cmp-label">对比对象：
      <select id="cmpSelect"></select>
    </span>
    <span class="cmp-note" id="cmpNote"></span>
  </div>

  <div class="global-kpis" id="gkpis"></div>

  <div id="gateBanner" style="display:none" class="gate-banner">
    ⚠️ 部分账号作品被抖音「登录态」挡住（接口返回 not_login_module），当前数据可能不完整。
    如需准确全量数据，请在 <code>douyin-monitor.env.txt</code> 配置 <code>DOUYIN_COOKIE=</code> 后重跑。
  </div>

  <button class="back-btn" id="backBtn" onclick="switchTab('overview')">← 返回总览</button>

  <!-- 总览矩阵 -->
  <div class="card" id="overview">
    <div class="filterbar" style="margin-bottom:12px">
      <div class="fitem"><label>粉丝数 ≥</label><input type="number" id="mFollowerMin" placeholder="0" min="0" value="0"></div>
      <div class="fitem"><label>粉丝数 ≤</label><input type="number" id="mFollowerMax" placeholder="不限" min="0"></div>
      <div class="fitem"><label>作品数 ≥</label><input type="number" id="mVideoMin" placeholder="0" min="0" value="0"></div>
      <div class="fitem"><label>变化</label>
        <select id="mChange">
          <option value="__all__">全部</option>
          <option value="has_new">有新增</option>
          <option value="has_caption">有文案变化</option>
          <option value="has_tags">有标签变化</option>
          <option value="has_deleted">有删除/隐藏</option>
          <option value="no_change">无变化（基线）</option>
        </select>
      </div>
      <div class="fitem"><label>搜索账号</label><input type="text" id="mSearch" placeholder="昵称/抖音号…" style="min-width:130px"></div>
      <button class="btn ghost" id="mReset">重置</button>
    </div>
    <div style="font-size:12px;color:#8a9099;margin-bottom:8px" id="matrixCount"></div>
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
        <select id="dChange" onchange="renderDetail()">
          <option value="__all__">全部变化</option>
          <option value="new">新增</option>
          <option value="caption">文案变化</option>
          <option value="tags">标签变化</option>
          <option value="deleted">删除/隐藏</option>
          <option value="none">无变化</option>
        </select>
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
          <th>点赞Δ</th><th>评论Δ</th><th>转发Δ</th><th>收藏Δ</th>
          <th>变化</th><th>操作</th>
        </tr></thead>
        <tbody id="d-tbody"></tbody>
      </table>
      </div>
    </div>
  </div>

  <!-- 全部作品汇总 -->
  <div id="allview" style="display:none">
    <div class="filterbar">
      <div class="fitem"><label>账号</label><select id="fAccount"></select></div>
      <div class="fitem"><label>点赞数 ≥</label><input type="number" id="fLikeMin" placeholder="0" min="0" value="0"></div>
      <div class="fitem"><label>点赞数 ≤</label><input type="number" id="fLikeMax" placeholder="不限" min="0"></div>
      <div class="fitem row2">
        <div class="fitem"><label>发布日期 从</label><input type="date" id="fDateFrom"></div>
        <div class="fitem"><label>至</label><input type="date" id="fDateTo"></div>
      </div>
      <div class="fitem"><label>搜索文案/标签</label><input type="text" id="fSearch" placeholder="关键词…" style="min-width:160px"></div>
      <div class="fitem"><label>变化</label>
        <select id="fChange">
          <option value="__all__">全部</option>
          <option value="new">新增</option>
          <option value="caption">文案变化</option>
          <option value="tags">标签变化</option>
          <option value="deleted">删除/隐藏</option>
          <option value="none">无变化</option>
        </select>
      </div>
      <div class="fitem"><label>排序</label>
        <select id="fSort">
          <option value="digg_desc">点赞（高→低）</option>
          <option value="digg_asc">点赞（低→高）</option>
          <option value="eng_desc">总互动（高→低）</option>
          <option value="create_desc">发布时间（新→旧）</option>
          <option value="create_asc">发布时间（旧→新）</option>
        </select>
      </div>
      <button class="btn ghost" id="fReset">重置</button>
      <button class="btn" id="fExport" style="background:#185fa5;color:#fff;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600;margin-left:8px">📥 导出 Excel</button>
    </div>
    <div class="card">
      <div style="font-size:12px;color:#8a9099;margin-bottom:8px" id="allCount"></div>
      <div style="overflow-x:auto">
      <table>
        <thead><tr>
          <th>账号</th><th>作品（↗跳转抖音）</th><th>发布时间</th>
          <th class="sortable" data-sort="digg">点赞</th>
          <th class="sortable" data-sort="comm">评论</th>
          <th class="sortable" data-sort="share">转发</th>
          <th class="sortable" data-sort="coll">收藏</th>
          <th class="sortable" data-sort="eng">总互动</th>
          <th>变化</th><th>抓取天数</th><th>操作</th>
        </tr></thead>
        <tbody id="tbodyA"></tbody>
      </table>
      </div>
      <div class="empty" id="allEmpty" style="display:none">没有符合筛选条件的作品</div>
    </div>
  </div>

  <footer id="footer"></footer>
</div>

<!-- 逐日下钻弹窗（总览下钻 + 全部作品共用） -->
<div class="mask" id="dMask" onclick="if(event.target===this)closeDailyModal()">
  <div class="modal">
    <span class="close" onclick="closeDailyModal()">×</span>
    <h3 id="dmTitle"></h3>
    <div class="sub" id="dmSub"></div>
    <button class="btn" id="dmExport" style="margin:4px 0 12px" onclick="exportDaily()">📥 导出当前作品逐日数据（Excel / CSV）</button>
    <table>
      <thead><tr><th>统计日</th><th>点赞</th><th>评论</th><th>转发</th><th>收藏</th><th>较前一日 Δ</th><th>点赞趋势</th></tr></thead>
      <tbody id="dmBody"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = {DATA_JSON};

// ===== 可选对比日期引擎 =====
// DATA.stat_dates 为升序；最新基准 = 最后一个统计日；对比对象 = 用户在下拉中任选的更早日期。
const STAT_DATES = (DATA.stat_dates||[]).slice().sort();
const LATEST_DATE = STAT_DATES.length ? STAT_DATES[STAT_DATES.length-1] : null;
const state = { cmpDate: STAT_DATES.length>=2 ? STAT_DATES[STAT_DATES.length-2] : null };

function accLatest(a){ return (a.dates&&a.dates.length)? a.dates[a.dates.length-1] : (a.stat_date||LATEST_DATE); }
function snapMap(a, date){
  const arr = (a.snaps && a.snaps[date]) || [];
  const m = {};
  arr.forEach(r=>{ m[String(r.aweme_id)] = r; });
  return m;
}

// 针对当前选中的对比日期，计算每个账号的逐日对比（新增/文案变/标签变/删除隐藏）与每个作品的逐日标记。
function applyComparison(){
  DATA.accounts.forEach(a=>{
    const latest = accLatest(a);
    const cmp = state.cmpDate;
    const latestMap = snapMap(a, latest);
    const cmpMap = cmp ? snapMap(a, cmp) : {};
    const cmp_ = { has_prior:false, prior_date: cmp||'', new_count:0, changed_caption:0,
                   changed_tags:0, deleted_count:0, deleted:[], cmp_unavailable:false };
    if(!cmp || !(a.dates||[]).includes(cmp) || cmp>=latest){
      cmp_.cmp_unavailable = true;
    } else {
      cmp_.has_prior = true;
      Object.keys(latestMap).forEach(aid=>{
        const L = latestMap[aid], C = cmpMap[aid];
        if(!C) cmp_.new_count++;
        else {
          if((L.desc||'') !== (C.desc||'')) cmp_.changed_caption++;
          if((L.tags||'') !== (C.tags||'')) cmp_.changed_tags++;
        }
      });
      Object.keys(cmpMap).forEach(aid=>{
        if(!latestMap[aid]){
          cmp_.deleted_count++;
          const C = cmpMap[aid];
          cmp_.deleted.push({ aweme_id:aid, desc:C.desc||'(无文案)', digg:C.digg, date:cmp });
        }
      });
    }
    a._cmp = cmp_;
    // 逐作品标记
    a.videos.forEach(v=>{
      const aid = String(v.aweme_id);
      const L = latestMap[aid], C = cmpMap[aid];
      const f = { has_cmp:cmp_.has_prior, is_new:false, deleted:!!v.deleted,
                  caption_changed:false, tags_changed:false,
                  ddigg:null, dcomm:null, dshare:null, dcoll:null };
      if(cmp_.has_prior){
        if(L && C){
          f.caption_changed = (L.desc||'') !== (C.desc||'');
          f.tags_changed    = (L.tags||'') !== (C.tags||'');
          f.ddigg = (L.digg||0) - (C.digg||0);
          f.dcomm = (L.comm||0) - (C.comm||0);
          f.dshare= (L.share||0) - (C.share||0);
          f.dcoll = (L.coll||0) - (C.coll||0);
        } else if(L && !C){
          f.is_new = true;
        } else if(!L && C){
          f.deleted = true; f.is_new = false;
        }
      } else {
        f.is_new=false; f.caption_changed=false; f.tags_changed=false;
        f.ddigg=f.dcomm=f.dshare=f.dcoll=null;
      }
      v._c = f;
    });
  });
}
function flagOf(v){ return v._c || { has_cmp:false, is_new:!!v.is_new, deleted:!!v.deleted,
  caption_changed:!!v.caption_changed, tags_changed:!!v.tags_changed,
  ddigg:v.ddigg, dcomm:v.dcomm, dshare:v.dshare, dcoll:v.dcoll }; }

function esc(s){ s = (s==null)?'':String(s); return s.replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
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
function delta(n){ if(n==null) return '<span class="muted">—</span>';
  if(n===0) return '0';
  const cls=n>0?'up':'down'; const s=n>0?'+':'';
  return '<span class="delta '+cls+'">'+s+fmt(n)+'</span>'; }
function deltaCell(n){ if(n==null) return '<span class="muted">—</span>';
  if(n===0) return '<span class="delta flat">0</span>';
  const cls=n>0?'up':'down'; const s=n>0?'+':'';
  return `<span class="delta ${cls}">${s}${fmt(n)}</span>`; }
function changeBadges(v){ const f=flagOf(v); const c=[];
  if(f.deleted) c.push('<span class="b-del">已删除</span>');
  if(f.is_new) c.push('<span class="b-new">新</span>');
  if(f.caption_changed) c.push('<span class="b-cap">文变</span>');
  if(f.tags_changed) c.push('<span class="b-tag">签变</span>');
  return c.length?c.join(' '):'<span class="muted">—</span>'; }
const engOf = v => (v.digg||0)+(v.comm||0)+(v.share||0)+(v.coll||0);

// 全部作品扁平列表（来自所有账号的 videos）
const ALL = DATA.accounts.flatMap(a => a.videos.map(v => ({...v, uid: a.profile.uid})));

// ===== 逐日下钻弹窗（通用） =====
let currentDailyV = null;
function openDailyModal(v){
  if(!v || !(v.daily||[]).length){ return; }
  currentDailyV = v;
  document.getElementById('dmTitle').textContent = (v.desc||'(无文案)').split('\n')[0];
  const accName = v.nickname || '未知账号';
  const accLink = v.account_url
    ? ` · <a class="acc-link" href="${esc(v.account_url)}" target="_blank">${esc(accName)} ↗</a>`
    : ` · ${esc(accName)}`;
  document.getElementById('dmSub').innerHTML =
    '账号：' + accLink + ' · 作品 ID：' + esc(v.aweme_id) + ' · 共 ' + v.daily.length + ' 个统计日';
  const daily = v.daily||[];
  const maxDigg = Math.max(...daily.map(d=>d.digg),1);
  let prev=null;
  document.getElementById('dmBody').innerHTML = daily.map(d=>{
    let dc='<span class="muted">—</span>';
    if(prev!==null){
      const diff=d.digg-prev;
      if(diff!==0){ const cls=diff>0?'up':'down'; const s=diff>0?'+':'';
        dc=`<span class="delta ${cls}">${s}${fmt(diff)}</span>`; }
      else dc='<span class="delta flat">0</span>';
    }
    const pct=Math.round(d.digg/maxDigg*100);
    return `<tr><td class="num">${d.date}</td><td class="num">${fmt(d.digg)}</td>`+
      `<td class="num">${fmt(d.comm)}</td><td class="num">${fmt(d.share)}</td>`+
      `<td class="num">${fmt(d.coll)}</td><td>${dc}</td>`+
      `<td><div class="bar"><i style="width:${pct}%"></i></div></td></tr>`;
    prev=d.digg;
  }).join('');
  document.getElementById('dMask').style.display='flex';
}
function closeDailyModal(){ document.getElementById('dMask').style.display='none'; }
document.addEventListener('keydown', e=>{ if(e.key==='Escape') closeDailyModal(); });

// 导出当前作品逐日数据（Excel 兼容 CSV，UTF-8 BOM）
function exportDaily(){
  if(!currentDailyV || !(currentDailyV.daily||[]).length){ alert('该作品暂无逐日数据可导出'); return; }
  const v=currentDailyV, daily=v.daily||[];
  let csv='\uFEFF';
  csv+='统计日,账号,作品ID,作品文案,点赞,评论,转发,收藏,较前一日点赞Δ,抖音链接\n';
  let prev=null;
  daily.forEach(d=>{
    let diff='';
    if(prev!==null){ const x=d.digg-prev; diff=(x>0?'+':'')+x; }
    const desc=String(v.desc||'').replace(/"/g,'""').replace(/\n/g,' ');
    csv+=`"${d.date}","${v.nickname||''}","${String(v.aweme_id||'')}","${desc}",${d.digg||0},${d.comm||0},${d.share||0},${d.coll||0},"${diff}","${v.url||''}"\n`;
    prev=d.digg;
  });
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  const ts=new Date().toISOString().slice(0,10);
  a.download='抖音作品逐日_'+v.aweme_id+'_'+ts+'.csv';
  a.click(); URL.revokeObjectURL(a.href);
}

// ===== 总览矩阵 =====
function showOverview(){
  document.getElementById('detail').style.display='none';
  document.getElementById('overview').style.display='block';
  document.getElementById('backBtn').style.display='none';
  renderMatrix();
}

// 仅渲染总览矩阵（供筛选 / 切换对比日期时复用，不触碰视图显隐状态）
function renderMatrix(){
  // 读取筛选条件
  const fMinEl=document.getElementById('mFollowerMin');
  const fMin=fMinEl?Number(fMinEl.value||0):0;
  const fMaxEl=document.getElementById('mFollowerMax');
  const fMaxRaw=fMaxEl?fMaxEl.value:'';
  const fMax=fMaxRaw?Number(fMaxRaw):Infinity;
  const vMinEl=document.getElementById('mVideoMin');
  const vMin=vMinEl?Number(vMinEl.value||0):0;
  const chEl=document.getElementById('mChange');
  const change=chEl?chEl.value:'__all__';
  const qEl=document.getElementById('mSearch');
  const q=qEl?qEl.value.trim().toLowerCase():'';

  // 筛选账号（使用运行时计算的 _cmp）
  let filtered = DATA.accounts.filter((a, i)=>{
    const p=a.profile, s=a.summary, cmp=a._cmp||{};
    if((p.follower_count||0)<fMin || (p.follower_count||0)>fMax) return false;
    if((s.video_count||0)<vMin) return false;
    if(q && !((p.nickname||'').toLowerCase().includes(q) || (p.unique_id||'').toLowerCase().includes(q))) return false;
    if(change!=='__all__'){
      if(cmp.cmp_unavailable) return false;
      if(!cmp.has_prior && change!=='no_change') return false;
      if(change==='no_change' && cmp.has_prior) return false;
      if(change==='has_new' && !cmp.new_count) return false;
      if(change==='has_caption' && !cmp.changed_caption) return false;
      if(change==='has_tags' && !cmp.changed_tags) return false;
      if(change==='has_deleted' && !cmp.deleted_count) return false;
    }
    return true;
  });

  // 计数
  const cntEl=document.getElementById('matrixCount');
  if(cntEl) cntEl.textContent='当前显示 '+filtered.length+' / '+DATA.accounts.length+' 个账号';

  // 渲染（用原始索引保证 showDetail 正确）
  document.getElementById('matrix').innerHTML = filtered.map(a=>{
    const i = DATA.accounts.indexOf(a);
    const p=a.profile, s=a.summary, cmp=a._cmp||{};
    const av = p.avatar ? `<img class="avatar" src="${esc(p.avatar)}" alt="">` : `<div class="avatar"></div>`;
    const chips=[];
    if(cmp.cmp_unavailable){
      chips.push('<span class="chip muted">该日无数据</span>');
    } else if(cmp.has_prior){
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
      <td class="num">${fmt(s.video_count)}${p.total_count>s.video_count?'<div class="muted" style="font-size:11px">/共'+fmt(p.total_count)+'</div>':(p.gated?'<div class="muted" style="font-size:11px">未知(登录限制)</div>':(s.deleted_count?'<div class="muted" style="font-size:11px">含'+s.deleted_count+'删</div>':''))}</td>
      <td class="num">${fmt(s.total_digg)}</td>
      <td class="num">${fmt(s.total_share)}</td>
      <td>${chips.join('')}</td>
      <td class="meta">${a.stat_date||''}</td>
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
  document.getElementById('d-profile').innerHTML = `
    ${p.avatar?`<img class="avatar-lg" src="${esc(p.avatar)}" alt="">`:`<div class="avatar-lg"></div>`}
    <div class="pinfo">
      <h2>${esc(p.nickname)} ${p.verified?'<span class="verify" title="已认证">✦</span>':''}
          <a class="open-btn" href="${esc(p.douyin_url)}" target="_blank" title="在抖音打开">↗ 在抖音打开</a></h2>
      <div class="meta">抖音号: ${esc(p.unique_id||'—')} · UID: ${esc(p.uid)}</div>
      <div class="sig">${esc(p.signature||'（暂无签名）')}</div>
      ${(p.total_count&&p.total_count>s.video_count)?`<div class="cap-note">⚠️ 该账号真实作品数 ${fmt(p.total_count)}，已按需求仅采集并展示前 ${s.video_count} 条</div>`:(p.gated?`<div class="cap-note" style="background:#fdecea;color:#c0392b">⚠️ 该账号作品受登录态限制，当前展示的 ${s.video_count} 条可能不完整（真实作品数未知）</div>`:'')}
    </div>`;
  document.getElementById('d-kpis').innerHTML = [
    ['粉丝', fmt(p.follower_count)], ['关注', fmt(p.following_count)],
    ['已采集作品', fmt(s.video_count)], ['总点赞', fmt(s.total_digg)], ['总转发', fmt(s.total_share)],
  ].map(([l,v])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
  renderCmpCard(curAccount);
  renderDetail();
}

// 下钻页「逐日对比」卡片（依据当前选中的对比日期实时计算）
function renderCmpCard(a){
  const cmp=a._cmp||{};
  const el=document.getElementById('d-cmp');
  if(cmp.cmp_unavailable || !cmp.has_prior){
    el.style.display='block';
    el.innerHTML=`<h3>📊 逐日对比</h3><div class="del-list muted">当前对比日期（${esc(cmp.prior_date||'—')}）下无可用对比数据（该账号在该日可能尚未采集）。</div>`;
    return;
  }
  const chips=[['对比日期',cmp.prior_date],['新增作品',cmp.new_count],['文案变化',cmp.changed_caption],
    ['标签变化',cmp.changed_tags],['删除/隐藏',cmp.deleted_count]]
    .map(([l,v])=>`<div class="cmp-chip">${l}<b>${v}</b></div>`).join('');
  const del = cmp.deleted.length
    ? cmp.deleted.map(d=>`<div class="del-item">🗑️ ${esc(d.desc)||'(无文案)'} <span class="muted">（在 ${esc(d.date)} 仍可见，点赞 ${fmt(d.digg)}）</span></div>`).join('')
    : '<div class="muted">无</div>';
  el.style.display='block';
  el.innerHTML=`<h3>📊 逐日对比（最新 ${esc(accLatest(a))} vs ${esc(cmp.prior_date)}）</h3><div class="cmp-chips">${chips}</div><div class="del-list"><b>删除/隐藏的作品：</b>${del}</div>`;
}

function renderDetail(){
  const D=curAccount;
  const qEl=document.getElementById('dq');
  const q=qEl?qEl.value.trim().toLowerCase():'';
  const sortEl=document.getElementById('dsort');
  const sort=sortEl?sortEl.value:'create_desc';
  const dChEl=document.getElementById('dChange');
  const dChange=dChEl?dChEl.value:'__all__';
  function dtOf(v){
    const f=flagOf(v);
    if(f.is_new) return 'new';
    if(f.deleted) return 'deleted';
    if(f.caption_changed) return 'caption';
    if(f.tags_changed) return 'tags';
    return 'none';
  }
  let rows=D.videos.filter(v=>{
    if(q && !(v.desc+v.tags).toLowerCase().includes(q)) return false;
    if(dChange!=='__all__' && dtOf(v)!==dChange) return false;
    return true;
  });
  const cmp={ create_desc:(a,b)=>b.create_time-a.create_time, digg_desc:(a,b)=>b.digg-a.digg }[sort];
  if(cmp) rows.sort(cmp);

  // 用 DOM API 构建表格行，彻底避免 innerHTML 模板字面量被数据中的特殊字符破坏
  const tbody=document.getElementById('d-tbody');
  tbody.innerHTML='';
  rows.forEach((v, ri)=>{
    const f=flagOf(v);
    const tr=document.createElement('tr');
    if(f.deleted) tr.className='del-row';

    // 封面
    const td0=document.createElement('td');
    if(v.cover){ const img=document.createElement('img'); img.className='cover'; img.src=v.cover; img.loading='lazy'; img.alt='封面'; td0.appendChild(img); }
    else td0.innerHTML='<div class="cover"></div>';
    tr.appendChild(td0);

    // 作品链接 + 标签
    const td1=document.createElement('td');
    const a1=document.createElement('a'); a1.className='cap-link'; a1.href=v.url||'#'; a1.target='_blank'; a1.title='在抖音打开';
    a1.textContent=(v.desc||'(无文案)').split('\n')[0]+' ↗';
    td1.appendChild(a1);
    if(v.tags){
      const tagDiv=document.createElement('div'); tagDiv.className='tags';
      v.tags.split(',').filter(Boolean).forEach(t=>{
        const sp=document.createElement('span'); sp.className='tag'; sp.textContent='#'+t; tagDiv.appendChild(sp);
      });
      td1.appendChild(tagDiv);
    }
    tr.appendChild(td1);

    // 发布时间
    const td2=document.createElement('td'); td2.className='num muted'; td2.textContent=timeStr(v.create_time); tr.appendChild(td2);

    // 点赞/评论/转发/收藏
    ['digg','comm','share','coll'].forEach(key=>{
      const td=document.createElement('td'); td.className='num'; td.textContent=fmt(v[key]||0); tr.appendChild(td);
    });

    // 各Δ（依据当前对比日期）
    [['ddigg',f.ddigg],['dcomm',f.dcomm],['dshare',f.dshare],['dcoll',f.dcoll]].forEach(([key,val])=>{
      const td=document.createElement('td'); td.className='num';
      if(val===null||val===0) td.innerHTML='<span class="muted">—</span>';
      else{ const s=document.createElement('span'); s.className=val>0?'pos':'neg'; s.textContent=(val>0?'+':'')+val; td.appendChild(s); }
      tr.appendChild(td);
    });

    // 变化标签
    const tdChg=document.createElement('td');
    const parts=[];
    if(f.is_new){ const s=document.createElement('span'); s.className='chip ok'; s.textContent='新增'; parts.push(s); }
    if(f.caption_changed){ const s=document.createElement('span'); s.className='chip warn'; s.textContent='文案变化'; parts.push(s); }
    if(f.tags_changed){ const s=document.createElement('span'); s.className='chip warn'; s.textContent='标签变化'; parts.push(s); }
    if(f.deleted && !f.has_cmp){ const s=document.createElement('span'); s.className='chip warn'; s.textContent='删除/隐藏'; parts.push(s); }
    if(!parts.length) tdChg.innerHTML='<span class="muted">—</span>';
    else parts.forEach(s=>tdChg.appendChild(s));
    tr.appendChild(tdChg);

    // 操作：查看每日按钮（用 aweme_id 做唯一标识，避免筛选后索引错位）
    const tdOp=document.createElement('td');
    const btn=document.createElement('button'); btn.className='open-btn btn-daily';
    btn.setAttribute('data-aid', String(v.aweme_id));
    btn.textContent='查看每日';
    const hasDaily=(v.daily||[]).length>=1;
    if(!hasDaily){ btn.disabled=true; btn.style.opacity='.4'; btn.style.cursor='not-allowed'; btn.title='暂无抓取到数据'; }
    tdOp.appendChild(btn);
    tr.appendChild(tdOp);

    tbody.appendChild(tr);
  });
  const infoEl=document.getElementById('d-info');
  if(infoEl) infoEl.textContent='共 '+rows.length+' / '+D.videos.length+' 条作品';
}

// ===== Tab 切换 =====
function switchTab(t){
  document.getElementById('tabOverview').classList.toggle('active', t==='overview');
  document.getElementById('tabAll').classList.toggle('active', t==='all');
  document.getElementById('overview').style.display = t==='overview'?'block':'none';
  document.getElementById('detail').style.display='none';
  document.getElementById('backBtn').style.display='none';
  document.getElementById('allview').style.display = t==='all'?'block':'none';
  if(t==='all') renderAll();
}

// ===== 全部作品汇总渲染（DOM API，避免 innerHTML 模板字面量被数据破坏）=====
const tbodyA = document.getElementById('tbodyA');
function renderAll(){
  const accEl=document.getElementById('fAccount');
  const acc=accEl?accEl.value:'__all__';
  const likeMinEl=document.getElementById('fLikeMin');
  const likeMin=likeMinEl?Number(likeMinEl.value||0):0;
  const likeMaxEl=document.getElementById('fLikeMax');
  const likeMaxRaw=likeMaxEl?likeMaxEl.value:'';
  const likeMax=likeMaxRaw?Number(likeMaxRaw):Infinity;
  const dfEl=document.getElementById('fDateFrom');
  const df=dfEl?dfEl.value:'';
  const dtEl=document.getElementById('fDateTo');
  const dt=dtEl?dtEl.value:'';
  const qEl=document.getElementById('fSearch');
  const q=qEl?qEl.value.trim().toLowerCase():'';
  const sortEl=document.getElementById('fSort');
  const sort=sortEl?sortEl.value:'digg_desc';
  const chEl=document.getElementById('fChange');
  const change=chEl?chEl.value:'__all__';

  // 变化类型判定（基于当前选中的对比日期）
  function changeTypeOf(v){
    const f=flagOf(v);
    if(f.is_new) return 'new';
    if(f.deleted) return 'deleted';
    if(f.caption_changed) return 'caption';
    if(f.tags_changed) return 'tags';
    return 'none';
  }

  let rows = ALL.filter(v=>{
    if(acc!=='__all__' && v.uid!==acc) return false;
    if((v.digg||0) < likeMin || (v.digg||0) > likeMax) return false;
    const cd = dateStr(v.create_time);
    if(df && cd < df) return false;
    if(dt && cd > dt) return false;
    if(q && !((v.desc||'').toLowerCase().includes(q) || (v.tags||'').toLowerCase().includes(q))) return false;
    if(change!=='__all__' && changeTypeOf(v)!==change) return false;
    return true;
  });
  const cmp = {
    digg_desc:(a,b)=>b.digg-a.digg, digg_asc:(a,b)=>a.digg-b.digg,
    eng_desc:(a,b)=>engOf(b)-engOf(a),
    create_desc:(a,b)=>b.create_time-a.create_time, create_asc:(a,b)=>a.create_time-b.create_time,
    nickname:(a,b)=>(a.nickname||'').localeCompare(b.nickname||'','zh'),
  }[sort] || ((a,b)=>b.digg-a.digg);
  rows.sort(cmp);

  const countEl=document.getElementById('allCount');
  if(countEl) countEl.textContent='当前显示 '+rows.length+' / '+ALL.length+' 条作品';
  const emptyEl=document.getElementById('allEmpty');
  if(!rows.length){ tbodyA.innerHTML=''; if(emptyEl) emptyEl.style.display='block'; return; }
  if(emptyEl) emptyEl.style.display='none';

  // DOM API 构建行
  tbodyA.innerHTML='';
  rows.forEach((v, ri)=>{
    const f=flagOf(v);
    const tr=document.createElement('tr');
    if(f.deleted) tr.className='del-row';

    // 账号
    const td0=document.createElement('td');
    if(v.account_url){ const a=document.createElement('a'); a.className='acc-link'; a.href=v.account_url; a.target='_blank'; a.textContent=v.nickname+' ↗'; td0.appendChild(a); }
    else{ const s=document.createElement('span'); s.className='acc'; s.textContent=v.nickname; td0.appendChild(s); }
    tr.appendChild(td0);

    // 封面+作品
    const td1=document.createElement('td');
    if(v.cover){ const img=document.createElement('img'); img.className='cover'; img.src=v.cover; img.loading='lazy'; td1.appendChild(img); }
    else td1.innerHTML='<div class="cover"></div>';
    const a1=document.createElement('a'); a1.className='cap-link'; a1.href=v.url||'#'; a1.target='_blank';
    a1.textContent=(v.desc||'(无文案)').split('\n')[0]+' ↗';
    td1.appendChild(a1);
    if(v.tags){
      const div=document.createElement('div'); div.className='tags';
      v.tags.split(',').filter(Boolean).forEach(t=>{ const sp=document.createElement('span'); sp.className='tag'; sp.textContent='#'+t; div.appendChild(sp); });
      td1.appendChild(div);
    }
    tr.appendChild(td1);

    // 发布时间
    const td2=document.createElement('td'); td2.className='num muted'; td2.textContent=timeStr(v.create_time); tr.appendChild(td2);

    // 点赞/评论/转发/收藏
    ['digg','comm','share','coll'].forEach(k=>{ const td=document.createElement('td'); td.className='num'; td.textContent=fmt(v[k]||0); tr.appendChild(td); });

    // 总互动
    const tdEng=document.createElement('td'); tdEng.className='num'; tdEng.textContent=fmt(engOf(v)); tr.appendChild(tdEng);

    // 变化徽章
    const tdChg=document.createElement('td');
    const ct=changeTypeOf(v);
    if(ct==='new'){ const s=document.createElement('span'); s.className='b-new'; s.textContent='新增'; tdChg.appendChild(s); }
    else if(ct==='deleted'){ const s=document.createElement('span'); s.style.cssText='background:#fce4ec;color:#c2185b;border-radius:6px;padding:1px 6px;font-size:11px;font-weight:700'; s.textContent='删除/隐藏'; tdChg.appendChild(s); }
    else if(ct==='caption'){ const s=document.createElement('span'); s.className='b-cap'; s.textContent='文案变'; tdChg.appendChild(s); }
    else if(ct==='tags'){ const s=document.createElement('span'); s.className='b-tag'; s.textContent='标签变'; tdChg.appendChild(s); }
    else tdChg.innerHTML='<span class="muted">—</span>';
    tr.appendChild(tdChg);

    // 天数
    const tdN=document.createElement('td'); const spN=document.createElement('span'); spN.className='daytag'; spN.textContent=(v.n_days||1)+' 天'; tdN.appendChild(spN); tr.appendChild(tdN);

    // 查看每日按钮（用 aweme_id 做唯一标识）
    const tdOp=document.createElement('td');
    const btn=document.createElement('button'); btn.className='open-btn btn-daily-all';
    btn.setAttribute('data-aid', String(v.aweme_id));
    btn.textContent='查看每日';
    const hasDaily=(v.daily||[]).length>=1;
    if(!hasDaily){ btn.disabled=true; btn.style.opacity='.4'; btn.style.cursor='not-allowed'; btn.title='暂无抓取到数据'; }
    tdOp.appendChild(btn);
    tr.appendChild(tdOp);

    tbodyA.appendChild(tr);
  });
}

// ===== Excel 导出 =====
function exportExcel(){
  // 获取当前筛选条件下的数据
  const accEl=document.getElementById('fAccount');
  const acc=accEl?accEl.value:'__all__';
  const likeMinEl=document.getElementById('fLikeMin');
  const likeMin=likeMinEl?Number(likeMinEl.value||0):0;
  const likeMaxEl=document.getElementById('fLikeMax');
  const likeMaxRaw=likeMaxEl?likeMaxEl.value:'';
  const likeMax=likeMaxRaw?Number(likeMaxRaw):Infinity;
  const dfEl=document.getElementById('fDateFrom');
  const df=dfEl?dfEl.value:'';
  const dtEl=document.getElementById('fDateTo');
  const dt=dtEl?dtEl.value:'';

  const rows=ALL.filter(v=>{
    if(acc!=='__all__'&&v.uid!==acc)return false;
    if((v.digg||0)<likeMin||(v.digg||0)>likeMax)return false;
    const cd=dateStr(v.create_time);
    if(df&&cd<df)return false;
    if(dt&&cd>dt)return false;
    return true;
  });

  // 构建 CSV（Excel 可直接打开）
  let csv='\uFEFF'; // BOM for UTF-8 Excel
  csv+='账号,作品ID,文案,标签,发布时间,点赞,评论,转发,收藏,总互动,变化,抓取天数,抖音链接\n';
  const chMap={new:'新增',caption:'文案变化',tags:'标签变化',deleted:'删除/隐藏',none:'—'};
  rows.forEach(v=>{
    const desc=(v.desc||'').replace(/"/g,'""').replace(/\n/g,' ');
    const tags=(v.tags||'').replace(/"/g,'""');
    const url=v.url||'';
    let ct='none'; if(v.is_new) ct='new'; else if(v.deleted) ct='deleted'; else if(v.caption_changed) ct='caption'; else if(v.tags_changed) ct='tags';
    csv+='"'+(v.nickname||'')+'","'+(v.aweme_id||'')+'","'+desc+'","'+tags+'",'+dateStr(v.create_time)+','+(v.digg||0)+','+(v.comm||0)+','+(v.share||0)+','+(v.coll||0)+','+(engOf(v))+',"'+(chMap[ct]||'—')+'",'+(v.n_days||1)+',"'+url+'"\n';
  });

  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  const ts=new Date().toISOString().slice(0,10);
  a.download='抖音监控_'+ts+'.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

// 账号下拉
const fAccount = document.getElementById('fAccount');
fAccount.innerHTML = '<option value="__all__">全部账号</option>' +
  DATA.accounts.map(a=>`<option value="${a.profile.uid}">${esc(a.profile.nickname)}（${fmt(a.profile.follower_count)}粉）</option>`).join('');

// 表头点击排序
document.querySelectorAll('th.sortable').forEach(th=>{
  th.onclick=()=>{
    const key=th.getAttribute('data-sort');
    const sel=document.getElementById('fSort');
    if(key==='eng') sel.value=(sel.value==='eng_desc')?'digg_desc':'eng_desc';
    else if(key==='digg'||key==='comm'||key==='share'||key==='coll'){
      if(key==='digg') sel.value=(sel.value==='digg_desc')?'digg_asc':'digg_desc';
      else sel.value='digg_desc';
    }
    renderAll();
  };
});

// 过滤事件
['fAccount','fLikeMin','fLikeMax','fDateFrom','fDateTo','fSearch','fSort','fChange'].forEach(id=>{
  document.getElementById(id).addEventListener('input', renderAll);
  document.getElementById(id).addEventListener('change', renderAll);
});
document.getElementById('fReset').onclick=()=>{
  fAccount.value='__all__';
  document.getElementById('fLikeMin').value=0;
  document.getElementById('fLikeMax').value='';
  document.getElementById('fDateFrom').value='';
  document.getElementById('fDateTo').value='';
  document.getElementById('fSearch').value='';
  document.getElementById('fSort').value='digg_desc';
  document.getElementById('fChange').value='__all__';
  renderAll();
};
const expBtn=document.getElementById('fExport');
if(expBtn) expBtn.onclick=exportExcel;

// ===== 可选对比日期：初始化下拉 + 切换重算 =====
const cmpSelect = document.getElementById('cmpSelect');
const cmpBase = document.getElementById('cmpBase');
const cmpNote = document.getElementById('cmpNote');
cmpBase.textContent = LATEST_DATE || '—';
(function initCmp(){
  const opts = STAT_DATES.filter(d=>d!==LATEST_DATE).slice().reverse(); // 最新可选日置顶
  let html = '<option value="">（不对比）</option>';
  html += opts.map(d=>`<option value="${d}">${d}</option>`).join('');
  cmpSelect.innerHTML = html;
  cmpSelect.value = state.cmpDate || '';
})();
function updateCmpNote(){
  if(!state.cmpDate){
    cmpNote.textContent='未选择对比日期：仅展示最新快照';
    cmpNote.className='cmp-note';
  } else {
    const nAcc = DATA.accounts.filter(a=>(a._cmp||{}).has_prior).length;
    cmpNote.textContent=`对比 ${LATEST_DATE} vs ${state.cmpDate} · ${nAcc}/${DATA.accounts.length} 个账号有可比数据`;
    cmpNote.className='cmp-note';
  }
}
function rerenderAfterCmp(){
  applyComparison();
  if(curAccount && document.getElementById('detail').style.display!=='none'){
    renderCmpCard(curAccount);
    renderDetail();
  }
  renderMatrix();
  if(document.getElementById('allview').style.display!=='none') renderAll();
  updateCmpNote();
}
cmpSelect.addEventListener('change', ()=>{ state.cmpDate = cmpSelect.value || null; rerenderAfterCmp(); });

// 全局 KPI
const totAcc=DATA.accounts.length;
const totVid=DATA.accounts.reduce((s,a)=>s+a.summary.video_count,0);
const totDigg=DATA.accounts.reduce((s,a)=>s+a.summary.total_digg,0);
const totShare=DATA.accounts.reduce((s,a)=>s+a.summary.total_share,0);
const multiDay=DATA.accounts.reduce((s,a)=>s+a.videos.filter(v=>(v.daily||[]).length>=2).length,0);
document.getElementById('gkpis').innerHTML=[
  ['监控账号', totAcc],['总作品数', totVid],['总点赞', fmt(totDigg)],
  ['总转发', fmt(totShare)],['有多日数据作品', multiDay + ' / ' + totVid],
].map(([l,v])=>`<div class="gkpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

const totDel = DATA.accounts.reduce((s,a)=>s+(a.summary.deleted_count||0),0);
document.getElementById('footer').innerHTML=
  `数据来源：本地数据库（TikHub 抓取快照）· 统计日 ${DATA.stat_dates.join('、')} · 共 ${totAcc} 个账号<br>`+
  `已移除无法抓取的「播放量 / 互动率」；点「查看每日」可下钻作品逐日数据；账号名后 <span style="color:#ff6a00">↗</span> 直达抖音主页。`+
  (DATA.stat_dates.length<2 ? '<br>当前仅 1 个统计日，逐日曲线将在多次抓取后变丰富。' : '')+
  (totDel ? `<br>含已删除/隐藏视频 <b style="color:#c0392b">${totDel}</b> 条（数据已留存，列表中置灰并标注「已删除」，仍可查看每日）` : '');

// 登录态限制横幅
if (DATA.accounts.some(a => a.profile && a.profile.gated)) {
  document.getElementById('gateBanner').style.display = 'block';
}

// 事件委托：查看每日按钮（用 data-aid 存 aweme_id，避免内联 JSON 破坏 HTML、也避免筛选后索引错位）
document.addEventListener('click', function(e){
  // 下钻明细中的按钮
  const btn = e.target.closest('.btn-daily');
  if(btn && !btn.disabled && curAccount){
    const aid = btn.getAttribute('data-aid');
    const v = curAccount.videos.find(x => String(x.aweme_id) === aid);
    if(v) openDailyModal(v);
    return;
  }
  // 汇总面板中的按钮
  const btnA = e.target.closest('.btn-daily-all');
  if(btnA && !btnA.disabled){
    const aid = btnA.getAttribute('data-aid');
    const v = ALL.find(x => String(x.aweme_id) === aid);
    if(v) openDailyModal(v);
    return;
  }
});

// 总览矩阵筛选事件
['mFollowerMin','mFollowerMax','mVideoMin','mChange','mSearch'].forEach(id=>{
  const el=document.getElementById(id);
  if(el){ el.addEventListener('input', showOverview); el.addEventListener('change', showOverview); }
});
const mResetBtn=document.getElementById('mReset');
if(mResetBtn) mResetBtn.onclick=()=>{
  document.getElementById('mFollowerMin').value=0;
  document.getElementById('mFollowerMax').value='';
  document.getElementById('mVideoMin').value=0;
  document.getElementById('mChange').value='__all__';
  document.getElementById('mSearch').value='';
  showOverview();
};

applyComparison();
showOverview();
updateCmpNote();
</script>
</body>
</html>
"""


def main():
    db = MonitorDB(DB_PATH)
    stat_date = datetime.now(CST_).strftime("%Y-%m-%d")
    accounts = []
    for uid in MONITOR_UIDS:
        try:
            d = load_account_from_db(db, uid, stat_date)
        except Exception as e:
            print(f"⚠️ {uid} 加载失败: {e}")
            continue
        if not d:
            print(f"⚠️ {uid} 数据库无数据，跳过")
            continue
        # 注入汇总表所需字段
        p = d["profile"]
        acc_url = "https://www.douyin.com/user/" + (p.get("sec_uid") or "")
        actual = db.get_distinct_dates(uid)
        d["stat_date"] = max(actual) if actual else stat_date
        for v in d["videos"]:
            v["nickname"] = p.get("nickname", uid)
            v["account_url"] = acc_url
            v["n_days"] = len(v.get("daily") or [])

        # 构建逐日快照（snaps）：每个统计日该账号可见作品的完整记录，
        # 支撑「可选对比日期」——用户可在前端选择任一历史日期与最新数据做对比。
        dates_sorted = sorted(db.get_distinct_dates(uid))  # 升序
        snaps = {}
        for d0 in dates_sorted:
            rows = db.get_records_by_date(uid, d0)
            snaps[d0] = [{
                "aweme_id": str(r.get("aweme_id")),
                "desc": (r.get("desc") or ""),
                "tags": (r.get("tags") or ""),
                "create_time": r.get("create_time") or 0,
                "cover": (r.get("cover") or ""),
                "digg": int(r.get("digg_count") or 0),
                "comm": int(r.get("comment_count") or 0),
                "share": int(r.get("share_count") or 0),
                "coll": int(r.get("collect_count") or 0),
                "url": "https://www.douyin.com/video/" + str(r.get("aweme_id")),
            } for r in rows]
        d["dates"] = dates_sorted
        d["snaps"] = snaps

        accounts.append(d)
        print(f"✅ {uid} 昵称={p.get('nickname')} 作品={d['summary']['video_count']}/真实{p.get('total_count')}")

    if not accounts:
        print("❌ 无可用账号数据")
        sys.exit(1)

    all_dates = sorted({dd["date"] for a in accounts for v in a["videos"] for dd in (v.get("daily") or [])})
    multi_day = sum(1 for a in accounts for v in a["videos"] if len(v.get("daily") or []) >= 2)
    data = {
        "stat_dates": all_dates,
        "accounts": accounts,
    }
    html = TEMPLATE.replace("{DATA_JSON}", json.dumps(data, ensure_ascii=False))

    deploy_dir = os.path.join(SCRIPT_DIR, "deploy")
    os.makedirs(deploy_dir, exist_ok=True)
    out = os.path.join(deploy_dir, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📄 合并看板已生成: {out}")
    print(f"   账号={len(accounts)} 作品={sum(len(a['videos']) for a in accounts)} "
          f"统计日={all_dates} 多日数据作品={multi_day}")


if __name__ == "__main__":
    main()
