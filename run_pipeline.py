"""定时任务主入口：抓取 → 分析 → 落库 → 回测 → 生成报告

cron 调用：每日 22:00 执行（Asia/Shanghai），预测次一交易日。
消息面窗口 = 当日 00:00 至执行时点。
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from datetime import datetime, timedelta

import config as C
import scrapers as S
import analysis as A
import report_gen as R
import db as D
import llm as L

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("pipeline")


def news_window_hours() -> tuple:
    """每日运行：采集当日 00:00 至执行时点的消息面"""
    now = datetime.now()
    hours = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
    return max(hours, 1.0), f"{now.strftime('%Y-%m-%d')} 当日消息（00:00 至执行时点）"


def run_backtest(run_id: str) -> dict:
    """对往期预测回填实际涨跌与命中"""
    rules = C.load_rules()
    flat_pct = float(rules.get("backtest_flat_pct", 1.0))
    pending = D.list_unverified_predictions(run_id)
    if not pending:
        return {"checked": 0, "filled": 0}
    log.info("回测：待对账往期预测 %d 条（震荡阈值 %.1f%%）", len(pending), flat_pct)

    need = [(p["market"], p["code"], p["id"], p["direction"], p["price_at_pred"])
            for p in pending if p.get("price_at_pred")]
    pairs = [(m, c) for m, c, *_ in need]
    live_quotes = S.fetch_quotes_batch(pairs)

    filled = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for market, code, pid, direction, pred_price in need:
        q = live_quotes.get(code)
        if not q or q.get("price") is None or not pred_price:
            continue
        cur = q["price"]
        pct = (cur / pred_price - 1.0) * 100.0
        if direction == "看涨":
            hit = 1 if pct > 0 else 0
        elif direction == "看跌":
            hit = 1 if pct < 0 else 0
        else:
            hit = 1 if abs(pct) < flat_pct else 0
        D.record_result(pid, round(pct, 2), hit, today)
        filled += 1
    log.info("回测：对账完成 %d/%d", filled, len(need))
    return {"checked": len(need), "filled": filled}


def run() -> dict:
    t0 = time.time()
    now = datetime.now()
    run_id = now.strftime("%Y%m%d_%H%M%S")
    D.init_db()
    log.info("==== pipeline 启动 %s ====", run_id)

    # ---------- 1. 热股池 ----------
    log.info("步骤 1/7 抓取热点股票池 …")
    pool = S.build_stock_pool()
    stocks = pool["pool"]
    log.info("股票池合并完成：A股 %d 只，港股 %d 只，合计 %d",
             pool["stats"]["merged_a"], pool["stats"]["merged_hk"], pool["stats"]["total"])

    # ---------- 2. 批量行情 ----------
    log.info("步骤 2/7 抓取批量行情 …")
    pairs = [(s["market"], s["code"]) for s in stocks]
    quotes = S.fetch_quotes_batch(pairs)
    log.info("行情获取 %d/%d", len(quotes), len(pairs))

    # ---------- 3. 逐只 K 线 + 财务 ----------
    log.info("步骤 3/7 抓取 K 线与财务（逐只，礼貌限速） …")
    stock_results = []
    for i, item in enumerate(stocks, 1):
        code, mkt = item["code"], item["market"]
        quote = quotes.get(code)
        try:
            klines = S.fetch_kline(mkt, code, C.KLINE_DAYS)
        except Exception as e:  # noqa: BLE001
            log.warning("K线失败 %s.%s: %s", mkt, code, e)
            klines = []
        try:
            fund = S.fetch_fundamentals(mkt, code)
        except Exception as e:  # noqa: BLE001
            log.warning("财务失败 %s.%s: %s", mkt, code, e)
            fund = {}
        try:
            res = A.analyze_stock(item, quote or {}, klines, fund)
            stock_results.append(res)
        except Exception as e:  # noqa: BLE001
            log.warning("分析失败 %s.%s: %s", mkt, code, e)
        if i % 25 == 0:
            log.info("  … 已处理 %d/%d", i, len(stocks))
    log.info("个股分析完成 %d 只", len(stock_results))

    # ---------- 4. 消息面 ----------
    log.info("步骤 4/7 抓取消息面 …")
    hours, window_desc = news_window_hours()
    news = S.fetch_news(hours_back=hours, page_size=100)
    sent = A.score_sentiment(news)
    log.info("消息 %d 条，情绪分 %s（%s）", len(news), sent["score"], sent["label"])

    # ---------- 5. 大盘预测（量化层 → LLM 研判可选增强） ----------
    log.info("步骤 5/7 大盘预测 …")
    index_data = S.fetch_indices()
    index_klines = {}
    for name, (secid, mkt_prefix) in S.INDEX_SECMAP.items():
        code = secid.split(".")[1]
        mkt = "SH" if mkt_prefix == "SH" else "SZ"
        index_klines[name] = S.fetch_kline(mkt, code, 120)
    market_fc = A.forecast_market(index_data, index_klines, index_data.get("breadth") or {}, sent)

    market_fc["engine"] = "rule"
    market_fc["llm_used"] = False
    if L.llm_enabled():
        log.info("  LLM 研判引擎：%s", L._model())
        md_lines = []
        for r in market_fc.get("index_rows") or []:
            md_lines.append(
                f"- {r['name']}: 现价{r['price']}, 5日{r['chg_5d']}%, 20日{r['chg_20d']}%, "
                f"MA20{'站上' if r['above20'] else '跌破'}, MA60{'站上' if r['above60'] else '跌破'}"
            )
        br = market_fc.get("breadth") or {}
        md_lines.append(
            f"- 市场广度: 上涨{br.get('up')} / 下跌{br.get('down')} / 平盘{br.get('flat')}"
            f"（占比{br.get('up_ratio')}%）"
        )
        llm_mkt = L.market_narrative(
            "\n".join(md_lines),
            f"情绪分{sent['score']}（{sent['label']}），样本{sent['count']}条；"
            f"利好关键词{[h['word'] for h in sent.get('pos_hits', [])]}；"
            f"利空关键词{[h['word'] for h in sent.get('neg_hits', [])]}",
            f"量化层结论：{market_fc.get('trend')}（综合分{market_fc.get('composite_score')}）；"
            f"依据：{'; '.join(market_fc.get('factors', [])[:3])}",
        )
        if llm_mkt:
            market_fc = {
                **market_fc,
                "trend": llm_mkt["trend"],
                "stance": llm_mkt.get("summary") or market_fc.get("stance"),
                "factors": llm_mkt.get("factors") or market_fc.get("factors"),
                "risks": llm_mkt.get("risks") or market_fc.get("risks"),
                "key_watch": llm_mkt.get("key_watch") or [],
                "confidence": llm_mkt.get("confidence"),
                "engine": llm_mkt.get("engine"),
                "llm_used": True,
            }
            log.info("  LLM 研判完成：%s（置信度 %s）", llm_mkt["trend"], llm_mkt["confidence"])
        else:
            log.info("  LLM 研判失败/无输出，保留规则结论")
    else:
        log.info("  LLM 未配置（LLM_API_BASE/LLM_API_KEY），使用规则叙事")

    # ---------- 6. 回测对账 ----------
    log.info("步骤 6/7 回测对账往期预测 …")
    bt = run_backtest(run_id)
    market_fc["backtest"] = bt

    # ---------- 7. 生成报告 + 落库 ----------
    log.info("步骤 7/7 生成 HTML 报告并落库 …")
    fetched_at = pool.get("fetched_at") or now.strftime("%Y-%m-%d %H:%M:%S")
    sources = [
        {"item": "热点 A 股池", "source": f'{C.SRC_EASTMONEY} / {C.SRC_THS}',
         "detail": "人气榜 + 热股榜，代码级去重合并", "fetched_at": fetched_at},
        {"item": "热点港股池", "source": C.SRC_EASTMONEY,
         "detail": "成交额榜 TOP100 + 涨幅榜 TOP50（热度代理口径）", "fetched_at": fetched_at},
        {"item": "个股行情/PE/PB", "source": C.SRC_TENCENT,
         "detail": "qt.gtimg.cn 批量快照", "fetched_at": fetched_at},
        {"item": "个股日线", "source": C.SRC_TENCENT,
         "detail": "web.ifzq.gtimg.cn 前复权日线 250 根", "fetched_at": fetched_at},
        {"item": "个股财务指标", "source": C.SRC_EASTMONEY,
         "detail": "F10 主要财务指标（ROE/增速/负债率/现金流）", "fetched_at": fetched_at},
        {"item": "消息面快讯", "source": C.SRC_EM_NEWS,
         "detail": f"7x24 快讯，窗口：{window_desc}", "fetched_at": fetched_at},
        {"item": "指数与市场广度", "source": C.SRC_EASTMONEY,
         "detail": "ulist.np 指数快照（含涨跌家数 f104/f105/f106）", "fetched_at": fetched_at},
        {"item": "研判引擎", "source": market_fc.get("engine", "rule"),
         "detail": "LLM 研判" if market_fc.get("llm_used") else "确定性规则（LLM 未启用）",
         "fetched_at": fetched_at},
    ]

    gaps = []
    no_fund = [s for s in stock_results if s["fundamental"].get("score") is None]
    if no_fund:
        gaps.append(f"财务数据缺口 {len(no_fund)} 只（含港股 F10 未覆盖标的），相关基本面层已标记「数据不足」")
    no_kline = [s for s in stock_results if s["technical"].get("score") is None]
    if no_kline:
        gaps.append(f"K线数据缺口 {len(no_kline)} 只，技术面层已标记「数据不足」")

    result = {
        "meta": {
            "run_id": run_id,
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "report_date": now.strftime("%Y-%m-%d"),
            "run_weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
            "news_window": window_desc,
        },
        "pool": pool,
        "market_forecast": market_fc,
        "stocks": stock_results,
        "news": {"count": len(news), "sentiment": sent},
        "news_list": news,
        "sources": sources,
        "gaps": gaps,
        "backtest": D.backtest_summary(),
    }

    html_text = R.render_report(result)
    json_text = json.dumps(result, ensure_ascii=False, indent=1, default=str)

    # 同时落文件（便于直接归档）与入库（便于统一备份）
    html_path = C.REPORTS_DIR / f"report_{run_id}.html"
    json_path = C.REPORTS_DIR / f"report_{run_id}.json"
    html_path.write_text(html_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    (C.REPORTS_DIR / "latest.txt").write_text(html_path.name, encoding="utf-8")

    result["_html_path"] = str(html_path)
    result["_html_text"] = html_text
    result["_json_text"] = json_text
    D.save_run(result)

    elapsed = time.time() - t0
    log.info("==== pipeline 完成 %s，耗时 %.1fs ====", html_path, elapsed)
    log.info("大盘判断：%s（综合分 %s，引擎 %s）",
             market_fc.get("trend"), market_fc.get("composite_score"), market_fc.get("engine"))
    return {
        "html": str(html_path), "json": str(json_path), "elapsed": elapsed,
        "stocks": len(stock_results), "market_trend": market_fc.get("trend"),
        "engine": market_fc.get("engine"), "backtest": bt,
    }


if __name__ == "__main__":
    try:
        summary = run()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.exit(0)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
