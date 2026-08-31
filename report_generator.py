"""
HTML 报告生成器（v3：多账号仪表盘 + 作品逐日累计）

报告结构：
  - 顶部悬浮导航：一排账号名可点击跳转 + 报告日期
  - 每个账号独立一节（account-block），内含：
      · 账号概览卡片（粉丝/关注/获赞 + 粉丝走势 sparkline）
      · 🎯 作品变化追踪（最新一天 vs 上一天：新增/删除隐藏/文案变化/标签变化/数据增量）
      · 📈 作品逐日累计分析（每个作品：首发日、状态、最新互动、累计增量、文案/标签变化、点赞走势）
      · 带货电商 / Dou+ 投放（如有）

使用纯 HTML + 内联 CSS + 内联 SVG sparkline，无外部依赖（可离线打开）。
"""

import os
import json
import html
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def _fmt(n: int) -> str:
    """格式化数字"""
    if n is None:
        return "0"
    n = int(n)
    if n >= 100000000:
        return f"{n/100000000:.1f}亿"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


def _esc(s) -> str:
    """HTML 转义，避免文案中的 < > & 破坏页面"""
    return html.escape(str(s if s is not None else ""))


def _trunc(s: str, n: int = 40) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + "…"


def _ts(ts) -> str:
    """Unix 时间戳转中文日期"""
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts, tz=CST).strftime("%m-%d %H:%M")
    except (ValueError, OSError, TypeError):
        return "—"


def _delta_cell(delta) -> str:
    """互动数据增量单元格（涨红跌绿）"""
    if not delta:
        return '<span style="color:#bbb">—</span>'
    delta = int(delta)
    sign = "+" if delta > 0 else ""
    color = "#e74c3c" if delta > 0 else "#27ae60"
    arrow = "▲" if delta > 0 else "▼"
    return (f'<span style="color:{color};font-weight:600;font-size:12px">'
            f'{arrow}{sign}{_fmt(abs(delta))}</span>')


def _delta_str(current: int, previous: int) -> str:
    """计算变化量并返回带颜色的字符串"""
    if not previous:
        return '<span style="color:#888">—</span>'
    delta = current - previous
    sign = "+" if delta > 0 else ""
    color = "#e74c3c" if delta > 0 else "#27ae60"
    return f'<span style="color:{color};font-weight:600">{sign}{_fmt(delta)}</span>'


def _sparkline(vals: list, color: str = "#667eea", w: int = 90, h: int = 26) -> str:
    """内联 SVG 迷你走势图（无依赖）"""
    vals = [int(v or 0) for v in vals]
    if len(vals) < 2:
        return '<span style="color:#bbb">—</span>'
    mn, mx = min(vals), max(vals)
    if mx == mn:
        pts = " ".join(f"{i * (w / (len(vals) - 1)):.1f},{h / 2:.1f}"
                       for i in range(len(vals)))
    else:
        pts = " ".join(
            f"{i * (w / (len(vals) - 1)):.1f},"
            f"{h - (v - mn) / (mx - mn) * (h - 4) - 2:.1f}"
            for i, v in enumerate(vals)
        )
    return (f'<svg width="{w}" height="{h}" style="vertical-align:middle">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
            f'points="{pts}"/></svg>')


# ============ 作品变化追踪（最新一天 vs 上一天）============

