#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音账号监控 —— 本地可视化操作面板

功能（全部本地运行，密钥绝不离开本机）：
  1. 账号管理：网页里输入 UID 即可「新增 / 移除」监控账号（写入 accounts.json）
  2. 立即刷新：一键触发「全量抓取 + 重建看板」，后台执行并实时显示日志
  3. 打开看板：直接在内嵌页查看 deploy/index.html
  4. 配置状态：显示 API Key / Cookie 是否已配置（绝不显示具体值）

运行：python panel.py   然后浏览器打开 http://127.0.0.1:5000
注意：仅监听 127.0.0.1（本机），不会暴露到局域网/公网。
"""
import os
import sys
import json
import time
import sqlite3
import threading
import subprocess
from datetime import datetime

from flask import Flask, request, redirect, url_for, send_file, jsonify, Response

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from accounts import load_accounts, add_account, remove_account, get_nickname

app = Flask(__name__)

# ---------------- 刷新状态（内存，单进程）----------------
_refresh = {
    "running": False,
    "done": False,
    "log": "",
    "started_at": "",
    "finished_at": "",
}


def _douyin_url(uid):
    """尽力从 snapshots.raw_profile 取 sec_uid 生成主页链接；取不到则用搜索页。"""
    try:
        db = os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db")
        if os.path.exists(db):
            con = sqlite3.connect(db)
            row = con.execute(
                "SELECT raw_profile FROM snapshots WHERE account_uid=? "
                "ORDER BY captured_at DESC LIMIT 1", (uid,)
            ).fetchone()
            con.close()
            if row and row[0]:
                prof = json.loads(row[0])
                sec = prof.get("sec_uid") or (prof.get("user", {}) or {}).get("sec_uid")
                if sec:
                    return f"https://www.douyin.com/user/{sec}", "主页"
    except Exception:
        pass
    return f"https://www.douyin.com/search/{uid}", "搜索"


def _config_status():
    """仅检查是否已配置，不返回任何密钥明文。"""
    def has_key(files, key):
        for f in files:
            p = os.path.join(SCRIPT_DIR, f)
            if not os.path.exists(p):
                p2 = os.path.join(os.path.dirname(SCRIPT_DIR), f)  # 兼容上级 douyin-monitor.env.txt
                if os.path.exists(p2):
                    p = p2
                else:
                    continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if line.strip().startswith(key) and "=" in line:
                            v = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if v:
                                return True
            except Exception:
                pass
        return False

    files = [".env", "douyin-monitor.env.txt"]
    return {
        "api_key": has_key(files, "TIKHUB_API_KEY"),
        "cookie": has_key(files, "DOUYIN_COOKIE"),
    }


def _last_fetch_date():
    try:
        db = os.path.join(SCRIPT_DIR, "data", "douyin_monitor.db")
        if os.path.exists(db):
            con = sqlite3.connect(db)
            row = con.execute("SELECT MAX(stat_date) FROM video_daily").fetchone()
            con.close()
            return row[0] if row and row[0] else "（暂无数据）"
    except Exception:
        pass
    return "（暂无数据）"


def _run_refresh():
    global _refresh
    _refresh["running"] = True
    _refresh["done"] = False
    _refresh["log"] = ""
    _refresh["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _refresh["finished_at"] = ""

    def log(line):
        _refresh["log"] += line + "\n"

    try:
        for script in ["fetch_all_accounts.py", "build_consolidated.py"]:
            log(f"▶ 执行 {script}  @ {datetime.now().strftime('%H:%M:%S')}")
            proc = subprocess.run(
                [sys.executable, script],
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            for ln in out.strip().splitlines():
                log(ln)
            log(f"✓ {script} 退出码 {proc.returncode}\n")
    except Exception as e:
        log(f"❌ 刷新失败：{e}")
    _refresh["running"] = False
    _refresh["done"] = True
    _refresh["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 页面 ----------------
PAGE_CSS = """
:root{--bg:#f4f6fa;--card:#fff;--line:#e6e9ef;--text:#1f2329;--muted:#6b7280;
       --blue:#2f6bff;--green:#1b8a3a;--red:#d23f3f;--amber:#b7791f;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);
     color:var(--text);padding:28px;line-height:1.5}
.wrap{max-width:980px;margin:0 auto}
h1{font-size:22px;margin-bottom:4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:18px}
.card h2{font-size:15px;margin-bottom:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:200px;padding:9px 11px;border:1px solid var(--line);
       border-radius:8px;font-size:14px}
