"""
TikHub 抖音数据客户端 v2
支持四大监控维度：粉丝与增长 / 作品数据 / 带货电商 / Dou+投放

接口来源（基于已安装的 kk-kingkong-tiktok-pipeline-100 skill + TikHub 文档验证）：
  维度1-粉丝:   GET  /api/v1/douyin/web/fetch_user_profile_by_uid        (免费)
  维度1-粉丝:   GET  /api/v1/douyin/web/fetch_user_fans_list             (免费)
  维度2-作品:   GET  /api/v1/douyin/web/fetch_user_post_videos            (免费)
  维度2-作品:   GET  /api/v1/douyin/web/fetch_one_video                   (免费)
  维度3-搜索:   GET  /api/v1/douyin/search/fetch_user_search_result       (免费)
  维度3-电商:   GET  /api/v1/douyin/xingtu/fetch_promotion_card_list     (需星图权限)
  维度4-Dou+:   POST /api/v1/douyin/douplus/fetch_promotable_item_list    (需Cookie)
  维度4-Dou+:   POST /api/v1/douyin/douplus/fetch_video_ranking          (需Cookie)

技术选型：仅用标准库 urllib + json（不依赖 requests），保证自动化任务可直接运行。
"""

import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta

# ============ 时区 ============
CST = timezone(timedelta(hours=8))

# ============ 配置默认值 ============
DEFAULT_BASE_URL = "https://api.tikhub.dev"  # 国内用户用 .dev，无需代理


