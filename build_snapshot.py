"""
按指定统计日生成「定格」历史看板快照（纯读 DB，不重新抓取，不覆盖线上 index.html）。

与 build_consolidated.py 的区别：
  - 基准日锁定为 --date 指定的那一天，而非 datetime.now()；
  - 当天无数据时，只回退到「<= 基准日」的最近可用日（不会混入基准日之后的新数据）；
  - 每条作品的逐日历史(daily)截断到「<= 基准日」，确保「查看每日」也定格在当天。

用法:
  python build_snapshot.py --date 2026-08-29
输出:
  deploy/index_2026-08-29.html
"""
import os
import sys
import json
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_multi_account import MonitorDB, CST_, compute_comparison, assemble_data
from build_consolidated import TEMPLATE, MONITOR_UIDS

DB_PATH = os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db")


def load_account_frozen(db, uid, stat_date):
    """定格版加载：以 stat_date 为基准日。

    关键特性：即使视频被删除/隐藏，只要数据库里（<= 基准日）曾经抓到过就保留其数据留存——
    作品列表取「<= 基准日」的全部视频（按 aweme_id 去重），最后出现日 < 基准日 → 标记已删除/隐藏。
    回退只到 <= 基准日的最近可用日；逐日历史(daily)也截断到 <= 基准日。
    """
    rows = db.get_records_by_date(uid, stat_date)
    used_date = stat_date
    if not rows:
        dates = db.get_distinct_dates(uid)
        prior_avail = [d for d in dates if d <= stat_date]
        if prior_avail:
            used_date = max(prior_avail)
            rows = db.get_records_by_date(uid, used_date)
            print(f"  ℹ️ {uid} 无 {stat_date} 数据，回退到 {used_date}")
    if not rows:
        return None
    day_ids = {r["aweme_id"] for r in rows}

    # 全量去重集合（<= 基准日），取每个视频「最后出现」的那条记录
    conn = db._get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT aweme_id, stat_date, desc, title, tags, create_time, play_count, "
        "digg_count, comment_count, share_count, collect_count, cover "
        "FROM video_daily WHERE account_uid=? AND stat_date <= ? ORDER BY aweme_id, stat_date",
        (uid, stat_date),
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

    # 逐日历史（截断到 <= stat_date，定格）
    conn = db._get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT aweme_id, stat_date, digg_count, comment_count, share_count, collect_count "
        "FROM video_daily WHERE account_uid=? AND aweme_id IN ("
        + ",".join("?" for _ in videos) + ") AND stat_date <= ? ORDER BY aweme_id, stat_date",
        [uid] + [v["aweme_id"] for v in videos] + [stat_date],
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

    # 最新资料快照
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

    total_count = len(videos)
    capped = False
    comparison = {"has_prior": False, "prior_date": "", "new_count": 0,
                  "changed_caption": 0, "changed_tags": 0, "deleted_count": 0,
                  "deleted": [], "deletion_limited": False}
    dates = db.get_distinct_dates(uid)
    prior_date = next((d for d in dates if d < used_date), None)
    if prior_date:
        prior_records = db.get_records_by_date(uid, prior_date)
        day_videos = [v for v in videos if v["aweme_id"] in day_ids]
        comparison = compute_comparison(day_videos, prior_records, prior_date, capped=capped)

    for v in videos:
        if v.get("deleted"):
            v["is_new"] = False
            v["caption_changed"] = False
            v["tags_changed"] = False
            v["ddigg"] = v["dcomm"] = v["dshare"] = v["dcoll"] = None

    captured_at = datetime.now(CST_).strftime("%Y-%m-%d %H:%M:%S")
    data = assemble_data(profile, videos, used_date, captured_at, comparison,
                         total_count, gated=False)
    amap = {v["aweme_id"]: v["deleted"] for v in videos}
    for outv in data["videos"]:
        outv["deleted"] = amap.get(outv["aweme_id"], False)
    data["summary"]["deleted_count"] = len(deleted_ids)
    data["capped"] = capped
    data["from_db"] = True
    data["stat_date"] = used_date  # 定格：总览"最近更新"显示实际数据日
    return data


def main():
    args = sys.argv[1:]
    stat_date = ""
    for i, a in enumerate(args):
        if a == "--date" and i + 1 < len(args):
            stat_date = args[i + 1]
        elif a.startswith("--date="):
            stat_date = a.split("=", 1)[1]
    if not stat_date:
        stat_date = datetime.now(CST_).strftime("%Y-%m-%d")

    db = MonitorDB(DB_PATH)
    accounts = []
    for uid in MONITOR_UIDS:
        try:
            d = load_account_frozen(db, uid, stat_date)
        except Exception as e:
            print(f"❌ {uid} 加载失败: {e}")
            continue
        if not d:
            print(f"⚠️ {uid} 数据库无 <= {stat_date} 数据，跳过")
            continue
        p = d["profile"]
        acc_url = "https://www.douyin.com/user/" + (p.get("sec_uid") or "")
        # 注入前端所需字段（与 build_consolidated.main 一致）
        for v in d["videos"]:
            v["nickname"] = p.get("nickname", uid)
            v["account_url"] = acc_url
            v["n_days"] = len(v.get("daily") or [])
        accounts.append(d)
        print(f"✅ {uid} {p.get('nickname')} 作品={d['summary']['video_count']} (数据日 {d['stat_date']})")

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
    out = os.path.join(deploy_dir, f"index_{stat_date}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📄 定格看板已生成: {out}")
    print(f"   基准日={stat_date} 账号={len(accounts)} 作品={sum(len(a['videos']) for a in accounts)} "
          f"统计日={all_dates} 多日数据作品={multi_day}")


if __name__ == "__main__":
    main()
