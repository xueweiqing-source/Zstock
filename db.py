"""数据层：运行记录 / 股票池 / 预测 / 回测 / 快讯 / 报告

支持两种后端：
- **MySQL**（生产，Docker 编排）：设置 `DB_HOST` 即启用，pymysql 驱动
- **SQLite**（本地开发兜底）：未设置 `DB_HOST` 时使用 `data/forecast.db`

设计原则：
- 每期运行（run_id）为一个快照，预测结果落库以便回测
- 所有关键数字原样存储，不做二次加工，保证可追溯
- 回测字段（result_pct/hit）由后续运行回填
- 报告 HTML 一并入库，`mysqldump` 即完整备份
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import config as C

# ---------- 后端选择 ----------
DB_HOST = os.environ.get("DB_HOST", "").strip()
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "zstock")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "zstock")
USE_MYSQL = bool(DB_HOST)
DB_PATH = C.DATA_DIR / "forecast.db"   # SQLite 路径（仅非 MySQL 时使用）


# ============================================================
# 连接与游标
# ============================================================

@contextmanager
def get_conn():
    """统一连接入口，返回 dict 行的游标上下文"""
    if USE_MYSQL:
        import pymysql
        from pymysql.cursors import DictCursor
        conn = pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
            database=DB_NAME, charset="utf8mb4", cursorclass=DictCursor,
            autocommit=False, connect_timeout=10,
        )
    else:
        C.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=20)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _rows(cur) -> List[Dict]:
    """把游标结果统一成 list[dict]"""
    rs = cur.fetchall()
    out = []
    for r in rs:
        out.append(dict(r) if not isinstance(r, dict) else r)
    return out


def _q(sql: str) -> str:
    """占位符统一：统一写 `?`，MySQL 执行前转成 %s"""
    return sql.replace("?", "%s") if USE_MYSQL else sql


def _exec(conn, sql: str, params: tuple = ()):
    cur = conn.cursor()
    cur.execute(_q(sql), params)
    return cur


# ============================================================
# 建表
# ============================================================

SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          VARCHAR(32)  NOT NULL PRIMARY KEY,
    generated_at    VARCHAR(32),
    weekday         VARCHAR(16),
    news_window     VARCHAR(255),
    market_trend    VARCHAR(16),
    market_score    DOUBLE,
    market_factors  TEXT,
    market_risks    TEXT,
    sentiment_score DOUBLE,
    sentiment_label VARCHAR(32),
    news_count      INT,
    stock_count     INT,
    notes           TEXT,
    KEY idx_runs_time (generated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS reports (
    run_id      VARCHAR(32) NOT NULL PRIMARY KEY,
    html        LONGTEXT,
    json_data   LONGTEXT,
    created_at  VARCHAR(32),
    CONSTRAINT fk_reports_run FOREIGN KEY (run_id) REFERENCES runs(run_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pool_items (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_id          VARCHAR(32),
    code            VARCHAR(16),
    market          VARCHAR(8),
    name            VARCHAR(64),
    `rank`          INT,
    sources         TEXT,
    sources_detail  TEXT,
    tags            TEXT,
    fetched_at      VARCHAR(32),
    UNIQUE KEY uq_pool (run_id, code, market),
    KEY idx_pool_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS predictions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    run_id          VARCHAR(32),
    code            VARCHAR(16),
    market          VARCHAR(8),
    name            VARCHAR(64),
    direction       VARCHAR(16),
    confidence      VARCHAR(8),
    composite_score DOUBLE,
    brief           TEXT,
    fund_score      DOUBLE, fund_verdict VARCHAR(32), fund_dir VARCHAR(16),
    val_score       DOUBLE, val_verdict  VARCHAR(32), val_dir  VARCHAR(16),
    tech_score      DOUBLE, tech_verdict VARCHAR(32), tech_dir VARCHAR(16),
    price_at_pred   DOUBLE,
    created_at      VARCHAR(32),
    result_pct      DOUBLE,
    hit             INT,
    result_date     VARCHAR(32),
    UNIQUE KEY uq_pred (run_id, code, market),
    KEY idx_pred_code (code, market),
    KEY idx_pred_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quotes_snap (
    run_id      VARCHAR(32),
    code        VARCHAR(16),
    market      VARCHAR(8),
    price       DOUBLE,
    change_pct  DOUBLE,
    pe_ttm      DOUBLE,
    pb          DOUBLE,
    ma20        DOUBLE,
    ma60        DOUBLE,
    rsi14       DOUBLE,
    macd_hist   DOUBLE,
    pos_52w     DOUBLE,
    chg_5d      DOUBLE,
    PRIMARY KEY (run_id, code, market)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS news_items (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    run_id      VARCHAR(32),
    news_time   VARCHAR(32),
    title       VARCHAR(512),
    summary     TEXT,
    url         VARCHAR(512),
    source      VARCHAR(64),
    KEY idx_news_run (run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SCHEMA_SQLITE = """
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
    notes           TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    run_id      TEXT PRIMARY KEY,
    html        TEXT,
    json_data   TEXT,
    created_at  TEXT
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


