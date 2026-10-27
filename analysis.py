"""分析层：三层框架（基本面→估值→技术面）交叉验证 + 大盘预测 + 消息面情绪

原则（防幻觉硬约束）：
- 所有结论只由下方显式规则推导，规则与得分同时输出到报告的"依据"字段
- 任何数据缺失 → 标记"数据缺口"，不估算填充、不编造
- 不预测具体股价点位，不给买卖/仓位指令
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config as _cfg


def _R() -> Dict:
    """取当前生效的分析规则（每次调用重新读盘，Web 改配置即刻生效）"""
    return _cfg.load_rules()


# ============================================================
# 第一层：基本面 —— 值不值得买
# ============================================================

def score_fundamental(fund: Dict) -> Dict:
    if not fund:
        return {
            "score": None, "verdict": "数据不足", "direction": "neutral",
            "reasons": ["财务数据未获取到，基本面层跳过"],
            "gaps": ["ROE/营收增速/净利增速/资产负债率"],
        }
    R = _R()
    score = 50.0
    reasons: List[str] = []
    gaps: List[str] = []

    def _band(v, bands, labels, names):
        """bands: [[阈值, 加分], ...] 从高到低"""
        if v is None:
            gaps.append(names)
            return 0
        for th, pt in bands:
            if v >= th:
                reasons.append(f"{names}={v:.1f}%（{labels.get(th, '')}，{pt:+.0f}）")
                return pt
        last_th, last_pt = bands[-1]
        reasons.append(f"{names}={v:.1f}%（<{last_th}%，{last_pt:+.0f}）")
        return last_pt

    # 营收同比
    score += _band(
        fund.get("revenue_yoy"),
        [tuple(x) for x in R["fund_revenue_bands"]],
        {20: "高增长", 5: "稳增长", 0: "微增", -10: "下滑"},
        "营收同比",
    )
    # 归母净利同比
    score += _band(
        fund.get("profit_yoy"),
        [tuple(x) for x in R["fund_profit_bands"]],
        {30: "高增长", 10: "稳增长", 0: "微增", -1000: "下滑"},
        "归母净利同比",
    )
    # ROE
    score += _band(
        fund.get("roe"),
        [tuple(x) for x in R["fund_roe_bands"]],
        {15: "优秀", 8: "尚可", 0: "偏弱", -1000: "亏损"},
        "ROE加权",
    )
    # 资产负债率（越低越好，金融地产高杠杆属正常，标注口径）
    dr = fund.get("debt_ratio")
    if dr is None:
        gaps.append("资产负债率")
    else:
        if dr < R["fund_debt_ok"]:
            score += 12
            reasons.append(f"资产负债率={dr:.1f}%（低杠杆，+12）")
        elif dr < R["fund_debt_mid"]:
            score += 4
            reasons.append(f"资产负债率={dr:.1f}%（中等，+4）")
        else:
            score -= 8
            reasons.append(f"资产负债率={dr:.1f}%（偏高，-8；金融/地产行业属正常杠杆结构，需人工复核）")

    # 经营现金流/营收
    cf = fund.get("cf_to_revenue")
    if cf is None:
        gaps.append("经营现金流/营收")
    else:
        if cf > R["fund_cf_pos"]:
            score += 10
            reasons.append(f"经营现金流/营收={cf:.2f}（现金流健康，+10）")
        elif cf > 0:
            score += 3
            reasons.append(f"经营现金流/营收={cf:.2f}（微正，+3）")
        else:
            score -= 14
            reasons.append(f"经营现金流/营收={cf:.2f}（经营现金流为负，-14，警惕纸面利润）")

    score = max(0.0, min(100.0, score))
    if score >= R["fund_verdict_good"]:
        verdict, direction = "好公司", "bull"
    elif score >= R["fund_verdict_mid"]:
        verdict, direction = "一般", "neutral"
    else:
        verdict, direction = "质地偏弱", "bear"
    return {
        "score": round(score, 1), "verdict": verdict, "direction": direction,
        "reasons": reasons, "gaps": gaps,
        "report_date": fund.get("report_date"),
        "report_type": fund.get("report_type"),
    }


# ============================================================
# 第二层：估值 —— 贵不贵
# ============================================================

def score_valuation(quote: Dict, tech: Dict, fund: Dict) -> Dict:
    R = _R()
    pe = quote.get("pe_ttm") if quote else None
    pb = quote.get("pb") if quote else None
    pos52 = tech.get("pos_52w") if tech else None
    reasons: List[str] = []
    gaps: List[str] = []
    score = 50.0

    if pe is None:
        gaps.append("PE(TTM)")
    elif pe < 0:
        score -= 12
        reasons.append(f"PE(TTM)={pe:.1f}（亏损/微利，PE 失效，-12；应改看 P/S 与同行横比，本报告不估算 P/S）")
    elif pe < R["val_pe_cheap"]:
        score += R["val_pe_cheap_score"]
        reasons.append(f"PE(TTM)={pe:.1f}（绝对低估区 <{R['val_pe_cheap']:g}，{R['val_pe_cheap_score']:+.0f}）")
    elif pe < R["val_pe_fair"]:
        score += R["val_pe_fair_score"]
        reasons.append(f"PE(TTM)={pe:.1f}（合理区 {R['val_pe_cheap']:g}-{R['val_pe_fair']:g}，{R['val_pe_fair_score']:+.0f}）")
    elif pe < R["val_pe_expensive"]:
        score += R["val_pe_exp_score"]
        reasons.append(f"PE(TTM)={pe:.1f}（偏贵 {R['val_pe_fair']:g}-{R['val_pe_expensive']:g}，{R['val_pe_exp_score']:+.0f}）")
    else:
        score += R["val_pe_high_score"]
        reasons.append(f"PE(TTM)={pe:.1f}（高估值 >{R['val_pe_expensive']:g}，{R['val_pe_high_score']:+.0f}）")

    if pb is None:
        gaps.append("PB")
    elif pb < R["val_pb_cheap"]:
        score += 18
        reasons.append(f"PB={pb:.2f}（<{R['val_pb_cheap']:g}，破净/近破净区，+18）")
    elif pb < R["val_pb_fair"]:
        score += 10
        reasons.append(f"PB={pb:.2f}（{R['val_pb_cheap']:g}-{R['val_pb_fair']:g}，合理，+10）")
    elif pb < R["val_pb_expensive"]:
        score += 0
        reasons.append(f"PB={pb:.2f}（{R['val_pb_fair']:g}-{R['val_pb_expensive']:g}，偏高，0）")
    else:
        score -= 10
        reasons.append(f"PB={pb:.2f}（>{R['val_pb_expensive']:g}，高，-10）")

    if pos52 is None:
        gaps.append("52周股价位置")
    else:
        if pos52 < R["val_pos_low"]:
            score += 22
            reasons.append(f"52周股价位置={pos52:.0f}%（低位区，+22）")
        elif pos52 < R["val_pos_high"]:
            score += 8
            reasons.append(f"52周股价位置={pos52:.0f}%（中位区，+8）")
        else:
            score -= 6
            reasons.append(f"52周股价位置={pos52:.0f}%（高位区，-6）")

    # PEG（仅在净利增速 > 0 且 PE > 0 时有效）
    profit_yoy = fund.get("profit_yoy") if fund else None
    if pe and pe > 0 and profit_yoy and profit_yoy > 0:
        peg = pe / profit_yoy
        if peg < R["val_peg_good"]:
            score += 20
            reasons.append(f"PEG={peg:.2f}（<{R['val_peg_good']:g}，增速匹配估值，+20）")
        elif peg < R["val_peg_fair"]:
            score += 8
            reasons.append(f"PEG={peg:.2f}（{R['val_peg_good']:g}-{R['val_peg_fair']:g}，尚可，+8）")
        else:
            score -= 8
            reasons.append(f"PEG={peg:.2f}（>{R['val_peg_fair']:g}，估值透支增速，-8）")
    else:
        gaps.append("PEG（缺有效正增速或 PE）")

    score = max(0.0, min(100.0, score))
    if score >= R["val_verdict_cheap"]:
        verdict, direction = "便宜", "bull"
    elif score >= R["val_verdict_mid"]:
        verdict, direction = "合理", "neutral"
    else:
        verdict, direction = "贵", "bear"
    return {
        "score": round(score, 1), "verdict": verdict, "direction": direction,
        "reasons": reasons, "gaps": gaps,
    }


# ============================================================
# 第三层：技术面 —— 什么时候（相对时机）
# ============================================================

def score_technical(tech: Dict) -> Dict:
    if not tech or tech.get("price") is None:
        return {
            "score": None, "verdict": "数据不足", "direction": "neutral",
            "reasons": ["K线数据未获取到，技术面层跳过"], "gaps": ["K线"],
        }
    price = tech["price"]
    reasons: List[str] = []
    gaps: List[str] = []
    score = 50.0
    R = _R()

    def _ma_check(name, key, weight_bull, weight_flat=""):
        nonlocal score
        mv = tech.get(key)
        if mv is None:
            gaps.append(name)
            return
        if price > mv:
            score += weight_bull
            reasons.append(f"现价{price:.2f} > {name}={mv:.2f}（趋势偏多，+{weight_bull}）")
        else:
            score -= weight_bull
            reasons.append(f"现价{price:.2f} < {name}={mv:.2f}（趋势偏空，-{weight_bull}）")

    _ma_check("MA20", "ma20", R["tech_ma20_w"])
    _ma_check("MA60", "ma60", R["tech_ma60_w"])
    if tech.get("ma120") is not None:
        _ma_check("MA120", "ma120", R["tech_ma120_w"])

    hist = tech.get("macd_hist")
    if hist is None:
        gaps.append("MACD")
    else:
        if hist > 0:
            score += R["tech_macd_w"]
            reasons.append(f"MACD柱={hist:.3f}（多头动能，+{R['tech_macd_w']:g}）")
        else:
            score -= R["tech_macd_w"]
            reasons.append(f"MACD柱={hist:.3f}（空头动能，-{R['tech_macd_w']:g}）")

    r = tech.get("rsi14")
    if r is None:
        gaps.append("RSI14")
    else:
        if r >= R["tech_rsi_overbought"]:
            score -= 6
            reasons.append(f"RSI14={r:.1f}（超买区，短期回调风险，-6）")
        elif r <= R["tech_rsi_oversold"]:
            score += 6
            reasons.append(f"RSI14={r:.1f}（超卖区，存在修复需求，+6）")
        elif 40 <= r <= 60:
            score += 6
            reasons.append(f"RSI14={r:.1f}（中性健康区，+6）")
        else:
            score += 0
            reasons.append(f"RSI14={r:.1f}（中性偏强/弱，0）")

    vr = tech.get("vol_ratio")
    chg5 = tech.get("chg_5d")
    if vr is None:
        gaps.append("量能比")
    else:
        if vr > R["tech_vol_confirm"] and (chg5 or 0) > 0:
            score += 10
            reasons.append(f"量比(5/20日)={vr:.2f} 且近5日上涨（放量上行，量价配合，+10）")
        elif vr > R["tech_vol_confirm"] and (chg5 or 0) < 0:
            score -= 6
            reasons.append(f"量比(5/20日)={vr:.2f} 但近5日下跌（放量下跌，-6）")
        else:
            score += 2
            reasons.append(f"量比(5/20日)={vr:.2f}（量能平稳，+2）")

    pos = tech.get("pos_52w")
    if pos is not None and pos < R["tech_pos_low"]:
        score += 6
        reasons.append(f"52周位置={pos:.0f}%（相对低位，中期赔率占优，+6）")

    score = max(0.0, min(100.0, score))
    if score >= R["tech_verdict_bull"]:
        verdict, direction = "偏多（相对积极）", "bull"
    elif score >= R["tech_verdict_mid"]:
        verdict, direction = "震荡/观望", "neutral"
    else:
        verdict, direction = "偏空（等待企稳）", "bear"
    return {
        "score": round(score, 1), "verdict": verdict, "direction": direction,
        "reasons": reasons, "gaps": gaps,
    }


# ============================================================
# 三层交叉验证 → 方向 / 置信度 / 依据
# ============================================================

def cross_validate(fund_r: Dict, val_r: Dict, tech_r: Dict) -> Dict:
    R = _R()
    layers = [
        ("基本面", fund_r, R["w_fund"]),
        ("估值", val_r, R["w_val"]),
        ("技术面", tech_r, R["w_tech"]),
    ]
    valid = [(n, r, w) for n, r, w in layers if r.get("score") is not None]
    all_gaps = []
    for n, r, _ in layers:
        for g in r.get("gaps") or []:
            all_gaps.append(f"{n}-{g}")

    if not valid:
        return {
            "direction": "观望", "confidence": "低",
            "confidence_score": 20,
            "summary": "三层数据均不可得，不做方向判断",
            "layer_table": [], "gaps": all_gaps,
        }

    # 加权综合分
    total_w = sum(w for _, _, w in valid)
    comp = sum(r["score"] * w for _, r, w in valid) / total_w

    # 方向
    if comp >= R["dir_bull"]:
        direction = "看涨"
    elif comp >= R["dir_bear"]:
        direction = "震荡"
    else:
        direction = "看跌"

    # 交叉验证：统计各层方向一致性
    dirs = [r.get("direction", "neutral") for _, r, _ in valid]
    bulls = sum(1 for d in dirs if d == "bull")
    bears = sum(1 for d in dirs if d == "bear")
    neutrals = sum(1 for d in dirs if d == "neutral")
    n_valid = len(valid)

    strong_same = (bulls == n_valid and n_valid >= 2) or (bears == n_valid and n_valid >= 2)
    mostly_same = (bulls >= 2 or bears >= 2) and n_valid >= 2
    conflict = bulls >= 1 and bears >= 1

    # 置信度
    if strong_same and not all_gaps:
        conf, conf_score = "高", 85
    elif strong_same:
        conf, conf_score = "高", 78
    elif mostly_same and not conflict and len(all_gaps) <= 1:
        conf, conf_score = "中", 62
    elif conflict:
        conf, conf_score = "低", 35
    else:
        conf, conf_score = "中" if len(all_gaps) <= 2 else "低", 50 if len(all_gaps) <= 2 else 32

    if n_valid == 1:
        conf, conf_score = "低", 30

    # 依据摘要：每层一句结论 + 关键加减分
    layer_table = []
    for name, r, w in layers:
        layer_table.append({
            "layer": name,
            "score": r.get("score"),
            "verdict": r.get("verdict"),
            "direction": r.get("direction"),
            "reasons": r.get("reasons") or [],
            "gaps": r.get("gaps") or [],
            "weight": w,
        })

    agree_txt = f"看多{bulls} / 看空{bears} / 中性{neutrals}（有效层{n_valid}/3）"
    summary = (
        f"三层加权综合分 {comp:.1f}。交叉验证：{agree_txt}。"
        f"{'三层同向共振，信号较强。' if strong_same else '存在层间分歧或信息缺口，谨慎参考。' if conflict else '信号大体一致但强度一般。'}"
    )
    return {
        "direction": direction,
        "confidence": conf,
        "confidence_score": conf_score,
        "composite_score": round(comp, 1),
        "summary": summary,
        "layer_table": layer_table,
        "gaps": all_gaps,
    }


def analyze_stock(item: Dict, quote: Dict, klines: List[dict], fund: Dict) -> Dict:
    """单只股票三层分析主入口"""
    import indicators as ind

    tech_raw = ind.compute_all(klines) if klines else {}
    fund_r = score_fundamental(fund)
    val_r = score_valuation(quote, tech_raw, fund)
    tech_r = score_technical(tech_raw)
    cv = cross_validate(fund_r, val_r, tech_r)

    # 一句话理由（供表格展示）
    brief_parts = []
    if fund_r.get("score") is not None:
        brief_parts.append(f"基本面{fund_r['verdict']}({fund_r['score']:.0f})")
    if val_r.get("score") is not None:
        brief_parts.append(f"估值{val_r['verdict']}({val_r['score']:.0f})")
    if tech_r.get("score") is not None:
        brief_parts.append(f"技术面{tech_r['verdict']}({tech_r['score']:.0f})")
    brief = "；".join(brief_parts) if brief_parts else "数据不足"
    if cv["gaps"]:
        brief += f"。缺口：{'、'.join(cv['gaps'][:3])}"

    return {
        "code": item["code"],
        "market": item["market"],
        "name": (quote or {}).get("name") or item.get("name") or "",
        "sources": item.get("sources") or [],
        "sources_detail": item.get("sources_detail") or [],
        "rank": item.get("rank"),
        "tags": item.get("tags") or [],
        "quote": {
            "price": (quote or {}).get("price"),
            "change_pct": (quote or {}).get("change_pct"),
            "pe_ttm": (quote or {}).get("pe_ttm"),
            "pb": (quote or {}).get("pb"),
        },
        "tech_summary": {
            "ma20": tech_raw.get("ma20"), "ma60": tech_raw.get("ma60"),
            "rsi14": tech_raw.get("rsi14"), "macd_hist": tech_raw.get("macd_hist"),
            "pos_52w": tech_raw.get("pos_52w"), "chg_5d": tech_raw.get("chg_5d"),
        },
        "fundamental": fund_r,
        "valuation": val_r,
        "technical": tech_r,
        "cross": cv,
        "brief": brief,
    }


# ============================================================
# 消息面情绪（关键词规则，透明可复核）
# ============================================================

POS_WORDS = [
    "降准", "降息", "降LPR", "利好", "支持", "补贴", "增持", "回购", "中标",
    "突破", "创新高", "超预期", "预增", "扭亏", "政策支持", "专项债", "财政发力",
    "扩大内需", "促消费", "新高", "获批", "签约", "大单", "景气",
]
NEG_WORDS = [
    "利空", "减持", "处罚", "立案", "调查", "违约", "爆雷", "亏损扩大",
    "下滑", "衰退", "制裁", "出口管制", "加税", "加息", "缩表", "IPO抽水",
    "解禁", "违规", "警示函", "下修", "终止", "诉讼", "减持计划", "业绩预亏",
]


def score_sentiment(news: List[dict]) -> Dict:
    if not news:
        return {
            "score": 50, "label": "中性（消息面样本为空）",
            "pos_hits": [], "neg_hits": [], "themes": [], "count": 0,
        }
    pos_hits, neg_hits = [], []
    word_counter: Dict[str, int] = {}
    for n in news:
        text = (n.get("title") or "") + (n.get("summary") or "")
        for w in POS_WORDS:
            if w in text:
                word_counter[w] = word_counter.get(w, 0) + 1
                pos_hits.append({"word": w, "title": n.get("title", "")[:80], "time": n.get("time")})
        for w in NEG_WORDS:
            if w in text:
                word_counter[w] = word_counter.get(w, 0) + 1
                neg_hits.append({"word": w, "title": n.get("title", "")[:80], "time": n.get("time")})

    # 去重按词（展示用），词频统计用 word_counter（全量计数）
    def _uniq(hits):
        seen, out = set(), []
        for h in hits:
            if h["word"] in seen:
                continue
            seen.add(h["word"])
            out.append(h)
        return out

    pos_hits, neg_hits = _uniq(pos_hits), _uniq(neg_hits)
    raw = 50 + len(pos_hits) * 6 - len(neg_hits) * 6
    score = max(0, min(100, raw))
    if score >= 62:
        label = "偏正面"
    elif score <= 38:
        label = "偏负面"
    else:
        label = "中性"

    # 主题归类（出现频次最高的关键词，全量计数）
    themes = sorted(word_counter.items(), key=lambda x: -x[1])[:8]

    return {
        "score": score, "label": label,
        "pos_hits": pos_hits[:10], "neg_hits": neg_hits[:10],
        "themes": [{"word": w, "count": c} for w, c in themes],
        "count": len(news),
    }


# ============================================================
# 大盘预测
# ============================================================

def forecast_market(index_data: Dict, index_klines: Dict[str, List[dict]],
                    breadth: Dict, sentiment: Dict) -> Dict:
    """大盘趋势预测：指数趋势 + 广度 + 消息面情绪 → 预测/影响因素/风险提示"""
    import indicators as ind

    R = _R()
    factors: List[str] = []
    risks: List[str] = []
    score = 50.0

    # --- 指数趋势 ---
    idx_rows = []
    for name, kl in index_klines.items():
        if not kl:
            continue
        t = ind.compute_all(kl)
        chg5 = t.get("chg_5d")
        chg20 = t.get("chg_20d")
        above20 = t.get("ma20") is not None and t["price"] > t["ma20"]
        above60 = t.get("ma60") is not None and t["price"] > t["ma60"]
        idx_rows.append({
            "name": name,
            "price": t.get("price"),
            "chg_5d": chg5, "chg_20d": chg20,
            "ma20": t.get("ma20"), "ma60": t.get("ma60"),
            "above20": above20, "above60": above60,
        })
        if above20:
            score += 6
        else:
            score -= 6
        if above60:
            score += 5
        else:
            score -= 5
        if (chg20 or 0) > 1:
            score += 4
        elif (chg20 or 0) < -1:
            score -= 4

    if idx_rows:
        up20 = sum(1 for r in idx_rows if r["above20"])
        factors.append(
            f"指数趋势：{len(idx_rows)}个主要指数中{up20}个站上MA20；"
            + "、".join(
                f"{r['name']}{r['chg_5d']:+.1f}%(5日)/{r['chg_20d']:+.1f}%(20日)"
                for r in idx_rows if r["chg_5d"] is not None
            )
        )
        if up20 >= len(idx_rows) * 0.7:
            factors.append("多数指数中期均线呈多头排列，趋势面偏强")
        elif up20 <= len(idx_rows) * 0.3:
            factors.append("多数指数位于 MA20 下方，趋势面偏弱")
            risks.append("指数层面趋势走弱，注意系统性回撤风险")

    # --- 市场广度 ---
    br = breadth.get("上证指数") or {}
    br2 = breadth.get("深证成指") or {}
    up = (br.get("up") or 0) + (br2.get("up") or 0)
    down = (br.get("down") or 0) + (br2.get("down") or 0)
    flat = (br.get("flat") or 0) + (br2.get("flat") or 0)
    total = up + down + flat
    if total > 0:
        up_ratio = up / total * 100
        factors.append(f"市场广度：上涨{up}家 / 下跌{down}家 / 平盘{flat}家（上涨占比{up_ratio:.1f}%）")
        if up_ratio >= R["breadth_healthy"]:
            score += 10
            factors.append("个股涨多跌少，赚钱效应较好，属相对健康结构")
        elif up_ratio <= R["breadth_weak"]:
            score -= 12
            risks.append(f"上涨占比仅{up_ratio:.1f}%，赚钱效应差，指数若靠权重撑住需警惕脆弱性")
        elif up_ratio < R["breadth_soft"]:
            score -= 5
            factors.append(f"下跌家数多于上涨（上涨占比{up_ratio:.1f}%），赚钱效应偏弱")
        else:
            score += 0
            factors.append("涨跌家数大致均衡，属震荡结构")
    else:
        risks.append("市场广度数据未获取到，结构性判断受限")

    # --- 消息面 ---
    s_score = sentiment.get("score", 50)
    s_label = sentiment.get("label", "中性")
    score += (s_score - 50) * 0.35
    factors.append(
        f"消息面情绪：{s_label}（情绪分{s_score}，样本{sentiment.get('count', 0)}条，"
        f"窗口内利好关键词{len(sentiment.get('pos_hits', []))}个/利空关键词{len(sentiment.get('neg_hits', []))}个）"
    )
    if sentiment.get("themes"):
        factors.append(
            "高频关键词：" + "、".join(f"{t['word']}({t['count']})" for t in sentiment["themes"][:6])
        )
    if s_score <= 38:
        risks.append("消息面负面关键词占优，注意周末突发政策/事件对周一开盘的冲击")

    # --- 波动风险 ---
    for r in idx_rows:
        if r.get("chg_5d") is not None and abs(r["chg_5d"]) > 3:
            risks.append(f"{r['name']}近5日波动达{r['chg_5d']:+.1f}%，短期波动放大")

    score = max(0.0, min(100.0, score))
    if score >= 62:
        trend, stance = "偏多", "市场情绪与趋势面共振偏暖，下一交易日可关注量能能否延续"
    elif score >= 45:
        trend, stance = "震荡", "多空力量相对均衡，结构重于指数，宜控制节奏"
    else:
        trend, stance = "偏空", "趋势与情绪面偏弱，注意回撤风险与仓位管理"

    if not risks:
        risks.append("常规风险：海外市场波动、突发政策/地缘事件、量能不济导致的冲高回落")

    return {
        "trend": trend,
        "stance": stance,
        "composite_score": round(score, 1),
        "factors": factors,
        "risks": risks,
        "index_rows": idx_rows,
        "breadth": {"up": up, "down": down, "flat": flat, "up_ratio": round(up / total * 100, 1) if total else None},
        "sentiment": sentiment,
    }