def _build_diff_section(r: dict) -> str:
    """
    单个账号的「作品变化追踪」板块（告警视角）：
      顶部汇总徽章 + 逐条变化明细（删除/隐藏、文案前后对比、标签前后对比、互动增量）
    """
    cum = r.get("cumulative") or {}
    wd = cum.get("diff")
    if not wd:
        return ""
    summary = wd.get("summary", {})
    changes = wd.get("changes", [])
    name = r.get("name", "")

    if not changes:
        badges = '<span class="badge ok">✅ 与上次监控相比无变化</span>'
    else:
        parts = []
        if summary.get("new"):
            parts.append(f'<span class="badge new">🆕 新增 {summary["new"]}</span>')
        if summary.get("removed"):
            parts.append(f'<span class="badge removed">⚠️ 删除/隐藏 {summary["removed"]}</span>')
        if summary.get("caption_changed"):
            parts.append(f'<span class="badge caption">✏️ 文案变化 {summary["caption_changed"]}</span>')
        if summary.get("tags_changed"):
            parts.append(f'<span class="badge tags">🏷️ 标签变化 {summary["tags_changed"]}</span>')
        if summary.get("metric_changed"):
            parts.append(f'<span class="badge metric">📈 数据增量 {summary["metric_changed"]}</span>')
        badges = "".join(parts)

    rows = ""
    for ch in changes:
        if ch["type"] == "removed":
            status = '<span class="badge removed">⚠️ 删除/隐藏</span>'
            title = _esc(ch.get("title") or "(无标题)")
            caption_html = f'<span class="old-text">上次：{_esc(ch.get("desc", ""))}</span>'
            tags_html = f'<span class="old-text">{_esc(ch.get("tags") or "—")}</span>'
            m = ch.get("metrics", {})
            metrics_html = (f'❤️{_fmt(m.get("digg_count", 0))} · '
                            f'⭐{_fmt(m.get("collect_count", 0))} · '
                            f'↗️{_fmt(m.get("share_count", 0))}')
            note = '<div class="note warn">📌 上次监控仍存在，本次未找到 → 疑似删除 / 隐藏 / 设为私密</div>'
        elif ch["type"] == "new":
            status = '<span class="badge new">🆕 新增</span>'
            title = _esc(ch.get("title") or "(无标题)")
            caption_html = f'<span class="new-text">{_esc(ch.get("desc", ""))}</span>'
            tags_html = f'<span class="new-text">{_esc(ch.get("tags") or "—")}</span>'
            m = ch.get("metrics", {})
            metrics_html = (f'❤️{_fmt(m.get("digg_count", 0))} · '
                            f'⭐{_fmt(m.get("collect_count", 0))} · '
                            f'↗️{_fmt(m.get("share_count", 0))}')
            note = '<div class="note ok">📌 本次新增发布的作品</div>'
        else:  # changed
            labels = []
            if ch.get("caption_changed"):
                labels.append("✏️文案")
            if ch.get("tags_changed"):
                labels.append("🏷️标签")
            if ch.get("metric_deltas"):
                labels.append("📈数据")
            status = f'<span class="badge changed">{" ".join(labels)}</span>'
            title = _esc(ch.get("title") or "(无标题)")
            if ch.get("caption_changed"):
                caption_html = (f'<span class="old-text">前：{_esc(ch.get("old_desc", ""))}</span>'
                                f'<br><span class="new-text">后：{_esc(ch.get("new_desc", ""))}</span>')
            else:
                caption_html = f'<span>{_esc(ch.get("new_desc", ""))}</span>'
            if ch.get("tags_changed"):
                tags_html = (f'<span class="old-text">{_esc(ch.get("old_tags") or "—")}</span>'
                             f'<br><span class="new-text">{_esc(ch.get("new_tags") or "—")}</span>')
            else:
                tags_html = f'<span>{_esc(ch.get("new_tags") or "—")}</span>'
            cm = ch.get("current_metrics", {})
            md = ch.get("metric_deltas", {})
            metrics_html = (
                f'❤️{_fmt(cm.get("digg_count", 0))} {_delta_cell(md.get("digg_count"))}<br>'
                f'⭐{_fmt(cm.get("collect_count", 0))} {_delta_cell(md.get("collect_count"))}<br>'
                f'↗️{_fmt(cm.get("share_count", 0))} {_delta_cell(md.get("share_count"))}'
            )
            note = ""

        rows += f"""
        <tr class="diff-row {ch['type']}">
          <td class="status-cell">{status}</td>
          <td class="title-cell">{title}</td>
          <td class="caption-cell">{caption_html}</td>
          <td class="tags-cell">{tags_html}</td>
          <td class="metrics-cell">{metrics_html}</td>
        </tr>
        {('<tr><td colspan="5">' + note + '</td></tr>') if note else ''}
        """

    return f"""
    <div class="section diff-section">
      <h3>🎯 {name} — 作品变化追踪（最新一天 vs 上一天）</h3>
      <div class="diff-badges">{badges}</div>
      <table class="diff-table">
        <thead><tr>
          <th>状态</th><th>标题</th><th>文案（变化对比）</th><th>标签</th><th>互动数据(点赞/收藏/转发)</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


# ============ 作品逐日累计分析 ============

def _build_cumulative_section(r: dict) -> str:
    """单个账号的「作品逐日累计」板块：每个作品的完整时间序列与变化历史"""
    cum = r.get("cumulative")
    if not cum or not cum.get("works"):
        return ""
    name = r.get("name", "")
    works = cum["works"]
    latest = cum.get("latest_date", "")

    rows = ""
    for w in works:
        lm = w["latest"]
        growth = w.get("growth", {})
        if w["status"] == "removed":
            status_badge = '<span class="badge removed">⚠️ 删除/隐藏</span>'
        else:
            status_badge = '<span class="badge ok">● 在更</span>'
        caption_flag = f'✏️×{w["caption_changes"]}' if w["caption_changes"] else "—"
        tag_flag = f'🏷️×{w["tag_changes"]}' if w["tag_changes"] else "—"
        spark = _sparkline([row.get("digg_count", 0) for row in w["series"]])
        rows += f"""
        <tr class="{'removed-row' if w['status'] == 'removed' else ''}">
          <td class="wk-title">{_esc(w.get('title') or '(无标题)')}<br>
              <span class="wk-sub">{_trunc(lm.get('desc', ''), 28)}</span></td>
          <td>{w['first_date']}</td>
          <td>{status_badge}</td>
          <td>{_fmt(lm.get('play_count', 0))}</td>
          <td style="color:#e74c3c">{_fmt(lm.get('digg_count', 0))}</td>
          <td>{_fmt(lm.get('collect_count', 0))}</td>
          <td>{_fmt(lm.get('share_count', 0))}</td>
          <td>{_delta_cell(growth.get('digg_count'))}</td>
          <td class="wk-flag">{caption_flag}<br>{tag_flag}</td>
          <td>{spark}</td>
        </tr>
        """

    # 文案/标签变化历史（累计所有日期）
    all_events = []
    for w in works:
        for e in w.get("caption_events", []):
            all_events.append((e["date"], w.get("title", ""), "文案", e["old"], e["new"]))
        for e in w.get("tag_events", []):
            all_events.append((e["date"], w.get("title", ""), "标签", e["old"], e["new"]))
    events_html = ""
    if all_events:
        ev_rows = ""
        for date, title, kind, old, new in sorted(all_events, key=lambda x: x[0]):
            ev_rows += f"""
            <tr>
              <td>{date}</td><td>{_esc(title)}</td><td>{kind}</td>
              <td class="caption-cell"><span class="old-text">{_esc(old) or '—'}</span>
                  → <span class="new-text">{_esc(new) or '—'}</span></td>
            </tr>"""
        events_html = f"""
        <div class="subsection">
          <h4>📝 文案 / 标签变化历史（累计）</h4>
          <table class="data-table">
            <thead><tr><th>日期</th><th>作品</th><th>类型</th><th>变化（前 → 后）</th></tr></thead>
            <tbody>{ev_rows}</tbody>
          </table>
        </div>
        """

    return f"""
    <div class="section cum-section">
      <h3>📈 {name} — 作品逐日累计分析（截至 {latest}）</h3>
      <table class="data-table cum-table">
        <thead><tr>
          <th>作品</th><th>首发</th><th>状态</th><th>▶️播放</th><th>❤️点赞</th>
          <th>⭐收藏</th><th>↗️转发</th><th>累计点赞增量</th><th>文案/标签变化</th><th>点赞走势</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
      {events_html}
    </div>
    """


# ============ 账号概览卡片（含粉丝走势）============

def _build_account_card(r: dict, db) -> str:
    p = r.get("profile") or {}
    uid = r.get("uid", "—")
    name = r.get("name", "未知")
    tags = " ".join(f'<span class="tag">{t}</span>' for t in r.get("tags", []))
    errors = r.get("errors", [])
    error_html = ('<div class="errors">' + "<br>".join(f"⚠️ {e}" for e in errors) + "</div>") if errors else ""

    prev_follower = 0
    follower_spark = ""
    if db and uid != "—":
        try:
            history = db.get_history(uid, days=30)
            if len(history) > 1:
                prev_follower = int(history[1]["follower_count"])
                follower_spark = _sparkline([h["follower_count"] for h in history], color="#667eea")
        except Exception:
            pass

    return f"""
    <div class="card">
      <div class="card-header">
        <div class="card-title"><h3>{name}</h3>{tags}</div>
        <span class="capture-time">📅 {r.get('captured_at', '')[:16]}</span>
      </div>
      {error_html}
      <div class="stats-grid">
        <div class="stat-item">
          <div class="stat-label">粉丝数</div>
          <div class="stat-value">{_fmt(p.get('follower_count', 0))}</div>
          <div class="stat-delta">{_delta_str(p.get('follower_count', 0), prev_follower)}</div>
          <div class="spark">{follower_spark}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">关注数</div>
          <div class="stat-value">{_fmt(p.get('following_count', 0))}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">总获赞</div>
          <div class="stat-value">{_fmt(p.get('total_favorited', 0))}</div>
        </div>
        <div class="stat-item">
          <div class="stat-label">作品数</div>
          <div class="stat-value">{p.get('aweme_count', 0)}</div>
        </div>
      </div>
    </div>
    """


# ============ Dou+ / 电商 单账号小节 ============

def _build_douplus_section(r: dict) -> str:
    dp = r.get("douplus")
    if not dp:
        return ""
    items = dp.get("promotable_items", [])
    total_consume = dp.get("total_consume", 0)
    rows = ""
    for item in items:
        rows += f"""
        <tr>
          <td>{_esc(item.get('desc', '—'))[:50]}</td>
          <td style="color:#e74c3c;font-weight:600">¥{item.get('total_consume', 0):,.2f}</td>
          <td>{_fmt(item.get('total_play', 0))}</td>
          <td>{_fmt(item.get('total_like', 0))}</td>
          <td>{_fmt(item.get('total_comment', 0))}</td>
          <td>{_fmt(item.get('total_share', 0))}</td>
        </tr>"""
    return f"""
    <div class="section">
      <h3>💰 {r.get('name', '')} — Dou+ 投放数据 (总消耗 ¥{total_consume:,.2f})</h3>
      <table class="data-table highlight-consume">
        <thead><tr><th>推广视频</th><th>💸 消耗(元)</th><th>▶️ 播放量</th>
          <th>❤️ 点赞</th><th>💬 评论</th><th>↗️ 转发</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def _build_ecommerce_section(r: dict) -> str:
    ec = r.get("ecommerce")
    if not ec:
        return ""
    cards = ec.get("promotion_cards", [])
    gmv = ec.get("total_gmv", 0)
    sales = ec.get("total_sales", 0)
    rows = ""
    for c in cards:
        rows += f"""
        <tr>
          <td>{_esc(c.get('title', '—'))[:40]}</td>
          <td style="color:#e74c3c;font-weight:600">¥{c.get('price', 0)}</td>
          <td>{c.get('sales_volume', 0):,}</td>
          <td>{c.get('commission_rate', 0)}%</td>
        </tr>"""
    return f"""
    <div class="section">
      <h3>🛒 {r.get('name', '')} — 带货商品 (GMV ¥{gmv:,.0f})</h3>
      <table class="data-table">
        <thead><tr><th>商品名称</th><th>价格</th><th>销量</th><th>佣金率</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


# ============ 主入口 ============

STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: #f5f7fa; color: #333; line-height: 1.6;
    padding: 0 24px 40px; max-width: 1200px; margin: 0 auto;
  }

  /* 顶部悬浮导航 */
  .topnav {
    position: sticky; top: 0; z-index: 100;
    background: #fff; border-bottom: 1px solid #eaeaea;
    padding: 10px 16px; margin: 0 -24px 20px;
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  }
  .nav-title { font-weight: 700; font-size: 15px; margin-right: 6px; }
  .nav-link {
    font-size: 13px; color: #667eea; text-decoration: none;
    padding: 4px 12px; background: #eef2ff; border-radius: 12px; white-space: nowrap;
  }
  .nav-link:hover { background: #667eea; color: #fff; }
  .nav-date { margin-left: auto; font-size: 12px; color: #999; }

  /* 头部 */
  .header {
    text-align: center; margin-bottom: 8px; padding: 28px 24px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 16px; color: white;
  }
  .header h1 { font-size: 26px; font-weight: 700; margin-bottom: 6px; }
  .header .subtitle { font-size: 14px; opacity: 0.85; }

  .account-block { margin-top: 28px; }
  .account-block + .account-block { border-top: 2px dashed #e3e8f0; padding-top: 8px; }

  /* 卡片 */
  .card {
    background: white; border-radius: 12px; padding: 22px; margin-bottom: 14px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
  .card-title h3 { font-size: 17px; font-weight: 600; display: inline; }
  .capture-time { font-size: 12px; opacity: 0.6; }
  .tag {
    display: inline-block; background: #eef2ff; color: #667eea;
    font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-left: 6px;
  }
  .errors {
    background: #fff5f5; border-left: 3px solid #e74c3c; padding: 8px 12px;
    margin: 10px 0; font-size: 13px; color: #c0392b; border-radius: 4px;
  }

  /* 统计网格 */
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; }
  .stat-item { text-align: center; padding: 14px 8px; background: #fafbfc; border-radius: 10px; }
  .stat-label { font-size: 12px; color: #888; margin-bottom: 4px; }
  .stat-value { font-size: 22px; font-weight: 700; color: #222; }
  .stat-delta { font-size: 12px; margin-top: 2px; }
  .spark { margin-top: 4px; }

  /* Section */
  .section { margin-top: 22px; }
  .section h3 {
    font-size: 17px; font-weight: 600; margin-bottom: 14px;
    padding-left: 10px; border-left: 4px solid #667eea;
  }
  .subsection { margin-top: 16px; }
  .subsection h4 { font-size: 14px; font-weight: 600; margin-bottom: 8px; color: #555; }

  /* 表格 */
  .data-table {
    width: 100%; border-collapse: collapse; font-size: 13px; background: white;
    border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }
  .data-table th {
    background: #f8f9fb; padding: 11px 12px; text-align: left; font-weight: 600;
    font-size: 12px; color: #555; border-bottom: 2px solid #eee; white-space: nowrap;
  }
  .data-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
  .data-table tr:hover { background: #fafbfc; }
  .video-desc { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* 作品变化追踪板块 */
  .diff-section { margin-top: 22px; }
  .diff-badges { margin-bottom: 14px; display: flex; flex-wrap: wrap; gap: 8px; }
  .badge { display: inline-block; font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 12px; }
  .badge.new { background: #e8f5e9; color: #2e7d32; }
  .badge.removed { background: #ffebee; color: #c62828; }
  .badge.caption { background: #fff8e1; color: #f57f17; }
  .badge.tags { background: #e3f2fd; color: #1565c0; }
  .badge.metric { background: #f3e5f5; color: #6a1b9a; }
  .badge.changed { background: #fff3e0; color: #e65100; }
  .badge.ok { background: #f1f8e9; color: #558b2f; }

  .diff-table { width: 100%; border-collapse: collapse; font-size: 13px; background: white;
    border-radius: 10px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
  .diff-table th {
    background: #f8f9fb; padding: 11px 12px; text-align: left; font-weight: 600;
    font-size: 12px; color: #555; border-bottom: 2px solid #eee; white-space: nowrap;
  }
  .diff-table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }
  .diff-row.removed { background: #fff5f5; }
  .diff-row.new { background: #f6fff7; }
  .diff-row.changed { background: #fffdf5; }
  .status-cell { white-space: nowrap; }
  .title-cell { font-weight: 600; max-width: 160px; }
  .caption-cell { max-width: 320px; line-height: 1.5; }
  .tags-cell { max-width: 140px; }
  .metrics-cell { white-space: nowrap; }
  .old-text { color: #c0392b; text-decoration: line-through; opacity: 0.8; }
  .new-text { color: #1e7d32; font-weight: 600; }
  .note { font-size: 12px; padding: 8px 12px; border-radius: 4px; }
  .note.warn { background: #fff5f5; border-left: 3px solid #e74c3c; color: #c0392b; }
  .note.ok { background: #f6fff7; border-left: 3px solid #27ae60; color: #1e7d32; }

  /* 累计表 */
  .cum-table td { font-size: 12.5px; }
  .wk-title { font-weight: 600; max-width: 200px; }
  .wk-sub { font-weight: 400; font-size: 11px; color: #999; }
  .wk-flag { white-space: nowrap; text-align: center; }
  .removed-row { background: #fff5f5; }

  /* 页脚 */
  .footer { text-align: center; margin-top: 36px; padding: 16px; font-size: 12px; color: #aaa; }
</style>
"""