def init_db():
    with get_conn() as conn:
        script = SCHEMA_MYSQL if USE_MYSQL else SCHEMA_SQLITE
        if USE_MYSQL:
            for stmt in [s.strip() for s in script.split(";") if s.strip()]:
                _exec(conn, stmt)
        else:
            conn.executescript(script)


# ============================================================
# 写入
# ============================================================

def save_run(result: Dict[str, Any]) -> None:
    meta = result["meta"]
    market = result.get("market_forecast") or {}
    sent = market.get("sentiment") or {}
    pool = result.get("pool") or {}
    stocks = result.get("stocks") or []
    news = result.get("news") or {}

    with get_conn() as conn:
        # runs
        if USE_MYSQL:
            _exec(conn, """
                INSERT INTO runs (run_id, generated_at, weekday, news_window,
                                  market_trend, market_score, market_factors, market_risks,
                                  sentiment_score, sentiment_label, news_count, stock_count, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON DUPLICATE KEY UPDATE
                    generated_at=VALUES(generated_at), weekday=VALUES(weekday),
                    news_window=VALUES(news_window), market_trend=VALUES(market_trend),
                    market_score=VALUES(market_score), market_factors=VALUES(market_factors),
                    market_risks=VALUES(market_risks), sentiment_score=VALUES(sentiment_score),
                    sentiment_label=VALUES(sentiment_label), news_count=VALUES(news_count),
                    stock_count=VALUES(stock_count), notes=VALUES(notes)
            """, (
                meta["run_id"], meta["generated_at"], meta.get("run_weekday"),
                meta.get("news_window"), market.get("trend"), market.get("composite_score"),
                json.dumps(market.get("factors") or [], ensure_ascii=False),
                json.dumps(market.get("risks") or [], ensure_ascii=False),
                sent.get("score"), sent.get("label"),
                news.get("count"), len(stocks),
                json.dumps(pool.get("notes") or [], ensure_ascii=False),
            ))
        else:
            _exec(conn, """INSERT OR REPLACE INTO runs
                (run_id, generated_at, weekday, news_window, market_trend, market_score,
                 market_factors, market_risks, sentiment_score, sentiment_label,
                 news_count, stock_count, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                meta["run_id"], meta["generated_at"], meta.get("run_weekday"),
                meta.get("news_window"), market.get("trend"), market.get("composite_score"),
                json.dumps(market.get("factors") or [], ensure_ascii=False),
                json.dumps(market.get("risks") or [], ensure_ascii=False),
                sent.get("score"), sent.get("label"),
                news.get("count"), len(stocks),
                json.dumps(pool.get("notes") or [], ensure_ascii=False),
            ))

        # reports（HTML + JSON 一并入库）
        html = result.get("_html_text") or ""
        json_text = result.get("_json_text") or ""
        if html or json_text:
            if USE_MYSQL:
                _exec(conn, """
                    INSERT INTO reports (run_id, html, json_data, created_at)
                    VALUES (?,?,?,?)
                    ON DUPLICATE KEY UPDATE html=VALUES(html), json_data=VALUES(json_data)
                """, (meta["run_id"], html, json_text, meta["generated_at"]))
            else:
                _exec(conn, """INSERT OR REPLACE INTO reports
                    (run_id, html, json_data, created_at) VALUES (?,?,?,?)""",
                    (meta["run_id"], html, json_text, meta["generated_at"]))

        # pool_items
        for item in pool.get("pool_a", []) + pool.get("pool_hk", []):
            params = (
                meta["run_id"], item["code"], item["market"], item.get("name"),
                item.get("rank"),
                json.dumps(item.get("sources") or [], ensure_ascii=False),
                json.dumps(item.get("sources_detail") or [], ensure_ascii=False),
                json.dumps(item.get("tags") or [], ensure_ascii=False),
                pool.get("fetched_at"),
            )
            if USE_MYSQL:
                _exec(conn, """INSERT INTO pool_items
                    (run_id, code, market, name, `rank`, sources, sources_detail, tags, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON DUPLICATE KEY UPDATE name=VALUES(name), `rank`=VALUES(`rank`)""", params)
            else:
                _exec(conn, """INSERT OR REPLACE INTO pool_items
                    (run_id, code, market, name, rank, sources, sources_detail, tags, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""", params)

        # predictions + quotes_snap
        for s in stocks:
            cv = s.get("cross") or {}
            fund = s.get("fundamental") or {}
            val = s.get("valuation") or {}
            tech = s.get("technical") or {}
            q = s.get("quote") or {}
            ts = s.get("tech_summary") or {}
            p_params = (
                meta["run_id"], s["code"], s["market"], s.get("name"),
                cv.get("direction"), cv.get("confidence"), cv.get("composite_score"),
                s.get("brief"),
                fund.get("score"), fund.get("verdict"), fund.get("direction"),
                val.get("score"), val.get("verdict"), val.get("direction"),
                tech.get("score"), tech.get("verdict"), tech.get("direction"),
                q.get("price"), meta["generated_at"],
            )
            if USE_MYSQL:
                _exec(conn, """INSERT INTO predictions
                    (run_id, code, market, name, direction, confidence, composite_score, brief,
                     fund_score, fund_verdict, fund_dir,
                     val_score, val_verdict, val_dir,
                     tech_score, tech_verdict, tech_dir,
                     price_at_pred, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON DUPLICATE KEY UPDATE
                        direction=VALUES(direction), confidence=VALUES(confidence),
                        composite_score=VALUES(composite_score), brief=VALUES(brief),
                        price_at_pred=VALUES(price_at_pred)""", p_params)
            else:
                _exec(conn, """INSERT OR REPLACE INTO predictions
                    (run_id, code, market, name, direction, confidence, composite_score, brief,
                     fund_score, fund_verdict, fund_dir,
                     val_score, val_verdict, val_dir,
                     tech_score, tech_verdict, tech_dir,
                     price_at_pred, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", p_params)

            q_params = (
                meta["run_id"], s["code"], s["market"],
                q.get("price"), q.get("change_pct"), q.get("pe_ttm"), q.get("pb"),
                ts.get("ma20"), ts.get("ma60"), ts.get("rsi14"),
                ts.get("macd_hist"), ts.get("pos_52w"), ts.get("chg_5d"),
            )
            if USE_MYSQL:
                _exec(conn, """INSERT INTO quotes_snap
                    (run_id, code, market, price, change_pct, pe_ttm, pb,
                     ma20, ma60, rsi14, macd_hist, pos_52w, chg_5d)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON DUPLICATE KEY UPDATE price=VALUES(price), change_pct=VALUES(change_pct)""",
                    q_params)
            else:
                _exec(conn, """INSERT OR REPLACE INTO quotes_snap
                    (run_id, code, market, price, change_pct, pe_ttm, pb,
                     ma20, ma60, rsi14, macd_hist, pos_52w, chg_5d)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", q_params)

        # news
        for n in (result.get("news_list") or []):
            _exec(conn, """INSERT INTO news_items
                (run_id, news_time, title, summary, url, source) VALUES (?,?,?,?,?,?)""",
                (meta["run_id"], n.get("time"), (n.get("title") or "")[:500],
                 (n.get("summary") or "")[:2000], n.get("url"), n.get("source")))


# ============================================================
# 查询
# ============================================================

def list_runs(limit: int = 30) -> List[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, "SELECT * FROM runs ORDER BY generated_at DESC LIMIT ?", (limit,))
        return _rows(cur)


def get_run(run_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, "SELECT * FROM runs WHERE run_id=?", (run_id,))
        rs = _rows(cur)
        return rs[0] if rs else None


def get_report_html(run_id: str) -> Optional[str]:
    with get_conn() as conn:
        cur = _exec(conn, "SELECT html FROM reports WHERE run_id=?", (run_id,))
        rs = _rows(cur)
        return rs[0].get("html") if rs else None


def get_run_predictions(run_id: str) -> List[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, """
            SELECT p.*, q.price, q.change_pct, q.pe_ttm, q.pb, q.ma20, q.ma60,
                   q.rsi14, q.macd_hist, q.pos_52w, q.chg_5d
            FROM predictions p
            LEFT JOIN quotes_snap q
              ON p.run_id=q.run_id AND p.code=q.code AND p.market=q.market
            WHERE p.run_id=?
            ORDER BY p.composite_score DESC""", (run_id,))
        return _rows(cur)


def get_stock_history(code: str, market: str, limit: int = 12) -> List[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, """
            SELECT p.*, r.generated_at, r.market_trend, r.weekday,
                   q.price, q.change_pct, q.pe_ttm, q.pb,
                   q.ma20, q.ma60, q.rsi14, q.macd_hist, q.pos_52w, q.chg_5d
            FROM predictions p
            JOIN runs r ON p.run_id=r.run_id
            LEFT JOIN quotes_snap q
              ON p.run_id=q.run_id AND p.code=q.code AND p.market=q.market
            WHERE p.code=? AND p.market=?
            ORDER BY r.generated_at DESC LIMIT ?""", (code, market, limit))
        return _rows(cur)


def get_stock_pool_info(run_id: str, code: str, market: str) -> Optional[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, "SELECT * FROM pool_items WHERE run_id=? AND code=? AND market=?",
                    (run_id, code, market))
        rs = _rows(cur)
        return rs[0] if rs else None


def list_unverified_predictions(before_run_id: str) -> List[Dict]:
    with get_conn() as conn:
        cur = _exec(conn, """
            SELECT * FROM predictions
            WHERE result_pct IS NULL AND run_id < ?
            ORDER BY run_id""", (before_run_id,))
        return _rows(cur)


def record_result(pred_id: int, result_pct: float, hit: int, result_date: str):
    with get_conn() as conn:
        _exec(conn, "UPDATE predictions SET result_pct=?, hit=?, result_date=? WHERE id=?",
              (result_pct, hit, result_date, pred_id))


def backtest_summary() -> Dict[str, Any]:
    with get_conn() as conn:
        cur = _exec(conn,
            "SELECT direction, confidence, market, hit, result_pct FROM predictions WHERE hit IS NOT NULL")
        rows = _rows(cur)

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

        by_dir = {d: _stat([x for x in rows if x["direction"] == d])
                  for d in ("看涨", "看跌", "震荡")}
        by_conf = {c: _stat([x for x in rows if x["confidence"] == c])
                   for c in ("高", "中", "低")}
        by_mkt = {m: _stat([x for x in rows if x["market"] == m])
                  for m in ("SH", "SZ", "HK")}

        return {
            "total": _stat(rows),
            "by_direction": by_dir,
            "by_confidence": by_conf,
            "by_market": by_mkt,
        }
