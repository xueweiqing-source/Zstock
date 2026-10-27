"""SQLite 数据层：运行记录 / 股票池 / 预测 / 回测 / 快讯

设计原则：
- 每期运行（run_id）为一个快照，预测结果落库以便回测
- 所有关键数字原样存储，不做二次加工，保证可追溯
- 回测字段（result_pct/hit）由后续运行回填
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import config as C

DB_PATH = C.DATA_DIR / "forecast.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    generated_at    TEXT,
    weekday         TEXT,
    news_window     TEXT,
    market_trend    TEXT,
    market_score    REAL,
    market_factors  TEXT,
    market_risks    TEXT,
    sentiment_score REAL,
    sentiment_label TEXT,
    news_count      INTEGER,
    stock_count     INTEGER,
    report_html     TEXT,
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS pool_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    code            TEXT,
    market          TEXT,
    name            TEXT,
    rank            INTEGER,
    sources         TEXT,
    sources_detail  TEXT,
    tags            TEXT,
    fetched_at      TEXT,
    UNIQUE(run_id, code, market)
);

CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    code            TEXT,
    market          TEXT,
    name            TEXT,
    direction       TEXT,
    confidence      TEXT,
    composite_score REAL,
    brief           TEXT,
    fund_score      REAL, fund_verdict TEXT, fund_dir TEXT,
    val_score       REAL, val_verdict TEXT, val_dir TEXT,
    tech_score      REAL, tech_verdict TEXT, tech_dir TEXT,
    price_at_pred   REAL,
    created_at      TEXT,
    result_pct      REAL,
    hit             INTEGER,
    result_date     TEXT,
    UNIQUE(run_id, code, market)
);

CREATE TABLE IF NOT EXISTS quotes_snap (
    run_id      TEXT,
    code        TEXT,
    market      TEXT,
    price       REAL,
    change_pct  REAL,
    pe_ttm      REAL,
    pb          REAL,
    ma20        REAL,
    ma60        REAL,
    rsi14       REAL,
    macd_hist   REAL,
    pos_52w     REAL,
    chg_5d      REAL,
    PRIMARY KEY (run_id, code, market)
);

CREATE TABLE IF NOT EXISTS news_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT,
    news_time   TEXT,
    title       TEXT,
    summary     TEXT,
    url         TEXT,
    source      TEXT
);

CREATE INDEX IF NOT EXISTS idx_pred_code ON predictions(code, market);
CREATE INDEX IF NOT EXISTS idx_pred_run ON predictions(run_id);
CREATE INDEX IF NOT EXISTS idx_pool_run ON pool_items(run_id);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_run(result: Dict[str, Any]) -> None:
    """把 pipeline 结果写入库"""
    meta = result["meta"]
    market = result.get("market_forecast") or {}
    sent = market.get("sentiment") or {}
    pool = result.get("pool") or {}
    stocks = result.get("stocks") or []
    news = result.get("news") or {}

    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO runs
               (run_id, generated_at, weekday, news_window, market_trend, market_score,
                market_factors, market_risks, sentiment_score, sentiment_label,
                news_count, stock_count, report_html, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                meta["run_id"], meta["generated_at"], meta.get("run_weekday"),
                meta.get("news_window"), market.get("trend"), market.get("composite_score"),
                json.dumps(market.get("factors") or [], ensure_ascii=False),
                json.dumps(market.get("risks") or [], ensure_ascii=False),
                sent.get("score"), sent.get("label"),
                news.get("count"), len(stocks),
                result.get("_html_path"),
                json.dumps(pool.get("notes") or [], ensure_ascii=False),
            ),
        )

        for item in pool.get("pool_a", []) + pool.get("pool_hk", []):
            conn.execute(
                """INSERT OR REPLACE INTO pool_items
                   (run_id, code, market, name, rank, sources, sources_detail, tags, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    meta["run_id"], item["code"], item["market"], item.get("name"),
                    item.get("rank"),
                    json.dumps(item.get("sources") or [], ensure_ascii=False),
                    json.dumps(item.get("sources_detail") or [], ensure_ascii=False),
                    json.dumps(item.get("tags") or [], ensure_ascii=False),
                    pool.get("fetched_at"),
                ),
            )

        for s in stocks:
            cv = s.get("cross") or {}
            fund = s.get("fundamental") or {}
            val = s.get("valuation") or {}
            tech = s.get("technical") or {}
            q = s.get("quote") or {}
            ts = s.get("tech_summary") or {}
            conn.execute(
                """INSERT OR REPLACE INTO predictions
                   (run_id, code, market, name, direction, confidence, composite_score, brief,
                    fund_score, fund_verdict, fund_dir,
                    val_score, val_verdict, val_dir,
                    tech_score, tech_verdict, tech_dir,
                    price_at_pred, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    meta["run_id"], s["code"], s["market"], s.get("name"),
                    cv.get("direction"), cv.get("confidence"), cv.get("composite_score"),
                    s.get("brief"),
                    fund.get("score"), fund.get("verdict"), fund.get("direction"),
                    val.get("score"), val.get("verdict"), val.get("direction"),
                    tech.get("score"), tech.get("verdict"), tech.get("direction"),
                    q.get("price"), meta["generated_at"],
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO quotes_snap
                   (run_id, code, market, price, change_pct, pe_ttm, pb,
                    ma20, ma60, rsi14, macd_hist, pos_52w, chg_5d)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    meta["run_id"], s["code"], s["market"],
                    q.get("price"), q.get("change_pct"), q.get("pe_ttm"), q.get("pb"),
                    ts.get("ma20"), ts.get("ma60"), ts.get("rsi14"),
                    ts.get("macd_hist"), ts.get("pos_52w"), ts.get("chg_5d"),
                ),
            )

        for n in (result.get("news_list") or []):
            conn.execute(
                """INSERT INTO news_items (run_id, news_time, title, summary, url, source)
                   VALUES (?,?,?,?,?,?)""",
                (meta["run_id"], n.get("time"), n.get("title"), n.get("summary"),
                 n.get("url"), n.get("source")),
            )


# ---------- 查询 ----------

def list_runs(limit: int = 30) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_run_predictions(run_id: str) -> List[Dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.*, q.price, q.change_pct, q.pe_ttm, q.pb, q.ma20, q.ma60,
                      q.rsi14, q.macd_hist, q.pos_52w, q.chg_5d
               FROM predictions p
               LEFT JOIN quotes_snap q
                 ON p.run_id=q.run_id AND p.code=q.code AND p.market=q.market
               WHERE p.run_id=?
               ORDER BY p.composite_score DESC""",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_stock_history(code: str, market: str, limit: int = 12) -> List[Dict]:
    """单只股票的历次预测记录（含回测结果与行情快照）"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.*, r.generated_at, r.market_trend, r.weekday,
                      q.price, q.change_pct, q.pe_ttm, q.pb,
                      q.ma20, q.ma60, q.rsi14, q.macd_hist, q.pos_52w, q.chg_5d
               FROM predictions p
               JOIN runs r ON p.run_id=r.run_id
               LEFT JOIN quotes_snap q
                 ON p.run_id=q.run_id AND p.code=q.code AND p.market=q.market
               WHERE p.code=? AND p.market=?
               ORDER BY r.generated_at DESC LIMIT ?""",
            (code, market, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_stock_pool_info(run_id: str, code: str, market: str) -> Optional[Dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM pool_items WHERE run_id=? AND code=? AND market=?",
            (run_id, code, market),
        ).fetchone()
        return dict(row) if row else None


def list_unverified_predictions(before_run_id: str) -> List[Dict]:
    """取指定 run 之前、尚未回填结果的预测"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM predictions
               WHERE result_pct IS NULL AND run_id < ?
               ORDER BY run_id""",
            (before_run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def record_result(pred_id: int, result_pct: float, hit: int, result_date: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE predictions
               SET result_pct=?, hit=?, result_date=?
               WHERE id=?""",
            (result_pct, hit, result_date, pred_id),
        )


def backtest_summary() -> Dict[str, Any]:
    """回测统计：总体 + 按方向 + 按置信度 + 按市场"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT direction, confidence, market, hit, result_pct FROM predictions WHERE hit IS NOT NULL"
        ).fetchall()
        rows = [dict(r) for r in rows]

        def _stat(items):
            n = len(items)
            if n == 0:
                return {"n": 0, "hit": 0, "rate": None, "avg_pct": None}
            hits = sum(1 for x in items if x["hit"] == 1)
            pcts = [x["result_pct"] for x in items if x["result_pct"] is not None]
            return {
                "n": n, "hit": hits,
                "rate": round(hits / n * 100, 1),
                "avg_pct": round(sum(pcts) / len(pcts), 2) if pcts else None,
            }

        by_dir = {}
        for d in ("看涨", "看跌", "震荡"):
            by_dir[d] = _stat([x for x in rows if x["direction"] == d])
        by_conf = {}
        for c in ("高", "中", "低"):
            by_conf[c] = _stat([x for x in rows if x["confidence"] == c])
        by_mkt = {}
        for m in ("SH", "SZ", "HK"):
            by_mkt[m] = _stat([x for x in rows if x["market"] == m])

        return {
            "total": _stat(rows),
            "by_direction": by_dir,
            "by_confidence": by_conf,
            "by_market": by_mkt,
        }
