"""
抖音账号监控配置文件

使用方式：
  1. 复制此文件为 config_local.py（已在 .gitignore 中）
  2. 填入你的 TikHub API Key 和要监控的账号
  3. 运行 python monitor.py

获取 API Key: https://user.tikhub.io → API Token → 创建新 Token

Dou+ Cookie 获取方式：
  1. 浏览器打开 https://creator.douyin.com 并登录
  2. F12 → Application → Cookies → 复制完整 Cookie 字符串
  3. 粘贴到下方 DOUPLUS_COOKIE
"""

# ============ TikHub API ============
API_KEY = ""              # 必填：TikHub API Token (Bearer token)
BASE_URL = "https://api.tikhub.dev"   # 国内用 .dev，海外用 .io

# ============ Dou+ Cookie（可选）============
# 从 creator.douyin.com 的浏览器 Cookie 中复制
DOUPLUS_COOKIE = ""

# ============ 监控账号列表 ============
# 每个账号支持两种标识方式：
#   - uid:       MS4wLjABAAAA... 格式（优先使用，最稳定）
#   - unique_id: 抖音号/昵称（会先通过搜索解析为 uid）
# 原始 31 个 UID（去重后 30 个唯一账号，用户 2026-08-26 提供）
_RAW_UIDS = [
    "397396233431257","7650684889516180529","3049374778393848","7638433940257489978",
    "1224222226253568","2939458067636336","7675642921655567397","7674544304131425329",
    "7493779785803007036","2156606405215895","1694786943199561","3762968190780163",
    "1716801736283996","7660691145656239153","2574399090487555","1096648367808554",
    "7629528523569693745","7676013645696123963","2697517525905482","604067175866235",
    "1325344306246316","7668478121516123194","2456776614359369","1083498019428832",
    "7662902822904562746","3014201962932036","7650764311963681841","2156606405215895",
    "2830555776298372","7638433940257489978","2983435520719572","3313257525808732",
]
# 去重 + 转为 MONITOR_ACCOUNTS 格式（name 后续通过 profile 接口自动填充昵称）
_UNIQUE_UIDS = list(dict.fromkeys(_RAW_UIDS))  # 保持顺序去重
MONITOR_ACCOUNTS = [{"name": f"达人_{i+1:02d}", "uid": u, "unique_id": "", "tags": []} for i, u in enumerate(_UNIQUE_UIDS)]

# ============ 监控维度开关 ============
ENABLE_FANS = True          # 维度1：粉丝与增长
ENABLE_VIDEOS = True        # 维度2：作品数据
ENABLE_ECOMMERCE = True     # 维度3：带货电商（星图）
ENABLE_DOUPlus = False      # 维度4：Dou+投放（需要Cookie）

# ============ 作品采集设置 ============
VIDEO_MAX_COUNT = 10        # 每个账号最多采集最近 N 条视频

# ============ 数据存储 ============
DATA_DIR = "./data"         # SQLite + CSV 存储目录
DB_NAME = "douyin_monitor.db"

# ============ 报告设置 ============
REPORT_DIR = "./reports"    # 报告输出目录
REPORT_TITLE = "抖音账号监控日报"
