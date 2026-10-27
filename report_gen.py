"""HTML 报告生成：大盘预测 + 个股预测表格 + 数据来源 + 免责声明

风格：浅底深字、内联样式、无 JS（避免脚本失配导致整页图表失效），
结论先行，表格承载个股预测。
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List

import config as C

# 涨跌配色（A股惯例：涨红跌绿）
RED = "#c0392b"
GREEN = "#1e8449"
GRAY = "#5d6d7e"


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def _fmt_pct(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:+.{digits}f}%"


def _fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _pct_color(v) -> str:
    if v is None:
        return GRAY
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return GRAY
    if fv > 0:
        return RED
    if fv < 0:
        return GREEN
    return GRAY


def _dir_badge(direction: str) -> str:
    color = {"看涨": RED, "看跌": GREEN}.get(direction, GRAY)
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
        f'background:{color};color:#fff;font-size:12px;font-weight:600;">{_e(direction)}</span>'
    )


def _conf_badge(conf: str) -> str:
    color = {"高": "#1a5276", "中": "#b9770e", "低": "#7f8c8d"}.get(conf, GRAY)
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:8px;'
        f'border:1px solid {color};color:{color};font-size:12px;">置信度{_e(conf)}</span>'
    )


BASE_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 48px;
  background: #f4f6f7; color: #1c2833;
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
  line-height: 1.65; font-size: 14px;
}
.wrap { max-width: 1080px; margin: 0 auto; }
.card {
  background: #fff; border-radius: 10px; padding: 22px 26px; margin-bottom: 18px;
  border: 1px solid #e5e8e8; box-shadow: 0 1px 3px rgba(0,0,0,.04);
}
h1 { font-size: 24px; margin: 0 0 6px; color: #1a5276; }
h2 {
  font-size: 18px; margin: 0 0 14px; padding-left: 10px;
  border-left: 4px solid #1a5276; color: #1a5276;
}
h3 { font-size: 15px; margin: 16px 0 8px; color: #2c3e50; }
.meta { color: #5d6d7e; font-size: 12.5px; margin-bottom: 4px; }
.tag {
  display: inline-block; background: #eaf2f8; color: #1a5276;
  border-radius: 4px; padding: 1px 8px; font-size: 12px; margin: 2px 4px 2px 0;
}
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
th, td { border: 1px solid #d5dbdb; padding: 7px 9px; text-align: left; vertical-align: top; }
th { background: #eaf2f8; color: #1a5276; font-weight: 600; white-space: nowrap; }
tr:nth-child(even) td { background: #fbfcfc; }
.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
ul.factors { margin: 6px 0; padding-left: 20px; }
ul.factors li { margin: 4px 0; }
.callout {
  background: #fef9e7; border-left: 4px solid #d4ac0d;
  padding: 10px 14px; border-radius: 4px; margin: 10px 0;
}
.callout.risk { background: #fdedec; border-left-color: #c0392b; }
.callout.src { background: #eafaf1; border-left-color: #1e8449; }
.disclaimer {
  background: #f8f9f9; border: 1px solid #d5dbdb; border-radius: 8px;
  padding: 14px 18px; color: #566573; font-size: 12.5px; line-height: 1.8;
}
.small { font-size: 12px; color: #7f8c8d; }
.kpi-row { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0; }
.kpi {
  flex: 1 1 140px; background: #f8f9f9; border: 1px solid #e5e8e8;
  border-radius: 8px; padding: 12px 14px;
}
.kpi .v { font-size: 22px; font-weight: 700; color: #1a5276; }
.kpi .k { font-size: 12px; color: #7f8c8d; }
.badge-row { margin: 8px 0 4px; }
"""


def render_report(result: Dict) -> str:
    """把 pipeline 结果渲染为独立 HTML（无 JS）"""
    meta = result.get("meta") or {}
    market = result.get("market_forecast") or {}
    stocks: List[Dict] = result.get("stocks") or []
    pool_info = result.get("pool") or {}
    sources: List[Dict] = result.get("sources") or []
    gaps: List[str] = result.get("gaps") or []
    news = result.get("news") or {}
    run_id = meta.get("run_id", "")

    # ---- 头部 ----
    parts: List[str] = []
    parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>次一交易日市场预测报告 {_e(meta.get("report_date", ""))}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="wrap">
