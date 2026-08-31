#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量抓取所有监控账号的真实数据 → 存 SQLite → 供 build_consolidated.py 生成看板。

特性：
- 读取 build_consolidated.py 的 MONITOR_UIDS（单一数据源）
- 用 sec_uid 直接拉作品列表，绕过 fetch_account 的 not_login_module 误判
- 失败账号自动跳过并汇总，不影响其他账号
- 纯实时抓取（消耗少量 TikHub 额度）
"""
import sys
import time
sys.path.insert(0, ".")

from build_single_account import load_api_key, load_cookie, MonitorDB, CST_
from tikhub_client import TikHubClient, extract_profile, extract_videos
from datetime import datetime

# 从 build_consolidated 导入监控列表（单一数据源）
try:
    from build_consolidated import MONITOR_UIDS
except Exception:
    # 兜底：直接运行时从文件读取
    MONITOR_UIDS = []

SCRIPT_DIR = "."


def fetch_one(client, db, uid, cookie, stat_date):
    """抓取单个账号：资料 + 作品 → 存库。返回 (ok, name, n_videos)"""
    raw_p = client.get_user_profile(uid, cookie=cookie)
    prof = extract_profile(raw_p)
    if not prof:
        return (False, None, 0, "profile_fail")
    sec = prof.get("sec_uid", "")
    if not sec:
        return (False, prof.get("nickname"), 0, "no_sec_uid")
    raw_v = client.get_user_videos(sec, max_count=50, cursor=0, cookie=cookie)
    d = (raw_v.get("data") or {})
    al = (d.get("aweme_list") or []) or []
    n = len(al)
    if n:
        vids = extract_videos({"data": {"aweme_list": al}})
        db.save_snapshot(uid, prof["nickname"], prof)
        db.save_video_daily(uid, vids, stat_date)
        return (True, prof["nickname"], n, "OK")
    return (False, prof["nickname"], 0, "no_videos")


def main():
    if not MONITOR_UIDS:
        print("❌ MONITOR_UIDS 为空")
        sys.exit(1)
    api_key = load_api_key()
    if not api_key:
        print("❌ 未找到 TikHub API Key")
        sys.exit(1)
    cookie = load_cookie()
    client = TikHubClient(api_key=api_key, cookie=cookie)
    db = MonitorDB("data/douyin_monitor.db")
    sd = datetime.now(CST_).strftime("%Y-%m-%d")

    print(f"🚀 全量抓取 {len(MONITOR_UIDS)} 个账号 | 统计日 {sd}")
    ok, fail = [], []
    for i, uid in enumerate(MONITOR_UIDS):
        print(f"[{i+1}/{len(MONITOR_UIDS)}] {uid}", end=" ", flush=True)
        try:
            res = fetch_one(client, db, uid, cookie, sd)
            if res[0]:
                ok.append(res)
                print(f"✅ {res[1]} 作品{res[2]}")
            else:
                fail.append((res[1], res[2], res[3], uid))
                print(f"⚠️ {res[3]}")
        except Exception as e:
            fail.append((None, 0, f"ERR:{e}", uid))
            print(f"❌ {e}")
        time.sleep(1.5)  # 限流保护

    print(f"\n📊 完成：成功 {len(ok)} / 失败 {len(fail)}")
    print(f"📈 本次新抓作品总数：{sum(r[2] for r in ok)}")
    for r in fail:
        print(f"   ⚠️ uid={r[3]} name={r[0] or '未知'} reason={r[2]}")


if __name__ == "__main__":
    main()
