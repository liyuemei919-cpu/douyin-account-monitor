"""
抖音账号监控主程序

用法:
  # 正式运行（需要 API Key）
  python monitor.py

  # 演示模式（无需 Key，用模拟数据生成报告）
  python monitor.py --demo

  # 指定配置文件
  python monitor.py --config my_config.py

输出:
  - data/douyin_monitor.db   (SQLite 历史存档)
  - data/snapshot_YYYYMMDD.json (每日快照)
  - reports/report_YYYYMMDD.html (HTML 报告)
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from datetime import datetime, timezone, timedelta

# 确保项目目录在 path 中
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from tikhub_client import (
    TikHubClient,
    extract_profile,
    extract_videos,
    format_number,
    format_timestamp,
    CST,
)

# ============ 时区 ============
CST = timezone(timedelta(hours=8))


def load_config(config_path: str = "") -> dict:
    """加载配置，支持默认 config.py 或自定义路径"""
    if not config_path:
        config_path = os.path.join(SCRIPT_DIR, "config.py")

    config_globals = {}
    try:
        with open(config_path, encoding="utf-8") as f:
            exec(f.read(), config_globals)
        return {
            "api_key": config_globals.get("API_KEY", ""),
            "base_url": config_globals.get("BASE_URL", ""),
            "douplus_cookie": config_globals.get("DOUPLUS_COOKIE", ""),
            "accounts": config_globals.get("MONITOR_ACCOUNTS", []),
            "enable_fans": config_globals.get("ENABLE_FANS", True),
            "enable_videos": config_globals.get("ENABLE_VIDEOS", True),
            "enable_ecommerce": config_globals.get("ENABLE_ECOMMERCE", True),
            "enable_douplus": config_globals.get("ENABLE_DOUPlus", False),
            "video_max_count": config_globals.get("VIDEO_MAX_COUNT", 10),
            "data_dir": config_globals.get("DATA_DIR", "./data"),
            "db_name": config_globals.get("DB_NAME", "douyin_monitor.db"),
            "report_dir": config_globals.get("REPORT_DIR", "./reports"),
            "report_title": config_globals.get("REPORT_TITLE", "抖音账号监控日报"),
        }
    except FileNotFoundError:
        print(f"⚠️ 配置文件不存在: {config_path}")
        print("   请复制 config.py 为 config_local.py 并填写配置")
        return None


# ==================== 数据库操作 ====================

class MonitorDB:
    """SQLite 历史数据存档"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_uid TEXT NOT NULL,
                account_name TEXT,
                captured_at TEXT NOT NULL,
                follower_count INTEGER DEFAULT 0,
                following_count INTEGER DEFAULT 0,
                total_favorited INTEGER DEFAULT 0,
                aweme_count INTEGER DEFAULT 0,
                raw_profile TEXT,
                UNIQUE(account_uid, captured_at)
            );

            CREATE TABLE IF NOT EXISTS video_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_uid TEXT NOT NULL,
                aweme_id TEXT NOT NULL,
                stat_date TEXT NOT NULL,
                desc TEXT,
                title TEXT,
                tags TEXT,
                create_time INTEGER,
                cover TEXT,
                play_count INTEGER DEFAULT 0,
                digg_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                UNIQUE(account_uid, aweme_id, stat_date)
            );

            CREATE TABLE IF NOT EXISTS douplus_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_uid TEXT NOT NULL,
                aweme_id TEXT,
                total_consume REAL DEFAULT 0,
                total_play INTEGER DEFAULT 0,
                total_like INTEGER DEFAULT 0,
                total_comment INTEGER DEFAULT 0,
                total_share INTEGER DEFAULT 0,
                captured_at TEXT NOT NULL
            );
        """)
        # 兼容旧库：补充 cover 列（首次创建已含，已存在则忽略）
        try:
            c.execute("ALTER TABLE video_daily ADD COLUMN cover TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def save_snapshot(self, uid: str, name: str, profile: dict):
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO snapshots
            (account_uid, account_name, captured_at, follower_count,
             following_count, total_favorited, aweme_count, raw_profile)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, name, now,
              profile.get("follower_count", 0),
              profile.get("following_count", 0),
              profile.get("total_favorited", 0),
              profile.get("aweme_count", 0),
              json.dumps(profile, ensure_ascii=False)))
        conn.commit()
        conn.close()

    # ============ 作品逐日累计（按天聚合）============

    def save_video_daily(self, uid: str, videos: list[dict], stat_date: str):
        """按「天」聚合写入：同一作品同一天只保留最新一条（多次运行合并）"""
        conn = self._get_conn()
        c = conn.cursor()
        for v in videos:
            c.execute("""
                INSERT OR REPLACE INTO video_daily
                (account_uid, aweme_id, stat_date, desc, title, tags,
                 create_time, cover, play_count, digg_count, comment_count,
                 share_count, collect_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (uid, v["aweme_id"], stat_date, v["desc"], v.get("title", ""),
                  v.get("tags", ""), v["create_time"], v.get("cover", ""),
                  v["play_count"], v["digg_count"], v["comment_count"],
                  v["share_count"], v["collect_count"]))
        conn.commit()
        conn.close()

    def get_distinct_dates(self, uid: str) -> list[str]:
        """该账号所有有数据的日期（降序）"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT DISTINCT stat_date FROM video_daily
            WHERE account_uid = ? ORDER BY stat_date DESC
        """, (uid,))
        rows = [r["stat_date"] for r in c.fetchall()]
        conn.close()
        return rows

    def get_records_by_date(self, uid: str, stat_date: str) -> list[dict]:
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM video_daily
            WHERE account_uid = ? AND stat_date = ?
        """, (uid, stat_date))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_work_series(self, uid: str) -> dict:
        """返回 {aweme_id: [按日期升序的逐日记录]}"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM video_daily
            WHERE account_uid = ? ORDER BY stat_date ASC
        """, (uid,))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        series: dict = {}
        for r in rows:
            series.setdefault(r["aweme_id"], []).append(r)
        return series

    def seed_demo_baseline(self, uid: str, name: str):
        """
        演示模式：清空该 uid 旧数据，写入连续 3 天（前天/昨天/今天）的演变基线，
        内含：一条跨天文案/标签多次变化、一条被删除/隐藏、一条今天新增。
        今日采集（demo client）会与这份基线合并，从而展示真正的「逐日累计」。
        """
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM video_daily WHERE account_uid = ?", (uid,))
        d2 = (datetime.now(CST) - timedelta(days=2)).strftime("%Y-%m-%d")
        d1 = (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")
        d0 = datetime.now(CST).strftime("%Y-%m-%d")

        base = int(__import__("time").time())
        # 各作品三天的演变；demo_001 的 d0 会被今日 client 数据覆盖
        seed_rows = [
            # demo_001：三天内文案/标签持续变化（累计 2 次变化），数据递增
            ("demo_001", d2, "旧版文案：巷子里的苍蝇馆子，本地人从小吃到大！", "巷子里的苍蝇馆子", "",
             base-86400, 150000, 10000, 2000, 800, 2400),
            ("demo_001", d1, "【成都】巷子里的苍蝇馆子，本地人从小吃到大！ #成都美食", "巷子里的苍蝇馆子", "成都美食",
             base-86400, 198000, 14000, 2600, 1100, 3300),
            ("demo_001", d0, "【成都】巷子里的苍蝇馆子，本地人从小吃到大！ #成都美食", "巷子里的苍蝇馆子", "成都美食",
             base-86400, 230000, 16000, 3000, 1300, 3800),
            # demo_002：三天不变
            ("demo_002", d2, "周末去哪儿？这个网红打卡地拍照超出片 📸", "周末去哪儿", "",
             base-172800, 189000, 12500, 2180, 960, 3100),
            ("demo_002", d1, "周末去哪儿？这个网红打卡地拍照超出片 📸", "周末去哪儿", "",
             base-172800, 189000, 12500, 2180, 960, 3100),
            ("demo_002", d0, "周末去哪儿？这个网红打卡地拍照超出片 📸", "周末去哪儿", "",
             base-172800, 189000, 12500, 2180, 960, 3100),
            # demo_003：前天/昨天在，今天消失 → 删除/隐藏
            ("demo_003", d2, "限时福利！这家店周年庆全场五折 🎉 #优惠 #探店", "周年庆五折福利", "优惠,探店",
             base-259200, 95000, 6200, 980, 540, 1700),
            ("demo_003", d1, "限时福利！这家店周年庆全场五折 🎉 #优惠 #探店", "周年庆五折福利", "优惠,探店",
             base-259200, 95000, 6200, 980, 540, 1700),
            # demo_004：仅今天出现 → 新增
            ("demo_004", d0, "新品首发！这家店的隐藏菜单太惊艳了 🤫 #新品 #探店", "新品首发", "新品,探店",
             base-3600, 12000, 1500, 230, 90, 380),
        ]
        for (aid, sd, desc, title, tags, ct, pc, dg, cm, sh, cl) in seed_rows:
            c.execute("""
                INSERT INTO video_daily
                (account_uid, aweme_id, stat_date, desc, title, tags,
                 create_time, play_count, digg_count, comment_count,
                 share_count, collect_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (uid, aid, sd, desc, title, tags, ct, pc, dg, cm, sh, cl))
        conn.commit()
        conn.close()

    def save_douplus(self, uid: str, items: list[dict]):
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._get_conn()
        c = conn.cursor()
        for item in items:
            c.execute("""
                INSERT INTO douplus_data
                (account_uid, aweme_id, total_consume, total_play,
                 total_like, total_comment, total_share, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (uid, item.get("aweme_id"), item.get("total_consume", 0),
                  item.get("total_play", 0), item.get("total_like", 0),
                  item.get("total_comment", 0), item.get("total_share", 0),
                  now))
        conn.commit()
        conn.close()

    def get_history(self, uid: str, days: int = 7) -> list[dict]:
        """获取最近 N 天的粉丝快照"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT * FROM snapshots
            WHERE account_uid = ?
            ORDER BY captured_at DESC LIMIT ?
        """, (uid, days))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows


# ==================== 作品级逐日对比（diff）====================

# 参与对比的互动指标
METRIC_FIELDS = [
    ("play_count", "播放"),
    ("digg_count", "点赞"),
    ("comment_count", "评论"),
    ("share_count", "转发"),
    ("collect_count", "收藏"),
]


def build_work_diff(current_videos: list[dict],
                    prev_videos: list[dict]) -> dict:
    """
    构建作品级逐日对比结果。

    返回结构：
    {
      "summary": {
          "new": 新增作品数,
          "removed": 删除/隐藏数,
          "caption_changed": 文案变化数,
          "tags_changed": 标签变化数,
          "metric_changed": 数据增量数,
      },
      "changes": [ ... 按类型排序的变化条目 ... ],
      "deltas": { aweme_id: { "digg_count": +123, ... } }  # 供作品表显示增量
    }
    """
    cur = {v.get("aweme_id"): v for v in current_videos if v.get("aweme_id")}
    prev = {v.get("aweme_id"): v for v in prev_videos if v.get("aweme_id")}

    new_ids = set(cur) - set(prev)
    removed_ids = set(prev) - set(cur)
    common_ids = set(cur) & set(prev)

    changes = []
    deltas = {}

    # --- 新增作品 ---
    for aid in new_ids:
        v = cur[aid]
        changes.append({
            "type": "new",
            "aweme_id": aid,
            "title": v.get("title", ""),
            "desc": v.get("desc", ""),
            "tags": v.get("tags", ""),
            "metrics": v,
        })

    # --- 删除/隐藏作品 ---
    for aid in removed_ids:
        v = prev[aid]
        changes.append({
            "type": "removed",
            "aweme_id": aid,
            "title": v.get("title", ""),
            "desc": v.get("desc", ""),
            "tags": v.get("tags", ""),
            "metrics": v,  # 用上次记录的数据展示
        })

    # --- 共同作品：文案/标签/数据变化 ---
    for aid in common_ids:
        c = cur[aid]
        p = prev[aid]
        caption_changed = (c.get("desc", "") != p.get("desc", ""))
        tags_changed = (c.get("tags", "") != p.get("tags", ""))
        metric_deltas = {}
        for key, _ in METRIC_FIELDS:
            d = (c.get(key, 0) or 0) - (p.get(key, 0) or 0)
            if d != 0:
                metric_deltas[key] = d
        deltas[aid] = metric_deltas
        if caption_changed or tags_changed or metric_deltas:
            changes.append({
                "type": "changed",
                "aweme_id": aid,
                "title": c.get("title", ""),
                "caption_changed": caption_changed,
                "tags_changed": tags_changed,
                "old_desc": p.get("desc", ""),
                "new_desc": c.get("desc", ""),
                "old_tags": p.get("tags", ""),
                "new_tags": c.get("tags", ""),
                "metric_deltas": metric_deltas,
                "current_metrics": c,
                "prev_metrics": p,
            })

    # 排序：删除/隐藏 → 文案变化 → 标签变化 → 新增 → 仅数据变化
    order = {"removed": 0, "changed": 1, "new": 2}
    changes.sort(key=lambda x: (order.get(x["type"], 9),
                                x.get("caption_changed", False) is False))

    summary = {
        "new": len(new_ids),
        "removed": len(removed_ids),
        "caption_changed": sum(1 for c in changes
                               if c["type"] == "changed" and c.get("caption_changed")),
        "tags_changed": sum(1 for c in changes
                            if c["type"] == "changed" and c.get("tags_changed")),
        "metric_changed": sum(1 for c in changes
                              if c["type"] == "changed" and c.get("metric_deltas")),
        "total": len(changes),
    }

    return {"summary": summary, "changes": changes, "deltas": deltas}


def build_cumulative(uid: str, db: "MonitorDB") -> dict:
    """
    构建账号级「逐日累计」分析：把每个作品的每日快照串成时间序列。

    返回结构：
    {
      "dates":        [日期降序],
      "latest_date":  最新日期,
      "prev_date":    上一日期(可能为 None),
      "diff":         build_work_diff(latest, prev) 的告警视图,
      "works":        [每个作品的累计信息，见下],
    }

    works 元素：
      aweme_id, title, first_date, last_date, status('alive'/'removed'),
      latest(最新日记录), first(首发日记录), growth(首发→最新 增量),
      series(按日期升序记录), caption_events(文案变化事件列表),
      tag_events(标签变化事件列表), caption_changes, tag_changes
    """
    dates = db.get_distinct_dates(uid)
    if not dates:
        return {"dates": [], "latest_date": None, "prev_date": None,
                "diff": {"summary": {}, "changes": [], "deltas": {}},
                "works": []}

    latest = dates[0]
    prev = dates[1] if len(dates) > 1 else None
    latest_rows = db.get_records_by_date(uid, latest)
    prev_rows = db.get_records_by_date(uid, prev) if prev else []
    diff = build_work_diff(latest_rows, prev_rows)

    series_map = db.get_work_series(uid)
    works = []
    for aid, rows in series_map.items():
        rows = sorted(rows, key=lambda r: r["stat_date"])
        first = rows[0]
        last = rows[-1]
        caption_events = []
        tag_events = []
        pd = None
        pt = None
        for r in rows:
            if pd is not None and r["desc"] != pd:
                caption_events.append({"date": r["stat_date"],
                                       "old": pd, "new": r["desc"]})
            if pt is not None and r["tags"] != pt:
                tag_events.append({"date": r["stat_date"],
                                   "old": pt, "new": r["tags"]})
            pd = r["desc"]
            pt = r["tags"]
        status = "alive" if last["stat_date"] == latest else "removed"
        growth = {k: (last.get(k, 0) or 0) - (first.get(k, 0) or 0)
                  for k, _ in METRIC_FIELDS}
        works.append({
            "aweme_id": aid,
            "title": last.get("title", ""),
            "first_date": first["stat_date"],
            "last_date": last["stat_date"],
            "status": status,
            "latest": last,
            "first": first,
            "growth": growth,
            "series": rows,
            "caption_events": caption_events,
            "tag_events": tag_events,
            "caption_changes": len(caption_events),
            "tag_changes": len(tag_events),
        })

    # 排序：被删除/隐藏的排最前，其余按最新点赞数降序
    works.sort(key=lambda w: (w["status"] != "removed",
                              -(w["latest"].get("digg_count", 0) or 0)))

    return {"dates": dates, "latest_date": latest, "prev_date": prev,
            "diff": diff, "works": works}


# ==================== 核心采集逻辑 ====================

def resolve_uid(client: TikHubClient, account: dict) -> str | None:
    """
    解析账号 UID：
      1. 如果直接提供了 uid → 直接返回
      2. 如果只有 unique_id → 通过搜索接口解析
    """
    uid = account.get("uid", "")
    if uid:
        print(f"  ✅ 使用已有 UID: {uid[:20]}...")
        return uid

    unique_id = account.get("unique_id", "")
    if not unique_id:
        print(f"  ❌ 账号 {account['name']} 缺少 uid 和 unique_id")
        return None

    print(f"  🔍 搜索用户: {unique_id} ...")
    result = client.search_user(unique_id)
    users = result.get("data", {}).get("user_list", [])
    if users:
        found = users[0]
        print(f"  ✅ 找到: {found['nickname']} (uid={found['uid'][:20]}...)")
        return found["uid"]

    print(f"  ❌ 未找到用户: {unique_id}")
    return None


def collect_account(client: TikHubClient, db: MonitorDB,
                    account: dict, cfg: dict) -> dict:
    """采集单个账号的全部维度数据"""
    name = account.get("name", "未知账号")
    print(f"\n{'='*50}")
    print(f"📊 采集账号: {name}")
    print(f"{'='*50}")

    result = {
        "name": name,
        "tags": account.get("tags", []),
        "profile": None,
        "videos": [],
        "ecommerce": None,
        "douplus": None,
        "errors": [],
        "captured_at": datetime.now(CST).isoformat(),
    }

    # --- 解析 UID ---
    uid = resolve_uid(client, account)
    if not uid:
        result["errors"].append("无法解析账号 UID")
        return result
    result["uid"] = uid

    # --- 维度1：粉丝与增长 ---
    if cfg.get("enable_fans"):
        print("\n📈 [维度1] 粉丝与增长 ...")
        raw = client.get_user_profile(uid)
        profile = extract_profile(raw)
        if profile:
            result["profile"] = profile
            db.save_snapshot(uid, name, profile)
            print(f"  👤 昵称: {profile['nickname']}")
            print(f"  📊 粉丝: {format_number(profile['follower_count'])} | "
                  f"关注: {format_number(profile['following_count'])}")
            print(f"  ❤️ 总获赞: {format_number(profile['total_favorited'])} | "
                  f"作品: {profile['aweme_count']}")
        else:
            result["errors"].append("粉丝资料获取失败")

    # --- 维度2：作品数据（逐日累计）---
    if cfg.get("enable_videos"):
        print(f"\n🎬 [维度2] 作品数据 (最多{cfg['video_max_count']}条) ...")
        # 演示模式：先写入连续 3 天的演变基线，便于展示逐日累计
        if client.demo_mode:
            db.seed_demo_baseline(uid, name)
        raw = client.get_user_videos(profile["sec_uid"], max_count=cfg.get("video_max_count", 10))
        videos = extract_videos(raw)
        if videos:
            result["videos"] = videos
            stat_date = datetime.now(CST).strftime("%Y-%m-%d")
            db.save_video_daily(uid, videos, stat_date)
            # === 逐日累计分析 ===
            result["cumulative"] = build_cumulative(uid, db) if db else None
            cum = result.get("cumulative") or {}
            diff = cum.get("diff", {}).get("summary", {})
            n_works = len(cum.get("works", []))
            print(f"  📹 本次采集 {len(videos)} 条；累计追踪作品 {n_works} 个；"
                  f"最新一天对比：新增 {diff.get('new',0)} / 删除隐藏 {diff.get('removed',0)} / "
                  f"文案变化 {diff.get('caption_changed',0)} / 标签变化 {diff.get('tags_changed',0)} / "
                  f"数据增量 {diff.get('metric_changed',0)}")
            for i, v in enumerate(videos[:5], 1):
                print(f"    {i}. [{format_timestamp(v['create_time'])}] "
                      f"{v['desc'][:30]}...")
                print(f"       ▶️{format_number(v['play_count'])}  "
                      f"❤️{format_number(v['digg_count'])}  "
                      f"💬{format_number(v['comment_count'])}  "
                      f"↗️{format_number(v['share_count'])}  "
                      f"⭐{format_number(v['collect_count'])}")
            if len(videos) > 5:
                print(f"    ... 还有 {len(videos)-5} 条")
        else:
            result["errors"].append("作品列表为空或获取失败")

    # --- 维度3：带货电商（星图） ---
    if cfg.get("enable_ecommerce"):
        print("\n🛒 [维度3] 带货电商（星图） ...")
        sec_uid = (result.get("profile") or {}).get("sec_uid", "") or uid
        raw = client.get_xingtu_promotion_cards(sec_uid)
        if raw.get("error"):
            msg = raw.get("body", "")[:100]
            result["errors"].append(f"星图数据不可用（可能未开通权限）: {msg}")
            print(f"  ⚠️ 星图接口返回错误: {raw.get('status')}")
        elif raw.get("data"):
            result["ecommerce"] = raw["data"]
            cards = raw["data"].get("promotion_cards", [])
            print(f"  🏪 推广商品数: {len(cards)}")
            gmv = raw["data"].get("total_gmv", 0)
            sales = raw["data"].get("total_sales", 0)
            if gmv:
                print(f"  💰 GMV: ¥{gmv:,.0f} | 销量: {sales:,}")
        else:
            print("  ℹ️ 无带货数据（该账号可能未开通星图/橱窗）")

    # --- 维度4：Dou+投放 ---
    if cfg.get("enable_douplus"):
        print("\n💰 [维度4] Dou+投放数据 ...")
        cookie = cfg.get("douplus_cookie", "")
        if not cookie:
            result["errors"].append("Dou+ Cookie 未配置")
            print("  ⚠️ 未配置 Dou+ Cookie，跳过投放数据采集")
        else:
            raw = client.get_douplus_promotable_items(cookie=cookie)
            dp_data = raw.get("data", {})
            if dp_data:
                items = dp_data.get("promotable_items", [])
                result["douplus"] = dp_data
                # 存入数据库
                db.save_douplus(uid, items)
                total_consume = dp_data.get("total_consume", 0)
                print(f"  📢 可推广视频: {len(items)} 条")
                print(f"  💸 总消耗: ¥{total_consume:,.2f}")
                for item in items[:5]:
                    print(f"    • {item.get('desc','?')[:35]}... "
                          f"| 消耗¥{item.get('total_consume',0):,.0f} "
                          f"| ▶️{format_number(item.get('total_play',0))}")
            else:
                err_msg = raw.get("body", "")[:150]
                result["errors"].append(f"Dou+数据获取失败: {err_msg}")
                print(f"  ⚠️ Dou+ 接口异常: {raw.get('status')}")

    return result


# ==================== 主流程 ====================

def main():
    parser = argparse.ArgumentParser(description="抖音账号监控系统")
    parser.add_argument("--demo", action="store_true",
                        help="演示模式：使用模拟数据，无需 API Key")
    parser.add_argument("--config", default="",
                        help="自定义配置文件路径")
    args = parser.parse_args()

    # 加载配置
    cfg = load_config(args.config)
    if not cfg:
        sys.exit(1)

    accounts = cfg.get("accounts", [])
    if not accounts:
        print("⚠️ 未配置任何监控账号，请编辑 config.py 的 MONITOR_ACCOUNTS")
        sys.exit(1)

    # 初始化客户端
    demo_mode = args.demo or not cfg.get("api_key")
    if demo_mode:
        print("🎭 演示模式：使用模拟数据\n")
    client = TikHubClient(
        api_key=cfg.get("api_key", ""),
        base_url=cfg.get("base_url", ""),
        cookie=cfg.get("douplus_cookie", ""),
        demo_mode=demo_mode,
    )

    # 初始化数据库
    db_path = os.path.join(cfg["data_dir"], cfg["db_name"])
    db = MonitorDB(db_path)

    # 逐账号采集
    all_results = []
    for acc in accounts:
        result = collect_account(client, db, acc, cfg)
        all_results.append(result)
        time.sleep(1)  # 避免频率限制

    # 保存每日快照 JSON
    snapshot_file = os.path.join(
        cfg["data_dir"],
        f"snapshot_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.json"
    )
    os.makedirs(cfg["data_dir"], exist_ok=True)
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 快照已保存: {snapshot_file}")

    # 生成报告
    from report_generator import generate_report
    report_html = generate_report(all_results, cfg, db)
    os.makedirs(cfg["report_dir"], exist_ok=True)
    report_file = os.path.join(
        cfg["report_dir"],
        f"report_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}.html"
    )
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"📄 报告已生成: {report_file}")

    print(f"\n✅ 监控完成！共采集 {len(all_results)} 个账号")
    return report_file


if __name__ == "__main__":
    main()