def generate_report(results: list[dict], cfg: dict, db=None) -> str:
    """生成多账号仪表盘 HTML 报告"""
    now = datetime.now(CST)
    title = cfg.get("report_title", "抖音账号监控日报")

    # ---- 顶部导航 + 逐账号分节 ----
    nav_links = ""
    account_blocks = ""
    for i, r in enumerate(results):
        anchor = f"acc-{i}"
        name = r.get("name", f"账号{i+1}")
        nav_links += f'<a href="#{anchor}" class="nav-link">{_esc(name)}</a>'
        block = f"""
        <section id="{anchor}" class="account-block">
          {_build_account_card(r, db)}
          {_build_diff_section(r)}
          {_build_cumulative_section(r)}
          {_build_douplus_section(r)}
          {_build_ecommerce_section(r)}
        </section>
        """
        account_blocks += block

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — {now.strftime('%Y-%m-%d')}</title>
{STYLE}
</head>
<body>

<div class="topnav">
  <span class="nav-title">📊 {_esc(title)}</span>
  {nav_links}
  <span class="nav-date">生成于 {now.strftime('%Y-%m-%d %H:%M')} · 共 {len(results)} 个账号</span>
</div>

<div class="header">
  <h1>📊 {_esc(title)}</h1>
  <div class="subtitle">多账号仪表盘 · 作品逐日累计分析 · 数据来源 TikHub</div>
