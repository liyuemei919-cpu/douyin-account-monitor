"""临时脚本：实时查询 5 个新账号的作品数（只读、不入 DB）。"""
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from build_single_account import load_api_key, load_cookie
from tikhub_client import TikHubClient, _payload, extract_profile

UIDS = ["88626305681","39043488272","33908169789","81630276328","60911988209"]

def main():
    key = load_api_key()
    ck = load_cookie()
    print(f"API Key: {'已配置' if key else '缺失!'} | Cookie: {'已配置' if ck else '缺失'}")
    if not key:
        print("❌ 无 API Key，无法查询"); return
    client = TikHubClient(api_key=key, cookie=ck)

    for uid in UIDS:
        print(f"\n=== UID {uid} ===")
        prof_raw = client.get_user_profile(uid, cookie=ck)
        prof = extract_profile(prof_raw)
        if not prof:
            print("  ⚠️ 资料获取失败：", (prof_raw or {}).get("body", str(prof_raw)[:200]))
            continue
        sec = prof.get("sec_uid") or ""
        print(f"  昵称: {prof.get('nickname')} | 抖音号: {prof.get('unique_id')} | 粉丝: {prof.get('follower_count')}")
        if not sec:
            print("  ⚠️ 无 sec_uid，无法翻作品"); continue
        # 翻页统计作品数
        count = 0; cursor = 0; pages = 0; err = None
        while pages < 20:  # 最多 20 页 = 1000 条上限保护
            pages += 1
            raw = client.get_user_videos(sec, max_count=50, cursor=cursor, cookie=ck)
            body = _payload(raw)
            al = body.get("aweme_list") or []
            count += len(al)
            has_more = body.get("has_more")
            mc = body.get("max_cursor")
            # 分页抖动：空页同 cursor 重试一次
            if not al and has_more:
                raw2 = client.get_user_videos(sec, max_count=50, cursor=cursor, cookie=ck)
                al2 = _payload(raw2).get("aweme_list") or []
                if al2:
                    count += len(al2); continue
            if not has_more:
                break
            if mc is None:
                break
            cursor = mc
            if count >= 1000:
                print("  ⚠️ 已达 1000 条上限，可能未统计完")
                break
        print(f"  ✅ 真实作品数（翻页汇总）: {count} 条（翻 {pages} 页）")

if __name__ == "__main__":
    main()