<div class="card">
  <h1>次一交易日市场预测报告</h1>
  <div class="meta">报告生成时间：{_e(meta.get("generated_at", ""))}　|　执行日：{_e(meta.get("run_weekday", ""))}　|　报告编号：{_e(run_id)}</div>
  <div class="meta">消息面采集窗口：{_e(meta.get("news_window", ""))}　|　数据抓取时点：{_e(pool_info.get("fetched_at", ""))}</div>
  <div class="badge-row">
    <span class="tag">大盘 {_e(market.get("trend", "—"))}</span>
    <span class="tag">样本股 {len(stocks)} 只</span>
    <span class="tag">A股池 {pool_info.get("stats", {}).get("merged_a", "—")}</span>
    <span class="tag">港股池 {pool_info.get("stats", {}).get("merged_hk", "—")}</span>
    <span class="tag">消息样本 {news.get("count", 0)} 条</span>
  </div>
</div>
""")

    # ---- 大盘预测 ----
    parts.append('<div class="card"><h2>一、次一交易日大盘趋势预测</h2>')
    trend = market.get("trend", "—")
    trend_color = {"偏多": RED, "偏空": GREEN}.get(trend, GRAY)
    parts.append(
        f'<div class="kpi-row">'
        f'<div class="kpi"><div class="k">趋势判断</div>'
        f'<div class="v" style="color:{trend_color}">{_e(trend)}</div></div>'
        f'<div class="kpi"><div class="k">综合分（0-100）</div>'
        f'<div class="v">{_fmt_num(market.get("composite_score"), 1)}</div></div>'
        f'<div class="kpi"><div class="k">上涨家数占比</div>'
        f'<div class="v">{_e((market.get("breadth") or {}).get("up_ratio", "—"))}%</div></div>'
        f'<div class="kpi"><div class="k">消息面情绪</div>'
        f'<div class="v">{_e((market.get("sentiment") or {}).get("label", "—"))}</div></div>'
        f'</div>'
    )
    parts.append(f'<p><strong>判断：</strong>{_e(market.get("stance", ""))}</p>')
    eng = market.get("engine", "rule")
    eng_txt = f"LLM 研判（{eng}）" if market.get("llm_used") else "确定性规则（LLM 未启用）"
    conf_txt = market.get("confidence") or "—"
    parts.append(
        f'<p class="small">研判引擎：{_e(eng_txt)}　|　研判置信度：{_e(conf_txt)}</p>'
    )

    # 指数表
    idx_rows = market.get("index_rows") or []
    if idx_rows:
        parts.append('<h3>指数表现（涨幅为原始收盘价重算）</h3><table><tr>'
                     '<th>指数</th><th class="num">最新</th><th class="num">近5日</th>'
                     '<th class="num">近20日</th><th>MA20</th><th>MA60</th></tr>')
        for r in idx_rows:
            parts.append(
                f'<tr><td>{_e(r["name"])}</td>'
                f'<td class="num">{_fmt_num(r.get("price"), 2)}</td>'
                f'<td class="num" style="color:{_pct_color(r.get("chg_5d"))}">{_fmt_pct(r.get("chg_5d"))}</td>'
                f'<td class="num" style="color:{_pct_color(r.get("chg_20d"))}">{_fmt_pct(r.get("chg_20d"))}</td>'
                f'<td>{"站上" if r.get("above20") else "跌破"}</td>'
                f'<td>{"站上" if r.get("above60") else "跌破"}</td></tr>'
            )
        parts.append('</table>')

    parts.append('<h3>影响因素</h3><ul class="factors">')
    for f in market.get("factors") or []:
        parts.append(f'<li>{_e(f)}</li>')
    parts.append('</ul>')

    if market.get("key_watch"):
        parts.append('<h3>下一交易日需跟踪的可验证信号</h3><ul class="factors">')
        for w in market["key_watch"]:
            parts.append(f'<li>{_e(w)}</li>')
        parts.append('</ul>')

    parts.append('<div class="callout risk"><strong>⚠ 风险提示</strong><ul class="factors">')
    for r in market.get("risks") or []:
        parts.append(f'<li>{_e(r)}</li>')
    parts.append('</ul></div>')

    # 消息面要点
    sent = market.get("sentiment") or {}
    if sent.get("pos_hits") or sent.get("neg_hits"):
        parts.append('<h3>消息面关键词命中（规则匹配，非观点）</h3><table>'
                     '<tr><th>类别</th><th>关键词</th><th>示例消息</th><th>时间</th></tr>')
        for h in (sent.get("pos_hits") or [])[:6]:
            parts.append(f'<tr><td style="color:{RED}">利好词</td><td>{_e(h["word"])}</td>'
                         f'<td>{_e(h.get("title", ""))}</td><td class="small">{_e(h.get("time", ""))}</td></tr>')
        for h in (sent.get("neg_hits") or [])[:6]:
            parts.append(f'<tr><td style="color:{GREEN}">利空词</td><td>{_e(h["word"])}</td>'
                         f'<td>{_e(h.get("title", ""))}</td><td class="small">{_e(h.get("time", ""))}</td></tr>')
        parts.append('</table>')
    parts.append('</div>')

    # ---- 个股预测 ----
    parts.append('<div class="card"><h2>二、个股预测（三层分析框架交叉验证）</h2>')
    parts.append(
        '<p class="small">框架：基本面（值不值得买）→ 估值（贵不贵）→ 技术面（相对时机），'
        '逐层打分后交叉验证得出方向与置信度。方向为「相对次一交易日的强弱倾向」，'
        '非买卖指令；不预测具体点位。</p>'
    )
    parts.append(
        '<table><tr><th>代码</th><th>名称</th><th>市场</th><th>热榜来源</th>'
        '<th class="num">现价</th><th class="num">涨跌%</th><th class="num">PE(TTM)</th>'
        '<th class="num">PB</th><th>方向</th><th>置信度</th><th>理由（三层摘要）</th></tr>'
    )
    for s in stocks:
        q = s.get("quote") or {}
        chg = q.get("change_pct")
        code_disp = s["code"] if s.get("market") != "HK" else f'{s["code"]}.HK'
        if s.get("market") == "SH":
            code_disp = f'{s["code"]}.SH'
        elif s.get("market") == "SZ":
            code_disp = f'{s["code"]}.SZ'
        src = "、".join(s.get("sources_detail") or []) or "—"
        parts.append(
            f'<tr>'
            f'<td>{_e(code_disp)}</td>'
            f'<td>{_e(s.get("name") or "—")}</td>'
            f'<td>{_e(s.get("market"))}</td>'
            f'<td class="small">{_e(src)}</td>'
            f'<td class="num">{_fmt_num(q.get("price"))}</td>'
            f'<td class="num" style="color:{_pct_color(chg)}">{_fmt_pct(chg)}</td>'
            f'<td class="num">{_fmt_num(q.get("pe_ttm"), 1)}</td>'
            f'<td class="num">{_fmt_num(q.get("pb"), 2)}</td>'
            f'<td>{_dir_badge(s.get("cross", {}).get("direction", "观望"))}</td>'
            f'<td>{_conf_badge(s.get("cross", {}).get("confidence", "低"))}</td>'
            f'<td class="small">{_e(s.get("brief", ""))}</td>'
            f'</tr>'
        )
    parts.append('</table>')

    # 详细三层展开（前 20 只，避免页面过长）
    parts.append('<h3>重点个股三层依据展开（按综合分排序前 20）</h3>')
    detailed = sorted(
        stocks,
        key=lambda x: -(x.get("cross", {}).get("composite_score") or 0),
    )[:20]
    for s in detailed:
        cv = s.get("cross") or {}
        code_disp = f'{s["code"]}.HK' if s.get("market") == "HK" else f'{s["code"]}.{s.get("market", "")}'
        parts.append(
            f'<h3>{_e(s.get("name") or s["code"])}（{_e(code_disp)}）'
            f'　{_dir_badge(cv.get("direction", "观望"))} {_conf_badge(cv.get("confidence", "低"))}'
            f'　综合分 {_fmt_num(cv.get("composite_score"), 1)}</h3>'
        )
        parts.append(f'<p class="small">{_e(cv.get("summary", ""))}</p>')
        parts.append('<table><tr><th>层次</th><th class="num">得分</th><th>结论</th><th>依据</th><th>缺口</th></tr>')
        for lt in cv.get("layer_table") or []:
            reasons = "；".join(lt.get("reasons") or []) or "—"
            gaps_t = "、".join(lt.get("gaps") or []) or "无"
            parts.append(
                f'<tr><td>{_e(lt["layer"])}</td>'
                f'<td class="num">{_fmt_num(lt.get("score"), 1)}</td>'
                f'<td>{_e(lt.get("verdict", "—"))}</td>'
                f'<td class="small">{_e(reasons)}</td>'
                f'<td class="small">{_e(gaps_t)}</td></tr>'
            )
        parts.append('</table>')
    parts.append('</div>')

    # ---- 股票池说明 ----
    parts.append('<div class="card"><h2>三、热点股票池构建</h2>')
    for n in pool_info.get("notes") or []:
        parts.append(f'<p class="small">· {_e(n)}</p>')
    st = pool_info.get("stats") or {}
    parts.append(
        f'<p class="small">抓取计数：东财人气榜 {st.get("a_em", "—")} 条、同花顺热股 {st.get("a_ths", "—")} 条、'
        f'东财港股成交额榜 {st.get("hk_amt", "—")} 条、东财港股涨幅榜 {st.get("hk_chg", "—")} 条；'
        f'合并去重后 A 股 {st.get("merged_a", "—")} 只、港股 {st.get("merged_hk", "—")} 只，合计 {st.get("total", "—")} 只。</p>'
    )
    parts.append('</div>')

    # ---- 数据来源 ----
    parts.append('<div class="card"><h2>四、数据来源与抓取时间</h2>')
    parts.append('<table><tr><th>数据项</th><th>来源</th><th>口径/接口</th><th>抓取时间</th></tr>')
    for s in sources:
        parts.append(
            f'<tr><td>{_e(s.get("item", ""))}</td><td>{_e(s.get("source", ""))}</td>'
            f'<td class="small">{_e(s.get("detail", ""))}</td>'
            f'<td class="small">{_e(s.get("fetched_at", ""))}</td></tr>'
        )
    parts.append('</table>')
    parts.append(
        '<p class="small">数据质量分级：交易所/平台公开接口返回值为一手行情与财务数据；'
        '消息面为财经媒体快讯（非一手来源，需核实原文）；'
        '港股热点采用成交额/涨幅榜作为热度代理口径（原人气榜接口不覆盖港股），已在表中标注。</p>'
    )
    parts.append('</div>')

    # ---- 数据缺口 ----
    parts.append('<div class="card"><h2>五、数据缺口与已知限制</h2><ul class="factors">')
    base_gaps = [
        "港股公司财务指标依赖东财 F10 接口，个别标的可能取不到，取不到时相关层标记「数据不足」并降低置信度，不做估算填充。",
        "估值层的历史 PE 分位需要多年 PE 序列，公开接口不稳定，本报告以「PE 绝对水平 + 52 周股价位置 + PEG」替代，未伪造历史分位。",
        "消息面情绪采用关键词规则匹配，仅反映词频倾向，不构成对消息内容的语义理解或观点判断。",
        "本报告不预测具体股价点位，不提供买卖/仓位指令；方向判断为相对强弱倾向，仅供参考。",
    ]
    for g in base_gaps + (gaps or []):
        parts.append(f'<li>{_e(g)}</li>')
    parts.append('</ul></div>')

    # ---- 免责声明 ----
    parts.append(f"""<div class="card">
<div class="disclaimer">
<strong>免责声明</strong><br>
{_e(C.DISCLAIMER)}<br><br>
<span class="small">报告编号 {_e(run_id)}　|　自动生成，未经人工审核　|　生成时间 {_e(meta.get("generated_at", ""))}</span>
</div>
</div>
</div>
</body>
</html>""")

    return "".join(parts)