</div>

{account_blocks}

<div class="footer">
  抖音监控系统 v3.0 · 数据来源 TikHub (tikhub.io) · 自动生成报告
</div>

</body>
</html>"""

    return html


if __name__ == "__main__":
    # 独立运行自测
    demo_results = [
        {
            "name": "示例账号_美食探店",
            "tags": ["美食", "探店"],
            "uid": "demo_uid",
            "profile": {
                "nickname": "示例账号_美食探店",
                "follower_count": 128500,
                "following_count": 368,
                "total_favorited": 5200000,
                "aweme_count": 486,
            },
            "videos": [
                {"aweme_id": "v1", "desc": "这家苍蝇馆子太绝了", "create_time": 1724592000,
                 "play_count": 256800, "digg_count": 18200, "comment_count": 3420,
                 "share_count": 1580, "collect_count": 4200},
                {"aweme_id": "v2", "desc": "网红打卡地拍照超出片", "create_time": 1724505600,
                 "play_count": 189000, "digg_count": 12500, "comment_count": 2180,
                 "share_count": 960, "collect_count": 3100},
            ],
            "douplus": {
                "promotable_items": [
                    {"desc": "推广视频A", "total_consume": 1500, "total_play": 125000,
                     "total_like": 8200, "total_comment": 450, "total_share": 210},
                    {"desc": "推广视频B", "total_consume": 800, "total_play": 78000,
                     "total_like": 5100, "total_comment": 280, "total_share": 130},
                ],
                "total_consume": 2300,
            },
            "captured_at": datetime.now(CST).isoformat(),
        }
    ]
    html = generate_report(demo_results, {"report_title": "测试报告"})
    out = "./reports/test_report.html"
    os.makedirs("./reports", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ 测试报告已生成: {out}")
