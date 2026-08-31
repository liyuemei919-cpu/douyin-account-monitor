"""
单账号真实数据看板生成器（先看板，再批量）

用法:
  python build_single_account.py [UID] [NAME]

功能:
  1. 从 .env 读取 TikHub API Key
  2. 抓取指定账号的【真实】资料 + 全部作品（分页）
  3. 写入 SQLite（snapshots / video_daily，含封面图 URL）
  4. 生成单账号 HTML 看板（真实封面 + 可点击跳转抖音视频）

数据来源: TikHub (api.tikhub.dev)
"""

import os
import sys
import json
import time
import re
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from tikhub_client import (
    TikHubClient, extract_profile, extract_videos, format_number, format_timestamp, CST
)
from monitor import MonitorDB

CST_ = timezone(timedelta(hours=8))


def load_api_key() -> str:
    """从 .env 文件读取 API Key（不写日志、不回显）"""
    search_dirs = [SCRIPT_DIR, os.path.dirname(SCRIPT_DIR)]
    for d in search_dirs:
        for fn in ("douyin-monitor.env.txt", "douyin-monitor.env", ".env"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    line = line.strip()
                    if line.startswith("TIKHUB_API_KEY"):
                        return line.split("=", 1)[1].strip()
    return ""


# 仅保留鉴权必需的核心 Cookie；剔除浏览器误带/超长的指纹与追踪类 Cookie
# （如 bit_env / sdk_source_info / bd_ticket_guard_* / fpk* / UIFID 等），
# 否则整串作为 query 参数发送时会触发抖音 WAF 返回 403。
_COOKIE_WHITELIST = [
    "sessionid", "sessionid_ss", "sid_tt", "sid_guard", "sid_ucp_v1", "ssid_ucp_v1",
    "ttwid", "odin_tt", "uid_tt", "uid_tt_ss", "d_ticket", "passport_csrf_token",
    "passport_csrf_token_default", "passport_assist_user", "n_mh", "s_v_web_id",
    "passport_auth_mix_state", "login_time", "has_biz_token", "is_staff_user",
    "my_rd", "bd_ticket_guard_client_web_domain",
]


def _clean_cookie(raw: str) -> str:
    """从整串 Cookie 中抽取白名单内的键值对，避免超长指纹 Cookie 触发 403。"""
    if not raw:
        return ""
    parts = re.split(r";\s*", raw.strip().strip(";"))
    kept = []
    for part in parts:
        if "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if name in _COOKIE_WHITELIST:
            kept.append(part.strip())
    return "; ".join(kept)


def load_cookie() -> str:
    """从 .env 文件读取抖音网页版登录 Cookie（解锁被登录态挡住的作品）。
    文件格式：DOUYIN_COOKIE=sessionid=...; ttwid=...; ...
    读取后会自动剔除指纹/追踪类冗长 Cookie，仅保留鉴权所需字段。
    为空则返回 ''（此时私密/新号可能返回 0 作品）。"""
    search_dirs = [SCRIPT_DIR, os.path.dirname(SCRIPT_DIR)]
    for d in search_dirs:
        for fn in ("douyin-monitor.env.txt", "douyin-monitor.env", ".env"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                for line in open(p, encoding="utf-8"):
                    line = line.strip()
                    if line.startswith("DOUYIN_COOKIE"):
                        return _clean_cookie(line.split("=", 1)[1].strip())
    return ""


# 采集上限：None 表示不限制，自动分页拉取该账号的全部作品（不再只取前 10）。
COLLECT_CAP = None


def fetch_account(client: TikHubClient, uid: str, name_hint: str, cookie: str = ""):
    """抓取单个账号的真实资料 + 全部作品（自动分页，不再限制前 N 条）

    返回: (profile, videos, total_count, not_login)
      - videos:       该账号的全部作品（按接口返回顺序 = 发布时间倒序 / 主页顺序）
      - total_count:  账号真实作品总数（优先 profile.aweme_count；
                      登录态挡住且 aweme_count=0 时为 None，此时用已采集条数兜底）
    """
    print(f"📡 抓取资料: uid={uid}")
    raw_p = client.get_user_profile(uid, cookie=cookie)
    profile = extract_profile(raw_p)
    if not profile:
        raise RuntimeError(f"资料获取失败: {raw_p.get('message', raw_p)[:200]}")
    sec_uid = profile["sec_uid"]
    print(f"  👤 昵称: {profile['nickname']} | 粉丝: {format_number(profile['follower_count'])} | 作品(接口): {profile['aweme_count']}")

    # 自动分页拉取全部作品（抖音作品端点返回 has_more / max_cursor）
    videos = []
    seen = set()
    not_login = False
    cursor = 0
    page = 0
    has_more = True
    while has_more:
        page += 1
        raw_v = client.get_user_videos(sec_uid, max_count=50, cursor=cursor, cookie=cookie)
        inner = (raw_v.get("data", {}) or {})
        al = inner.get("aweme_list", []) or []
        not_login = not_login or bool(inner.get("not_login_module"))
        # 翻页抖动：has_more=True 但本页空 → 用同一 cursor 重试一次
        if not al and inner.get("has_more"):
            raw_v = client.get_user_videos(sec_uid, max_count=50, cursor=cursor, cookie=cookie)
            inner = (raw_v.get("data", {}) or {})
            al = inner.get("aweme_list", []) or []
            not_login = not_login or bool(inner.get("not_login_module"))
        for item in al:
            if not isinstance(item, dict):
                continue
            vid = (item.get("aweme_id") or "").strip()
            if not vid or vid in seen:
                continue
            seen.add(vid)
            v = extract_videos({"data": {"aweme_list": [item]}})
            if v:
                videos.append(v[0])
        next_cursor = inner.get("max_cursor") or 0
        has_more = bool(inner.get("has_more"))
        # 无数据且已无更多 → 结束；cursor 未推进且本页空 → 防死循环
        if not al and not has_more:
            break
        if not al and next_cursor == cursor:
            break
        cursor = next_cursor
        if page >= 50:  # 安全上限：单账号最多 50 页 × 50 = 2500 条
            print("  ⚠️ 已达分页安全上限，停止翻页")
            break
        time.sleep(0.4)

    # 真实总数：优先 aweme_count（>0），否则用已采集条数兜底；
    # 若被登录态挡住（aweme_count=0 且无作品），真实数未知，记为 None
    if profile.get("aweme_count"):
        total_count = profile["aweme_count"]
    elif not_login:
        total_count = None  # 受登录态限制，真实作品数未知
    else:
        total_count = len(videos)
    if not_login:
        print("  ⚠️ 接口返回 not_login_module（作品被登录态挡住），当前 cookie 可能无效或未提供")
    print(f"  📹 共采集 {len(videos)} 条作品"
          + (f" · 真实总数={total_count}" if total_count is not None else " · 真实总数未知(登录态限制)"))

    return profile, videos, total_count, not_login


def assemble_data(profile: dict, videos: list, stat_date: str, captured_at: str,
                  comparison: dict = None, total_count: int = None, gated: bool = False) -> dict:
    """组装看板所需的数据对象（单账号）。供单账号/多账号看板复用。"""
    # 汇总指标
    total_play = sum(v.get("play_count", 0) for v in videos)
    total_digg = sum(v.get("digg_count", 0) for v in videos)
    total_comm = sum(v.get("comment_count", 0) for v in videos)
    total_share = sum(v.get("share_count", 0) for v in videos)
    total_coll = sum(v.get("collect_count", 0) for v in videos)
    # 抖音公开接口通常不返回播放量(play_count 恒为 0)，需优雅降级
    play_available = any(v.get("play_count", 0) for v in videos)
    avg_rate = round((total_digg + total_comm + total_share + total_coll) / total_play * 100, 2) \
        if (total_play and play_available) else None

    sec_uid = str(profile.get("sec_uid") or "")
    # 抖音主页跳转链接（点击账号直接跳转）
    douyin_url = f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "https://www.douyin.com"
    # 真实作品总数：采集受限（登录态）时记为 None，展示「未知」
    real_total = total_count if total_count is not None else len(videos)
    # 登录态限制：not_login_module 是对象/None，转为布尔 + 提示文案
    is_gated = bool(gated)
    login_tip = ""
    if is_gated and isinstance(gated, dict):
        extra = (gated.get("extra") or "")
        try:
            import json as _json
            login_tip = (_json.loads(extra).get("guide_login_tip_text_biserial") or "")
        except Exception:
            login_tip = ""

    return {
        "profile": {
            "nickname": profile.get("nickname", ""),
            "avatar": profile.get("avatar", ""),
            "uid": str(profile.get("uid") or ""),
            "sec_uid": sec_uid,
            "unique_id": profile.get("unique_id", ""),
            "signature": profile.get("signature", ""),
            "verified": bool(profile.get("verification_type", 0)),
            "follower_count": profile.get("follower_count", 0),
            "following_count": profile.get("following_count", 0),
            "total_favorited": profile.get("total_favorited", 0),
            "aweme_count": profile.get("aweme_count", 0),
            "total_count": real_total,
            "gated": is_gated,
            "login_tip": login_tip,
            "douyin_url": douyin_url,
        },
        "summary": {
            "total_play": total_play, "total_digg": total_digg,
            "total_comm": total_comm, "total_share": total_share,
            "total_coll": total_coll, "avg_rate": avg_rate,
            "play_available": play_available, "video_count": len(videos),
        },
        "videos": [
            {
                "aweme_id": v.get("aweme_id", ""),
                "url": "https://www.douyin.com/video/" + str(v.get("aweme_id", "")),
                "desc": v.get("desc", ""),
                "cover": v.get("cover", ""),
                "tags": v.get("tags", ""),
                "create_time": v.get("create_time", 0),
                "play": v.get("play_count", 0),
                "digg": v.get("digg_count", 0),
                "comm": v.get("comment_count", 0),
                "share": v.get("share_count", 0),
                "coll": v.get("collect_count", 0),
                "ddigg": v.get("ddigg"), "dcomm": v.get("dcomm"),
                "dshare": v.get("dshare"), "dcoll": v.get("dcoll"),
                "is_new": v.get("is_new", False),
                "caption_changed": v.get("caption_changed", False),
                "tags_changed": v.get("tags_changed", False),
                "daily": v.get("daily", []),       # 逐日历史（load_account_from_db 填充）
            }
            for v in videos
        ],
        "comparison": comparison or {},
        "stat_date": stat_date,
        "captured_at": captured_at,
    }


def build_html(profile: dict, videos: list, stat_date: str, captured_at: str,
               comparison: dict = None) -> str:
    data = assemble_data(profile, videos, stat_date, captured_at, comparison)
    html = HTML_TEMPLATE.replace("{DATA_JSON}", json.dumps(data, ensure_ascii=False))
    return html


def compute_comparison(current_videos: list, prior_records: list, prior_date: str,
                       capped: bool = False) -> dict:
    """对比前一天快照，计算逐日增量 / 文案·标签变化 / 删除隐藏。

    capped=True 表示本次仅采集了前 N 条 / 受登录态限制，无法可靠判断
    「作品被删除/隐藏」（可能只是被新作品挤出前 N）。此时 deleted 相关
    字段置 0 并标记 deletion_limited，避免误报。
    """
    prior_map = {r["aweme_id"]: r for r in prior_records}
    prior_ids = set(prior_map.keys())
    cur_ids = {v.get("aweme_id") for v in current_videos}
    for v in current_videos:
        aid = v.get("aweme_id")
        p = prior_map.get(aid)
        if p is None:
            v["is_new"] = True
            v["ddigg"] = v["dcomm"] = v["dshare"] = v["dcoll"] = None
            v["caption_changed"] = False
            v["tags_changed"] = False
            continue
        v["is_new"] = False
        v["ddigg"] = (v.get("digg_count", 0) or 0) - (p.get("digg_count") or 0)
        v["dcomm"] = (v.get("comment_count", 0) or 0) - (p.get("comment_count") or 0)
        v["dshare"] = (v.get("share_count", 0) or 0) - (p.get("share_count") or 0)
        v["dcoll"] = (v.get("collect_count", 0) or 0) - (p.get("collect_count") or 0)
        v["caption_changed"] = (v.get("desc", "") or "") != (p.get("desc") or "")
        v["tags_changed"] = (v.get("tags", "") or "") != (p.get("tags") or "")
    if capped:
        return {
            "has_prior": bool(prior_date),
            "prior_date": prior_date or "",
            "new_count": sum(1 for v in current_videos if v.get("is_new")),
            "changed_caption": sum(1 for v in current_videos if v.get("caption_changed")),
            "changed_tags": sum(1 for v in current_videos if v.get("tags_changed")),
            "deleted_count": 0,
            "deleted": [],
            "deletion_limited": True,
        }
    deleted = [prior_map[a] for a in prior_ids if a not in cur_ids]
    return {
        "has_prior": bool(prior_date),
        "prior_date": prior_date or "",
        "new_count": sum(1 for v in current_videos if v.get("is_new")),
        "changed_caption": sum(1 for v in current_videos if v.get("caption_changed")),
        "changed_tags": sum(1 for v in current_videos if v.get("tags_changed")),
        "deleted_count": len(deleted),
        "deleted": [
            {"aweme_id": d["aweme_id"], "desc": (d.get("desc") or "")[:60],
             "digg": d.get("digg_count") or 0}
            for d in deleted
        ],
        "deletion_limited": False,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>抖音账号看板 - 真实数据</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2329; padding: 24px; }
  .wrap { max-width: 1100px; margin: 0 auto; }
  .badge-real { display:inline-block; background:#e8f5e9; color:#1b8a3a; font-size:12px;
                padding:2px 8px; border-radius:10px; margin-left:8px; font-weight:600;}
  .card { background:#fff; border-radius:14px; box-shadow:0 2px 10px rgba(0,0,0,.06);
          padding:22px; margin-bottom:20px; }
  /* profile header */
  .profile { display:flex; gap:20px; align-items:center; flex-wrap:wrap; }
  .avatar { width:84px; height:84px; border-radius:50%; object-fit:cover; background:#e9edf3; flex-shrink:0; }
  .pinfo h1 { font-size:24px; display:flex; align-items:center; }
  .verify { color:#ffb300; margin-left:6px; font-size:18px; }
  .meta { color:#8a9099; font-size:13px; margin-top:4px; }
  .sig { color:#5a6068; font-size:14px; margin-top:8px; max-width:620px; }
  .kpis { display:grid; grid-template-columns:repeat(7,1fr); gap:12px; margin-top:18px; }
  .kpi { background:#f7f9fc; border-radius:10px; padding:12px; text-align:center; }
  .kpi .v { font-size:20px; font-weight:700; color:#185fa5; }
  .kpi .l { font-size:12px; color:#8a9099; margin-top:3px; }
  /* filter bar */
  .fbar { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px; }
  .fbar input, .fbar select { padding:8px 10px; border:1px solid #d9dee5; border-radius:8px; font-size:13px; }
  .fbar input[type=text] { flex:1; min-width:200px; }
  .fbar .info { font-size:13px; color:#8a9099; margin-left:auto; }
  /* table */
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:10px 8px; text-align:left; border-bottom:1px solid #eef1f5; vertical-align:middle; }
  th { color:#8a9099; font-weight:600; background:#fafbfd; position:sticky; top:0; }
  tbody tr:hover { background:#f7faff; }
  .cover { width:72px; height:96px; object-fit:cover; border-radius:8px; background:#e9edf3; flex-shrink:0; }
  .cap-link { color:#185fa5; text-decoration:none; font-weight:600; }
  .cap-link:hover { text-decoration:underline; }
  .cap-text { display:block; max-width:360px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .tags { margin-top:5px; }
  .tag { display:inline-block; background:#eef3fb; color:#3a6ea5; font-size:11px;
         padding:1px 7px; border-radius:9px; margin-right:4px; }
  .num { font-variant-numeric:tabular-nums; }
  .rate-bar { height:5px; background:#e7edf5; border-radius:3px; margin-top:4px; width:80px; overflow:hidden; }
  .rate-bar > i { display:block; height:100%; background:#34a853; }
  .muted { color:#8a9099; }
  footer { text-align:center; color:#9aa0a8; font-size:12px; margin-top:10px; }
  /* comparison */
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
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="profile" id="profile"></div>
    <div class="kpis" id="kpis"></div>
  </div>

  <div class="card cmp-card" id="cmp" style="display:none"></div>

  <div class="card">
    <div class="fbar">
      <input type="text" id="q" placeholder="🔍 按文案/标签搜索作品…" oninput="render()">
      <select id="sort" onchange="render()">
        <option value="create_desc">按发布时间（新→旧）</option>
        <option value="play_desc">按播放量（高→低）</option>
        <option value="digg_desc">按点赞量（高→低）</option>
        <option value="rate_desc">按互动率（高→低）</option>
      </select>
      <span class="info" id="info"></span>
    </div>
    <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>封面</th><th>作品（点击↗跳转抖音）</th><th>发布时间</th>
        <th>播放</th><th>点赞</th><th>评论</th><th>转发</th><th>收藏</th><th>互动率</th>
        <th>点赞Δ</th><th>评论Δ</th><th>转发Δ</th><th>收藏Δ</th><th>变化</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
    </div>
  </div>

  <footer id="footer"></footer>
</div>

<script>
const DATA = {DATA_JSON};

function esc(s){ s = (s==null)?'':String(s); return s.replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmt(n){ n=Number(n)||0;
  if(n>=1e8) return (n/1e8).toFixed(1)+'亿';
  if(n>=1e4) return (n/1e4).toFixed(1)+'万';
  return String(n); }

function rateOf(v){ const t=v.digg+v.comm+v.share+v.coll; return (v.play>0)? (t/v.play*100):null; }

function delta(n){ if(n==null) return '<span class="muted">—</span>';
  if(n===0) return '0';
  const cls=n>0?'up':'down'; const s=n>0?'+':'';
  return '<span class="delta '+cls+'">'+s+fmt(n)+'</span>'; }
function changeBadges(v){ const c=[];
  if(v.is_new) c.push('<span class="b-new">新</span>');
  if(v.caption_changed) c.push('<span class="b-cap">文变</span>');
  if(v.tags_changed) c.push('<span class="b-tag">签变</span>');
  return c.length?c.join(' '):'<span class="muted">—</span>'; }

function render(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  const sort = document.getElementById('sort').value;
  let rows = DATA.videos.filter(v => !q || (v.desc+v.tags).toLowerCase().includes(q));
  const cmp = {
    create_desc:(a,b)=>b.create_time-a.create_time,
    play_desc:(a,b)=>b.play-a.play,
    digg_desc:(a,b)=>b.digg-a.digg,
    rate_desc:(a,b)=>rateOf(b)-rateOf(a),
  }[sort];
  rows.sort(cmp);
  const tb = document.getElementById('tbody');
  tb.innerHTML = rows.map(v=>{
    const r = rateOf(v);
    const tags = v.tags.split(',').filter(Boolean)
      .map(t=>`<span class="tag">#${esc(t)}</span>`).join('');
    const cover = v.cover
      ? `<img class="cover" src="${esc(v.cover)}" loading="lazy" alt="封面">`
      : `<div class="cover"></div>`;
    return `<tr>
      <td>${cover}</td>
      <td><a class="cap-link" href="${esc(v.url)}" target="_blank" title="在抖音打开">${esc(v.desc.split('\n')[0]||'(无文案)')} <span style="color:#ff6a00">↗</span></a>
          <div class="tags">${tags}</div></td>
      <td class="num muted">${fmtTime(v.create_time)}</td>
      <td class="num">${DATA.summary.play_available ? fmt(v.play) : '—'}</td>
      <td class="num">${fmt(v.digg)}</td>
      <td class="num">${fmt(v.comm)}</td>
      <td class="num">${fmt(v.share)}</td>
      <td class="num">${fmt(v.coll)}</td>
      <td class="num">${r==null?'<span class="muted">—</span>':r.toFixed(1)+'%<div class="rate-bar"><i style="width:'+Math.min(100,r*4)+'%"></i></div>'}</td>
      <td class="num">${delta(v.ddigg)}</td>
      <td class="num">${delta(v.dcomm)}</td>
      <td class="num">${delta(v.dshare)}</td>
      <td class="num">${delta(v.dcoll)}</td>
      <td>${changeBadges(v)}</td>
    </tr>`;
  }).join('');
  document.getElementById('info').textContent = `共 ${rows.length} / ${DATA.videos.length} 条作品`;
}
function fmtTime(ts){ if(!ts) return '-';
  const d=new Date(ts*1000); const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }

// profile
const p = DATA.profile;
document.getElementById('profile').innerHTML = `
  ${p.avatar?`<img class="avatar" src="${esc(p.avatar)}" alt="头像">`:`<div class="avatar"></div>`}
  <div class="pinfo">
    <h1>${esc(p.nickname)} ${p.verified?'<span class="verify" title="已认证">✦</span>':''}<span class="badge-real">真实数据</span></h1>
    <div class="meta">抖音号: ${esc(p.unique_id||'—')} · UID: ${esc(p.uid)}</div>
    <div class="sig">${esc(p.signature||'（暂无签名）')}</div>
  </div>`;
const s = DATA.summary;
const playTxt = s.play_available ? fmt(s.total_play) : '—';
const rateTxt = (s.play_available && s.avg_rate!=null) ? s.avg_rate+'%' : '—';
document.getElementById('kpis').innerHTML = [
  ['粉丝', fmt(p.follower_count)], ['关注', fmt(p.following_count)],
  ['已采集作品', fmt(s.video_count)], ['总播放', playTxt],
  ['总点赞', fmt(s.total_digg)], ['总转发', fmt(s.total_share)],
  ['平均互动率', rateTxt],
].map(([l,v])=>`<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

document.getElementById('footer').innerHTML =
  `数据来源：TikHub API · 采集时间 ${DATA.captured_at} · 统计日 ${DATA.stat_date}<br>`
  + (DATA.summary.play_available ? `` : `注：抖音公开接口不返回播放量，故「总播放 / 平均互动率」显示为「—」；点赞·评论·转发·收藏为真实数据。<br>`)
  + `首次采集已建立逐日监控基线，次日再次运行即可查看「逐日增量 / 文案·标签变化 / 删除隐藏」对比。`;

const cmp = DATA.comparison;
if(cmp && cmp.has_prior){
  const chips = [
    ['对比日期', cmp.prior_date], ['新增作品', cmp.new_count],
    ['文案变化', cmp.changed_caption], ['标签变化', cmp.changed_tags],
    ['删除/隐藏', cmp.deleted_count],
  ].map(([l,v])=>`<div class="cmp-chip">${l}<b>${v}</b></div>`).join('');
  const del = cmp.deleted.length
    ? cmp.deleted.map(d=>`<div class="del-item">🗑️ ${esc(d.desc)||'(无文案)'} <span class="muted">（最后出现 ${cmp.prior_date}，点赞 ${fmt(d.digg)}）</span></div>`).join('')
    : '<div class="muted">无</div>';
  document.getElementById('cmp').style.display='block';
  document.getElementById('cmp').innerHTML =
    `<h3>📊 逐日对比（vs ${cmp.prior_date}）</h3>
     <div class="cmp-chips">${chips}</div>
     <div class="del-list"><b>删除/隐藏的作品：</b>${del}</div>`;
}

render();
</script>
</body>
</html>
"""


def process_account(client: TikHubClient, uid: str, name_hint: str,
                    db, stat_date: str) -> str:
    """处理单个账号：抓取→存库→对比→生成看板，返回输出文件路径"""
    captured_at = datetime.now(CST_).strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"📡 开始处理: uid={uid} ({name_hint})")

    profile, videos, total_count, not_login = fetch_account(client, uid, name_hint)

    # 存库
    db.save_snapshot(uid, profile.get("nickname", name_hint), profile)
    db.save_video_daily(uid, videos, stat_date)
    print(f"💾 已写入 SQLite：{len(videos)} 条作品 / 统计日 {stat_date}")

    # 与前一天对比
    comparison = {"has_prior": False, "prior_date": "", "new_count": 0,
                  "changed_caption": 0, "changed_tags": 0, "deleted_count": 0, "deleted": []}
    dates = db.get_distinct_dates(uid)
    prior_date = next((d for d in dates if d < stat_date), None)
    if prior_date:
        prior_records = db.get_records_by_date(uid, prior_date)
        comparison = compute_comparison(videos, prior_records, prior_date)
        print(f"🔍 对比基线 {prior_date}：新增 {comparison['new_count']} · "
              f"文案变化 {comparison['changed_caption']} · 标签变化 {comparison['changed_tags']} · "
              f"删除/隐藏 {comparison['deleted_count']}")

    # 生成看板
    html = build_html(profile, videos, stat_date, captured_at, comparison)
    out_dir = os.path.join(SCRIPT_DIR, "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"account_{uid}.html")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📄 看板已生成: {out_file}")
    print(f"✅ 完成。昵称={profile['nickname']} 作品数={len(videos)}")
    return out_file


def main():
    api_key = load_api_key()
    if not api_key:
        print("❌ 未找到 TikHub API Key，请确认 douyin-monitor.env.txt")
        sys.exit(1)

    client = TikHubClient(api_key=api_key, base_url="https://api.tikhub.dev")
    stat_date = datetime.now(CST_).strftime("%Y-%m-%d")

    os.makedirs(os.path.join(SCRIPT_DIR, "data"), exist_ok=True)
    db = MonitorDB(os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db"))

    # 支持三种调用方式：
    #   python build_single_account.py                     → 默认跑第一个账号
    #   python build_single_account.py UID1 UID2 ...        → 跑指定 UID 列表
    #   python build_single_account.py --batch              → 从 config.py 读全部账号
    #   python build_single_account.py --batch 3 5          → 从 config.py 跑第 3、5 个账号(从1开始)
    args = sys.argv[1:]
    uids_to_run = []
    names_to_run = {}

    if not args or args[0].startswith("--"):
        if "--batch" in args:
            # 从 config.py 批量读取
            try:
                from config import MONITOR_ACCOUNTS
                idx_filter = None
                if len(args) > 1:
                    indices = [int(x) for x in args[1:] if x.isdigit()]
                    if indices:
                        idx_filter = set(indices)
                for i, acc in enumerate(MONITOR_ACCOUNTS):
                    uid = str(acc.get("uid", ""))
                    if not uid:
                        continue
                    if idx_filter and (i + 1) not in idx_filter:
                        continue
                    uids_to_run.append(uid)
                    names_to_run[uid] = acc.get("name", f"账号_{i+1}")
                print(f"📋 --batch 模式：从 config.py 加载 {len(uids_to_run)} 个账号")
            except ImportError:
                print("⚠️ 未找到 config.py，回退到默认账号")
                uids_to_run = ["397396233431257"]
                names_to_run = {"397396233431257": "等晴天"}
        else:
            # 无参数 → 默认第一个
            uids_to_run = ["397396233431257"]
            names_to_run = {"397396233431257": "等晴天"}
    else:
        # 位置参数作为 UID 列表
        for a in args:
            if a.isdigit() or (a.startswith("MS4w")):
                uids_to_run.append(a)
                names_to_run.setdefault(a, f"UID_{a[:8]}")

    if not uids_to_run:
        print("❌ 未指定任何账号")
        sys.exit(1)

    print(f"🚀 共 {len(uids_to_run)} 个账号待处理 | 统计日: {stat_date}")
    outputs = []
    errors = []
    for uid in uids_to_run:
        try:
            out = process_account(client, uid, names_to_run.get(uid, uid), db, stat_date)
            outputs.append(out)
        except Exception as e:
            print(f"❌ uid={uid} 失败: {e}")
            errors.append((uid, str(e)))
            continue
        time.sleep(1.5)  # 接口限流保护

    # 汇总
    print(f"\n{'='*60}")
    print(f"🏁 全部完成: 成功 {len(outputs)}/{len(uids_to_run)}")
    for o in outputs:
        print(f"  ✅ {o}")
    for uid, err in errors:
        print(f"  ❌ {uid}: {err}")


if __name__ == "__main__":
    main()