class TikHubClient:
    """TikHub 抖音数据客户端"""

    def __init__(self, api_key: str = "", base_url: str = "",
                 cookie: str = "", demo_mode: bool = False):
        """
        Args:
            api_key:     TikHub API Token (Bearer token)
            base_url:    API 基地址，国内用 https://api.tikhub.dev
            cookie:      抖音用户 Cookie（Dou+ 接口需要）
            demo_mode:   True 时所有请求返回模拟数据，不实际调用 API
        """
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_BASE_URL
        self.cookie = cookie
        self.demo_mode = demo_mode
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "douyin-monitor/2.0",
        }

    # ==================== 通用请求 ====================

    def _request(self, method: str, endpoint: str,
                 params: dict = None, json_data: dict = None,
                 extra_headers: dict = None) -> dict:
        """通用请求方法，带 429 退避"""
        if self.demo_mode:
            return self._demo_response(endpoint)

        url = f"{self.base_url}{endpoint}"
        headers = {**self._headers}
        if extra_headers:
            headers.update(extra_headers)

        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(json_data).encode() if json_data else None

        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=data,
                                             headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 5 * (attempt + 1)
                    print(f"  ⚠️ 频率限制 429，等待 {wait}s... ({attempt+1}/3)")
                    time.sleep(wait)
                    continue
                body = e.read().decode(errors="replace")
                return {"error": True, "status": e.code, "body": body}
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return {"error": True, "exception": str(e)}

        return {"error": True, "message": "max retries exceeded"}

    def _get(self, endpoint: str, params: dict = None) -> dict:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, json_data: dict = None,
              extra_headers: dict = None) -> dict:
        return self._request("POST", endpoint, json_data=json_data,
                            extra_headers=extra_headers)

    # ==================== 演示模式 ====================

    @staticmethod
    def _demo_response(endpoint: str) -> dict:
        """返回模拟数据用于演示"""
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

        if "fetch_user_profile_by_uid" in endpoint:
            return {
                "data": {
                    "user": {
                        "nickname": "示例账号_美食探店",
                        "uid": "MS4wLjABAAAA_demo",
                        "sec_uid": "MS4wLjABAAAA_sec_demo",
                        "unique_id": "meishi_tandian",
                        "signature": "📍成都 | 每日探店分享",
                        "follower_count": 128500,
                        "following_count": 368,
                        "total_favorited": 5200000,
                        "aweme_count": 486,
                        "avatar_thumb": {"url_list": [""]},
                    }
                }
            }

        if "fetch_user_post_videos" in endpoint:
            return {
                "data": {
                    "aweme_list": [
                        {
                            "aweme_id": "demo_001",
                            "desc": "【成都】这家藏在巷子里的苍蝇馆子太绝了！人均30吃到撑 🍜 #成都美食 #探店打卡",
                            "video_tags": [
                                {"tag_name": "成都美食"},
                                {"tag_name": "探店打卡"},
                            ],
                            "create_time": int(time.time()) - 86400,
                            "statistics": {
                                "play_count": 256800,
                                "digg_count": 18200,
                                "comment_count": 3420,
                                "share_count": 1580,
                                "collect_count": 4200,
                            },
                        },
                        {
                            "aweme_id": "demo_002",
                            "desc": "周末去哪儿？这个网红打卡地拍照超出片 📸",
                            "create_time": int(time.time()) - 172800,
                            "statistics": {
                                "play_count": 189000,
                                "digg_count": 12500,
                                "comment_count": 2180,
                                "share_count": 960,
                                "collect_count": 3100,
                            },
                        },
                    ]
                }
            }

        if "fetch_user_fans_list" in endpoint:
            return {
                "data": {
                    "fans_list": [
                        {"uid": "f001", "nickname": "粉丝A", "follower_count": 1200},
                        {"uid": "f002", "nickname": "粉丝B", "follower_count": 850},
                    ],
                    "total": 128500,
                }
            }

        if "xingtu" in endpoint:
            return {
                "data": {
                    "promotion_cards": [
                        {
                            "item_id": "pc_001",
                            "title": "爆款推荐商品A",
                            "price": 69.9,
                            "sales_volume": 2340,
                            "commission_rate": 15,
                        }
                    ],
                    "total_sales": 156780,
                    "total_gmv": 892340,
                }
            }

        if "douplus" in endpoint:
            return {
                "data": {
                    "promotable_items": [
                        {
                            "aweme_id": "dp_001",
                            "desc": "推广视频A",
                            "like_count": 15200,
                            "comment_count": 890,
                            "total_consume": 1500.00,
                            "total_play": 125000,
                            "total_like": 8200,
                            "total_comment": 450,
                            "total_share": 210,
                        },
                        {
                            "aweme_id": "dp_002",
                            "desc": "推广视频B",
                            "like_count": 9800,
                            "comment_count": 520,
                            "total_consume": 800.00,
                            "total_play": 78000,
                            "total_like": 5100,
                            "total_comment": 280,
                            "total_share": 130,
                        },
                    ],
                    "total_consume": 2300.00,
                }
            }

        if "search" in endpoint:
            return {
                "data": {
                    "user_list": [
                        {
                            "uid": "MS4wLjABAAAA_demo",
                            "nickname": "示例账号_美食探店",
                            "unique_id": "meishi_tandian",
                        }
                    ]
                }
            }

        return {"data": {}}

    # ==================== 维度1：粉丝与增长 ====================

    def get_user_profile(self, uid: str, cookie: str = "") -> dict:
        """
        获取用户资料（粉丝数/关注数/获赞总数/作品数）
        端点: GET /api/v1/douyin/web/fetch_user_profile_by_uid
        免费
        注意: 部分账号（私密/新号）的资料与作品会被「登录态」挡住，接口会返回
              not_login_module 且 aweme_count=0。传入已登录的抖音网页 Cookie
              可解锁真实数据（cookie 作为 query 参数透传给 TikHub）。
        """
        params = {"uid": uid}
        if cookie:
            params["cookie"] = cookie
        return self._get("/api/v1/douyin/web/fetch_user_profile_by_uid",
                         params=params)

    def get_fans_list(self, unique_id: str, count: int = 20) -> dict:
        """
        获取粉丝列表（用于分析粉丝质量/变化）
        端点: GET /api/v1/douyin/web/fetch_user_fans_list
        免费
        """
        return self._get("/api/v1/douyin/web/fetch_user_fans_list",
                         params={"unique_id": unique_id, "count": count})

    # ==================== 维度2：作品数据 ====================

    def get_user_videos(self, sec_user_id: str, max_count: int = 20,
                        cursor: int = 0, cookie: str = "") -> dict:
        """
        获取用户发布的视频列表（含播放/点赞/评论/转发/收藏/封面）
        端点: GET /api/v1/douyin/web/fetch_user_post_videos
        免费
        注意：该接口需传 sec_user_id（从 fetch_user_profile_by_uid 返回的
              sec_uid 字段获得），仅传 uid 会返回空列表。
              未登录态下部分账号会返回 not_login_module 且 aweme_list 为空，
              传入 cookie 可解锁真实作品列表。
        """
        params = {
            "sec_user_id": sec_user_id,
            "max_cursor": cursor,
            "count": max_count,
        }
        if cookie:
            params["cookie"] = cookie
        return self._get("/api/v1/douyin/web/fetch_user_post_videos",
                         params=params)

    def get_video_detail(self, aweme_id: str) -> dict:
        """
        获取单个视频详情
        端点: GET /api/v1/douyin/web/fetch_one_video
        免费
        """
        return self._get("/api/v1/douyin/web/fetch_one_video",
                         params={"aweme_id": aweme_id})

    # ==================== 辅助：搜索用户 ====================

    def search_user(self, keyword: str, offset: int = 0,
                    count: int = 10) -> dict:
        """
        通过昵称/抖音号搜索用户 → 解析出 uid
        端点: GET /api/v1/douyin/search/fetch_user_search_result
        免费
        """
        return self._get("/api/v1/douyin/search/fetch_user_search_result",
                         params={
                             "keyword": keyword,
                             "offset": offset,
                             "count": count,
                         })

    # ==================== 维度3：带货电商（星图） ====================

    def get_xingtu_promotion_cards(self, sec_user_id: str,
                                   page: int = 1,
                                   page_size: int = 20) -> dict:
        """
        获取星图推广卡片/带货商品数据
        端点: GET /api/v1/douyin/xingtu/fetch_promotion_card_list
        注意：需要开通星图(Xingtu)相关权限，否则返回 403/404
        """
        return self._get(
            "/api/v1/douyin/xingtu/fetch_promotion_card_list",
            params={
                "sec_user_id": sec_user_id,
                "page": page,
                "page_size": page_size,
            },
        )

    # ==================== 维度4：Dou+投放数据 ====================

    def get_douplus_promotable_items(self, cookie: str = "",
                                     page: int = 0,
                                     page_size: int = 20) -> dict:
        """
        获取 Dou+ 可推广作品列表（含消耗/播放/互动数据）
        端点: POST /api/v1/douyin/douplus/fetch_promotable_item_list
        需要：抖音用户 Cookie（从浏览器复制）
        """
        ck = cookie or self.cookie
        headers = {"Cookie": ck} if ck else {}
        return self._post(
            "/api/v1/douyin/douplus/fetch_promotable_item_list",
            json_data={"page": page, "page_size": page_size},
            extra_headers=headers,
        )

    def get_douplus_video_ranking(self, cookie: str = "",
                                   item_type: int = 2,
                                   sort_type: int = 1,
                                   page: int = 0,
                                   page_size: int = 20) -> dict:
        """
        获取 Dou+ 视频排行榜（按消耗/播放等排序）
        端点: POST /api/v1/douyin/douplus/fetch_video_ranking
        需要：抖音用户 Cookie
        参数说明:
          item_type: 2=视频
          sort_type: 1=消耗降序, 2=播放量降序, 3=点赞数降序
        """
        ck = cookie or self.cookie
        headers = {"Cookie": ck} if ck else {}
        return self._post(
            "/api/v1/douyin/douplus/fetch_video_ranking",
            json_data={
                "item_type": item_type,
                "sort_type": sort_type,
                "page": page,
                "page_size": page_size,
            },
            extra_headers=headers,
        )

    # ==================== 工具方法 ====================

    def check_balance(self) -> dict:
        """查询 TikHub 账户余额"""
        return self._get("/api/v1/tikhub/user/get_user_info")


