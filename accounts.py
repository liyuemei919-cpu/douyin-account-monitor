"""
监控账号列表的单一数据源：accounts.json

- 仅存储公开抖音账号的 uid + 昵称（昵称可不填），不含任何密钥，可安全入库。
- 网页操作面板（panel.py）与抓取/看板脚本都从这里读取，保证单一数据源。
- 真实密钥（TIKHUB_API_KEY / DOUYIN_COOKIE）只从本地 .env 读取，不在此文件。
"""
import os
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_accounts():
    """返回 [{uid, nickname}, ...]，accounts.json 缺失或解析失败时返回空列表。"""
    p = os.path.join(SCRIPT_DIR, "accounts.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return [a for a in data if isinstance(a, dict) and a.get("uid")]
        except Exception:
            pass
    return []


def save_accounts(accounts):
    p = os.path.join(SCRIPT_DIR, "accounts.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def load_uids():
    return [a["uid"] for a in load_accounts()]


def add_account(uid, nickname=""):
    """新增/更新账号（按 uid 去重）。返回是否发生了新增。"""
    uid = (uid or "").strip()
    if not uid:
        return False
    accounts = load_accounts()
    for a in accounts:
        if a["uid"] == uid:
            a["nickname"] = nickname or a.get("nickname", "")
            save_accounts(accounts)
            return False
    accounts.append({"uid": uid, "nickname": nickname})
    save_accounts(accounts)
    return True


def remove_account(uid):
    """按 uid 移除账号。返回是否真的发生了删除。"""
    accounts = load_accounts()
    new = [a for a in accounts if a["uid"] != uid]
    if len(new) != len(accounts):
        save_accounts(new)
        return True
    return False


def get_nickname(uid):
    for a in load_accounts():
        if a["uid"] == uid:
            return a.get("nickname") or ""
    return ""
