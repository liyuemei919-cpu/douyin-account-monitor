# 抖音账号监控系统（Douyin Account Monitor）

监控多个抖音公开账号的粉丝增长、作品数量/数据变化、文案与标签变化，自动生成单文件 HTML 看板，支持多账号总览、逐日对比、删除/隐藏视频保留、Excel 导出。

数据来源：[TikHub](https://tikhub.io) 第三方数据平台 API。

---

## ⚠️ 隐私与安全（重要）

**本仓库不包含任何个人密钥。** 所有敏感信息只存在于你本地的 `.env` 文件：

- `TIKHUB_API_KEY` —— TikHub API Token
- `DOUYIN_COOKIE` —— 抖音网页版登录 Cookie（用于解锁被登录态挡住的作品）

`.env` 已被 `.gitignore` 强制忽略，**永远不会被提交到 GitHub**。请勿手动 `git add .env`。
公开的 `deploy/index.html` 看板仅含已抓取的公开作品数据，不含任何密钥、Cookie 或个人登录信息。

> 部署/分享前请再次确认：仓库中不存在 `.env`、任何 `*.env.txt`、或含密钥的日志文件。

---

## 目录结构

```
douyin-monitor/
├── panel.py                # 本地 Web 操作面板（账号增删 / 立即刷新 / 看板）
├── accounts.json           # 监控账号列表（单一数据源，仅含公开 UID，可入库）
├── accounts.py             # accounts.json 的读写模块
├── fetch_all_accounts.py   # 入口1：按 accounts.json 全量抓取并入库
├── build_consolidated.py   # 入口2：从数据库生成 deploy/index.html 看板
├── tikhub_client.py        # TikHub API 封装（资料/作品/视频详情/Dou+）
├── build_single_account.py # 单账号抓取 + 入库逻辑 + .env 加载
├── monitor.py              # 数据库读写（video_daily / snapshots）
├── config.py               # 开关配置（维度、Cookie 等）
├── data/                   # SQLite 数据库（已 gitignore，可重新生成）
├── deploy/
│   └── index.html          # 生成的看板（可直接用浏览器打开）
├── requirements.txt        # Flask 依赖
├── .env.example            # 密钥模板，复制为 .env 后填值
└── .gitignore
```

---

## 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt   # 含 flask + requests
```

### 2. 配置密钥
```bash
cp .env.example .env
```
编辑 `.env`，填入：
```
TIKHUB_API_KEY=你的TikHub_Api_Token
DOUYIN_COOKIE=sessionid=...; ttwid=...; odin_tt=...   # 可选，用于解锁全量作品
```
> Cookie 会自动剔除超长指纹/追踪字段，仅保留鉴权必需项，避免触发抖音 WAF 403。
> 不填 Cookie 也能跑，但部分账号可能被登录态限制（作品数返回 0/被截断）。

### 3. 抓取数据
```bash
python fetch_all_accounts.py
```

### 4. 生成看板
```bash
python build_consolidated.py
# 产出 deploy/index.html，用浏览器直接打开即可
```

---

## 查看看板

直接用浏览器打开 `deploy/index.html`（单文件、内联 CSS/JS，可离线使用）。支持：
- 账号总览矩阵（可按粉丝/作品数/变化筛选）
- 单账号下钻明细（4 个 Δ：点赞/评论/转发/收藏 + 变化列）
- 全部作品汇总（多维筛选 + 导出 Excel）
- 可选对比日期（与历史统计日逐日对比）
- 删除/隐藏视频置灰保留 + 「查看每日」逐日数据

---

## 可视化操作面板（推荐）

不想记命令？用本地 Web 面板点点鼠标即可：

```bash
python panel.py
# 浏览器打开 http://127.0.0.1:5000
```

面板功能（全部本地运行，**密钥绝不离开本机**，仅监听 127.0.0.1）：
- **账号管理**：输入 UID 即可「新增 / 移除」监控账号（写入 `accounts.json`，无需改代码）
- **立即刷新**：一键触发「全量抓取 + 重建看板」，后台执行并实时显示日志
- **打开看板**：面板内直接预览 `deploy/index.html`
- **配置状态**：显示 API Key / Cookie 是否已配置（**绝不显示具体值**）

> 端口占用时，改 `panel.py` 末尾 `app.run(port=5000)` 的端口即可。
> 新增账号后点「立即刷新」才会抓取数据；不操作也会在每日 18:00 自动任务时抓取。

## 配置监控账号

监控列表的**单一数据源是 `accounts.json`**（仅含公开 UID，已入库）。推荐用上面的操作面板增删；也可直接编辑 `accounts.json`：

```json
[
  { "uid": "2697552638795803", "nickname": "小杏福" },
  { "uid": "7650684889516180529", "nickname": "發財喵" }
]
```

`fetch_all_accounts.py` 与 `build_consolidated.py` 都读取该文件；编辑后无需改任何脚本代码。

---

## 已知限制

- 抖音公开 Web 接口**不返回播放量**（`play_count` 恒为 0），看板对播放量/互动率优雅降级为「—」。
- 无登录 Cookie 时，部分账号会被「登录态」限制，作品列表可能为空或被截断；填入 `DOUYIN_COOKIE` 可解锁。
- `profile.aweme_count` 常返回 0，真实作品总数以实际分页统计 / 历史 DB 为准。

---

## 免责声明

本工具仅用于监控**公开可见**的抖音数据，数据归各账号所有者所有。请遵守 TikHub 与抖音的服务条款，勿将抓取数据用于侵权或违规用途。