# ==================== 数据解析工具 ====================

def _payload(raw: dict) -> dict:
    """
    解包 TikHub 响应信封，返回最内层业务 dict。
    兼容两种形态：
      A) 资料接口:  raw["data"] = { "data": {用户字段...}, "extra", "status_code" }
         → 返回 raw["data"]["data"]（用户平铺字段）
      B) 作品接口:  raw["data"] = { "aweme_list":[...], "has_more", "max_cursor", ... }
         → 返回 raw["data"]（本身就是业务 dict）
    """
    if not isinstance(raw, dict):
        return {}
    d = raw.get("data")
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get("data"), dict) and "nickname" not in d:
        return d["data"]
    return d


def extract_profile(raw: dict) -> dict | None:
    """从 API 返回中提取结构化的用户资料"""
    user = _payload(raw)
    uid = user.get("uid") or user.get("id")
    if not uid:
        return None
    fi = user.get("follow_info") or {}
    return {
        "uid": uid,
        "sec_uid": user.get("sec_uid"),
        "unique_id": user.get("unique_id", ""),
        "nickname": user.get("nickname", "未知"),
        "signature": user.get("signature", ""),
        "avatar": (user.get("avatar_thumb", {}) or {}).get("url_list", [""])[0],
        "follower_count": fi.get("follower_count", 0) or user.get("follower_count", 0),
        "following_count": fi.get("following_count", 0) or user.get("following_count", 0),
        "total_favorited": user.get("total_favorited", 0),
        "aweme_count": user.get("aweme_count", 0),
        "verification_type": 1 if user.get("verified") else 0,
        "raw": user,
    }