button{cursor:pointer;border:none;border-radius:8px;padding:9px 16px;font-size:14px;
       background:var(--blue);color:#fff;font-weight:600}
button.ghost{background:#eef2ff;color:var(--blue)}
button.danger{background:#fdecec;color:var(--red)}
button:hover{filter:brightness(.96)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
a.act{color:var(--blue);text-decoration:none;margin-right:10px}
a.act:hover{text-decoration:underline}
.badge{display:inline-block;font-size:12px;padding:2px 9px;border-radius:10px;font-weight:600}
.b-ok{background:#e8f5e9;color:var(--green)}
.b-no{background:#fdecea;color:var(--red)}
.b-amber{background:#fff4e0;color:var(--amber)}
.muted{color:var(--muted);font-size:13px}
pre{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:10px;max-height:340px;
    overflow:auto;font-size:12.5px;white-space:pre-wrap;font-family:Consolas,Menlo,monospace}
.empty{color:var(--muted);padding:18px;text-align:center}
.meta{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:6px}
.meta div{font-size:13px}
.meta b{font-size:16px}
iframe{border:1px solid var(--line);border-radius:10px;width:100%;height:560px;background:#fff}
"""


def _render_page():
    accounts = load_accounts()
    cfg = _config_status()
    last = _last_fetch_date()
    rows = []
    for a in accounts:
        uid = a["uid"]
        url, label = _douyin_url(uid)
        rows.append(
            f"<tr><td>{a.get('nickname') or '<span class=muted>—</span>'}</td>"
            f"<td><code>{uid}</code></td>"
            f"<td><a class=act href='{url}' target=_blank>↗ 在抖音打开</a></td>"
            f"<td><form method=post action='/remove/{uid}' onsubmit='return confirm(\"确认移除该账号？历史数据仍保留\")'>"
            f"<button class=danger type=submit>移除</button></form></td></tr>"
        )
    rows_html = "\n".join(rows) if rows else "<tr><td colspan=4 class=empty>暂无监控账号，请在下方添加</td></tr>"

    cfg_html = (
        f"API Key：<span class='badge {'b-ok' if cfg['api_key'] else 'b-no'}'>"
        f"{'已配置' if cfg['api_key'] else '未配置'}</span>&nbsp;&nbsp;"
        f"Cookie：<span class='badge {'b-ok' if cfg['cookie'] else 'b-no'}'>"
        f"{'已配置' if cfg['cookie'] else '未配置'}</span>"
    )

    refresh_block = ""
    if _refresh["running"]:
        refresh_block = (
            "<div class='card'><h2>🔄 刷新中…（日志自动滚动）</h2>"
            "<pre id=log>" + _refresh["log"] + "</pre></div>"
        )
    elif _refresh["done"]:
        refresh_block = (
            f"<div class='card'><h2>✅ 上次刷新完成 · 开始 {_refresh['started_at']} · 结束 {_refresh['finished_at']}</h2>"
            "<pre>" + _refresh["log"] + "</pre></div>"
        )

    html = f"""<!DOCTYPE html><html lang=zh-CN><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>抖音监控 · 操作面板</title><style>{PAGE_CSS}</style>
<script>
function poll(){{
  fetch('/refresh_status').then(r=>r.json()).then(d=>{{
    if(d.running){{ document.getElementById('log').textContent=d.log;
      document.getElementById('log').scrollTop=document.getElementById('log').scrollHeight;
      setTimeout(poll,1500); }}
  }}).catch(()=>{{}});
}}
window.addEventListener('load',poll);
</script></head><body><div class=wrap>
<h1>抖音账号监控 · 操作面板</h1>
<div class=sub>本地运行 · 仅监听 127.0.0.1 · 密钥不出本机</div>

<div class=card>
  <div class=meta>
    <div>监控账号 <b>{len(accounts)}</b></div>
    <div>上次抓取 <b>{last}</b></div>
    <div>{cfg_html}</div>
  </div>
  <div class=row style="margin-top:10px">
    <a class=act href="/dashboard" target=_blank><button class=ghost>📊 打开看板</button></a>
    <form method=post action="/refresh" style="display:inline">
      <button type=submit>🔄 立即刷新（抓取+重建看板）</button>
    </form>
  </div>
</div>

{refresh_block}

<div class=card>
  <h2>➕ 新增监控账号</h2>
  <form method=post action="/add">
    <div class=row>
      <input type=text name=uid placeholder="抖音账号 UID（必填）" required>
      <input type=text name=nickname placeholder="昵称（可选）">
      <button type=submit>添加</button>
    </div>
  </form>
  <p class=muted style="margin-top:8px">提示：UID 是抖音账号的数字 ID；新增后点「立即刷新」才会抓取数据，或等每日 18:00 自动任务。</p>
</div>

<div class=card>
  <h2>📋 当前监控账号（{len(accounts)}）</h2>
  <table><thead><tr><th>昵称</th><th>UID</th><th>抖音</th><th>操作</th></tr></thead>
  <tbody>{rows_html}</tbody></table>
</div>

<div class=card>
  <h2>📊 看板预览</h2>
  <iframe src="/dashboard"></iframe>
</div>
</div></body></html>"""
    return html


@app.route("/")
def index():
    return Response(_render_page(), mimetype="text/html")


def _get_field(name, default=""):
    """手动解析原始 body（兼容 curl 与浏览器提交的 UTF-8 / 百分号编码），避免 request.form 解码乱码。"""
    try:
        from urllib.parse import unquote_plus
        body = request.get_data(as_text=True) or ""
        for pair in body.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if unquote_plus(k) == name:
                    return unquote_plus(v)
    except Exception:
        pass
    v = request.args.get(name)
    if v is not None:
        return v
    return default


@app.route("/add", methods=["POST"])
def add():
    uid = (_get_field("uid") or "").strip()
    nickname = (_get_field("nickname") or "").strip()
    if uid:
        add_account(uid, nickname)
    return redirect(url_for("index"))


@app.route("/remove/<uid>", methods=["POST"])
def remove(uid):
    remove_account(uid)
    return redirect(url_for("index"))


@app.route("/refresh", methods=["POST"])
def refresh():
    if not _refresh["running"]:
        threading.Thread(target=_run_refresh, daemon=True).start()
    return redirect(url_for("index"))


@app.route("/refresh_status")
def refresh_status():
    return jsonify({
        "running": _refresh["running"],
        "done": _refresh["done"],
        "log": _refresh["log"],
        "started_at": _refresh["started_at"],
        "finished_at": _refresh["finished_at"],
    })


@app.route("/dashboard")
def dashboard():
    p = os.path.join(SCRIPT_DIR, "deploy", "index.html")
    if os.path.exists(p):
        return send_file(p, mimetype="text/html")
    return "<p style='padding:20px'>尚未生成看板，请先点「立即刷新」。</p>", 200


if __name__ == "__main__":
    print("▶ 操作面板已启动：http://127.0.0.1:5000  （Ctrl+C 退出）")
    app.run(host="127.0.0.1", port=5000, debug=False)