def extract_tags(desc: str, raw_item: dict | None = None) -> str:
    """
    提取作品标签：
      1. 从文案中的 #话题 提取
      2. 若 API 返回 video_tags 列表也一并纳入
    返回逗号拼接、去重保序的字符串
    """
    tags: list[str] = []
    if desc:
        tags += re.findall(r"#([^\s#]+)", desc)
    vt = (raw_item or {}).get("video_tags") or []
    for t in vt:
        name = t.get("tag_name") or t.get("name") or ""
        if name:
            tags.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return ",".join(out)


def extract_title(desc: str) -> str:
    """从文案中推导标题：取首行、去掉 #话题 部分"""
    if not desc:
        return ""
    first_line = desc.split("\n", 1)[0]
    title = re.split(r"#", first_line)[0].strip()
    return title


def extract_videos(raw: dict) -> list[dict]:
    """从 API 返回中提取视频列表（含标题/标签/完整文案/互动数据/封面）"""
    body = _payload(raw)
    aweme_list = body.get("aweme_list", [])
    videos = []
    for item in aweme_list:
        stats = item.get("statistics", {})
        desc = item.get("desc") or ""
        # 封面图：video.cover.url_list[0]（仅首个清晰图）
        video = item.get("video") or {}
        cover_obj = video.get("cover") if isinstance(video, dict) else None
        cover_list = (cover_obj or {}).get("url_list", []) if isinstance(cover_obj, dict) else []
        cover_url = cover_list[0] if cover_list else ""
        # 标签：优先取 text_extra 中的话题名，再补文案里的 #话题
        text_extra = item.get("text_extra") or []
        te_tags = [t.get("hashtag_name", "") for t in text_extra
                   if t.get("hashtag_name")]
        tag_str = extract_tags(desc, item)
        for t in te_tags:
            if t not in tag_str:
                tag_str = (tag_str + "," + t) if tag_str else t
        videos.append({
            "aweme_id": item.get("aweme_id", ""),
            "desc": desc,                       # 完整文案（不截断，用于差异对比）
            "title": extract_title(desc),      # 标题
            "tags": tag_str,                   # 标签（#话题 + text_extra 话题）
            "create_time": item.get("create_time", 0),
            "cover": cover_url,                # 封面图 URL
            "play_count": stats.get("play_count", 0),
            "digg_count": stats.get("digg_count", 0),
            "comment_count": stats.get("comment_count", 0),
            "share_count": stats.get("share_count", 0),
            "collect_count": stats.get("collect_count", 0),
        })
    return videos


def format_number(n: int) -> str:
    """格式化数字为可读形式"""
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


def format_timestamp(ts: int) -> str:
    """Unix 时间戳转中文日期"""
    if not ts:
        return "-"
    try:
        dt = datetime.fromtimestamp(ts, tz=CST)
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, OSError):
        return "-"
