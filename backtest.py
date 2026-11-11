"""策略回测器：日线 K 线 + 持仓序列 → 绩效报告（纯 Python，零新增依赖）

执行口径（防未来函数）：
- t 日收盘生成信号（positions[t]）→ **t+1 日开盘**成交；最后一根的信号无法成交
- 全仓进出（1=满仓持有，0=空仓），A 股做空受限故 MVP 只做多
- 佣金 commission 双边收取；印花税 stamp_tax 仅卖出收取（默认 0.0005，2023 年后 A 股口径）
- 滑点 slippage_bps：买入开仓价上浮、卖出席位价下浮（默认 0）
- 收益曲线按每日收盘市值计算

策略输入是"事后可知的信号序列"时（如预测跟随），必须保证 positions[t] 只用
t 日收盘前可得的信息——本模块所有内置策略均满足该约束。
"""
from __future__ import annotations

import bisect
import math
from typing import Any, Dict, List, Optional, Tuple

TRADING_DAYS = 244          # 年化用交易日口径


# ============================================================
# 核心引擎
# ============================================================

def backtest(klines: List[dict], positions: List[int],
             init_cash: float = 1_000_000.0,
             commission: float = 0.0003,
             stamp_tax: float = 0.0005,
             slippage_bps: float = 0.0,
             stop_loss_pct: float = 0.0) -> Dict[str, Any]:
    """把持仓序列跑成资金曲线与绩效报告。

    klines: fetch_kline/get_klines 结构（升序 OHLCV）
    positions: 与 klines 等长的 0/1 序列，positions[t] 表示 t 日收盘后的持仓意图，
               在 t+1 日开盘成交。返回 {stats, trades, equity_curve, meta}。
    stop_loss_pct: 止损百分比（8.0 = 入场价下方 8% 止损），0=不启用。
        触发口径（日内）：持仓中当日 low 触及止损价即成交——跳空低开按开盘价、
        否则按止损价；成交当日不看信号。**止损后进入冷却**：信号转空之前不再
        入场（防止"止损后同一信号立刻买回"），信号出现过空仓后恢复。
    """
    n = len(klines)
    if n == 0 or len(positions) != n:
        raise ValueError("klines 与 positions 不能为空且长度必须一致")

    slip = slippage_bps / 10000.0
    stop_rate = (stop_loss_pct / 100.0) if stop_loss_pct and stop_loss_pct > 0 else 0.0
    cash = init_cash
    shares = 0.0
    stop_price: Optional[float] = None
    cooldown = False                      # 止损后冷却：信号转空前不再入场
    equity_curve: List[Tuple[str, float]] = []
    trades: List[Dict[str, Any]] = []
    open_trade: Optional[Dict[str, Any]] = None

    def _close_position(fill: float, date: str, reason: str) -> None:
        nonlocal cash, shares, open_trade, stop_price
        proceeds = shares * fill
        fee = proceeds * (commission + stamp_tax)
        cash += proceeds - fee
        if open_trade:
            trades.append({
                **open_trade,
                "exit_date": date, "exit_price": round(fill, 4),
                "exit_value": round(proceeds - fee, 2),
                "ret_pct": round(((proceeds - fee) / open_trade["entry_cost"] - 1.0) * 100, 2),
                "reason": reason,
            })
            open_trade = None
        shares = 0.0
        stop_price = None

    for t in range(n):
        # 1) 按上一根收盘的信号在本根开盘成交（无未来函数；止损冷却期不入场）
        if t > 0:
            want = 1 if positions[t - 1] else 0
            if cooldown:
                if want == 0:
                    cooldown = False      # 信号已转空，冷却解除
                want = 0                  # 冷却期内一律按空仓处理
            have = 1 if shares > 0 else 0
            if want != have:
                open_px = klines[t]["open"] or 0
                if open_px <= 0:
                    pass                    # 开盘价缺失则跳过本次调仓
                elif want == 1:
                    px = open_px * (1 + slip)
                    shares = cash / (px * (1 + commission))
                    cost = shares * px
                    cash -= cost * (1 + commission)
                    open_trade = {
                        "entry_date": klines[t]["date"], "entry_price": round(px, 4),
                        "shares": round(shares, 6), "entry_cost": round(cost * (1 + commission), 2),
                    }
                    stop_price = px * (1 - stop_rate) if stop_rate else None
                else:
                    _close_position(open_px * (1 - slip), klines[t]["date"], "signal")

        # 2) 日内止损：当日 low 触及止损价即成交（跳空低开按开盘价）
        if shares > 0 and stop_price:
            low_px = klines[t].get("low") or 0
            open_px = klines[t]["open"] or 0
            if 0 < low_px <= stop_price:
                fill = open_px if (0 < open_px < stop_price) else stop_price
                _close_position(fill, klines[t]["date"], "stop")
                cooldown = True

        # 3) 收盘估值
        close_px = klines[t]["close"] or 0
        equity_curve.append((klines[t]["date"], cash + shares * close_px))

    # 期末仍持仓 → 按最后收盘价标记未平仓交易（不计入胜率）
    if open_trade and shares > 0:
        last_close = klines[-1]["close"] or 0
        val = shares * last_close
        trades.append({
            **open_trade,
            "exit_date": None, "exit_price": None, "exit_value": round(val, 2),
            "ret_pct": round((val / open_trade["entry_cost"] - 1.0) * 100, 2),
            "open": True, "reason": "open",
        })

    stats = _stats(equity_curve, trades, init_cash, klines)
    return {
        "stats": stats,
        "trades": trades,
        "equity_curve": equity_curve,
        "meta": {
            "init_cash": init_cash, "commission": commission,
            "stamp_tax": stamp_tax, "slippage_bps": slippage_bps,
            "stop_loss_pct": stop_loss_pct,
            "bars": n, "start": klines[0]["date"], "end": klines[-1]["date"],
        },
    }


def _curve_stats(equity: List[Tuple[str, float]], init_cash: float) -> Dict[str, Any]:
    """资金曲线层面绩效：期末/累计/年化/最大回撤/夏普（组合与单标的共用）"""
    final = equity[-1][1]
    total_ret = final / init_cash - 1.0

    n = len(equity)
    years = n / TRADING_DAYS
    ann_ret = ((1 + total_ret) ** (1 / years) - 1.0) if (years > 0 and total_ret > -1) else None

    peak, max_dd = equity[0][1], 0.0
    for _, eq in equity:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)

    rets = [equity[i][1] / equity[i - 1][1] - 1.0
            for i in range(1, n) if equity[i - 1][1] > 0]
    sharpe = None
    if len(rets) >= 2:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        if sd > 0:
            sharpe = mean / sd * math.sqrt(TRADING_DAYS)

    return {
        "final_equity": round(final, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "ann_return_pct": round(ann_ret * 100, 2) if ann_ret is not None else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
    }


def _stats(equity: List[Tuple[str, float]], trades: List[Dict[str, Any]],
           init_cash: float, klines: List[dict]) -> Dict[str, Any]:
    out = _curve_stats(equity, init_cash)

    closed = [t for t in trades if not t.get("open")]
    wins = [t for t in closed if t["ret_pct"] > 0]
    losses = [t for t in closed if t["ret_pct"] <= 0]
    gross_win = sum(t["ret_pct"] for t in wins)
    gross_loss = abs(sum(t["ret_pct"] for t in losses))

    closes = [k["close"] for k in klines]
    buy_hold = closes[-1] / closes[0] - 1.0 if closes and closes[0] else None

    out.update({
        "buy_hold_pct": round(buy_hold * 100, 2) if buy_hold is not None else None,
        "excess_pct": round((out["total_return_pct"] / 100 - buy_hold) * 100, 2) if buy_hold is not None else None,
        "n_trades": len(closed),
        "n_open": sum(1 for t in trades if t.get("open")),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (None if not wins else float("inf")),
        "avg_win_pct": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss_pct": round(-gross_loss / len(losses), 2) if losses else None,
    })
    return out


# ============================================================
# 内置策略（positions[t] 只用 t 日收盘前信息）
# ============================================================

def ma_cross_positions(klines: List[dict], fast: int = 5, slow: int = 20) -> List[int]:
    """双均线：MA_fast 上穿 MA_slow 持仓，下穿空仓"""
    import indicators as ind
    closes = [k["close"] for k in klines]
    f = ind.ma_series(closes, fast)
    s = ind.ma_series(closes, slow)
    return [1 if (a is not None and b is not None and a > b) else 0
            for a, b in zip(f, s)]


def rsi_positions(klines: List[dict], period: int = 14,
                  low: float = 30.0, high: float = 70.0) -> List[int]:
    """RSI 均值回归：RSI 跌破 low 进场，升破 high 离场，其间维持原仓位"""
    import indicators as ind
    closes = [k["close"] for k in klines]
    rs = ind.rsi_series(closes, period)
    out: List[int] = []
    pos = 0
    for r in rs:
        if r is None:
            out.append(0)
            continue
        if r < low:
            pos = 1
        elif r > high:
            pos = 0
        out.append(pos)
    return out


def pred_positions(klines: List[dict],
                   preds: List[Dict[str, str]]) -> List[int]:
    """三层预测跟随：持有最近一次"看涨"预测，其余（看跌/震荡）空仓。

    preds: [{created_at: 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DD', direction: '看涨'...}]。
    生效对齐（严格无未来函数）：预测于盘后生成、目标是**次一交易日**——
    预测(P) 更新「最后一条日期 ≤ P 的 K 线」起的持仓意图，引擎在下一根 K 线
    开盘成交，恰好持有预测目标日。周末/节假日预测自动回溯到前一交易日生效
    （即下一交易日开盘成交）。同日多次预测按时间戳后者生效。
    """
    dates = [k["date"] for k in klines]
    events = []
    for p in preds:
        d = (p.get("created_at") or p.get("date") or "")[:10]
        if d:
            events.append((d, p.get("created_at") or d, p.get("direction") or ""))
    events.sort(key=lambda x: (x[0], x[1]))     # 同日多次预测按时间戳升序

    # 每条预测的有效 bar = 最后一根 date ≤ 预测日 的 K 线（非交易日回溯到前一交易日）
    eff = [bisect.bisect_right(dates, e[0]) - 1 for e in events]

    out: List[int] = [0] * len(klines)
    direction = ""
    ei = 0
    for t in range(len(klines)):
        while ei < len(events) and eff[ei] <= t:
            direction = events[ei][2]
            ei += 1
        out[t] = 1 if direction == "看涨" else 0
    return out


# ============================================================
# 全池预测跟随批量回测（P3）
# ============================================================

def _merge_curves(curves: List[Tuple[str, List[Tuple[str, float]]]],
                  sleeve_cash: float) -> List[Tuple[str, float]]:
    """多 sleeve 资金曲线按日合并：主日历=日期并集，缺日沿用前值（停牌近似），
    标的数据开始前记 sleeve_cash。返回组合曲线。"""
    master = sorted({d for _, curve in curves for d, _ in curve})
    data = [curve for _, curve in curves]
    ptr = [0] * len(data)
    last = [sleeve_cash] * len(data)
    merged: List[Tuple[str, float]] = []
    for d in master:
        total = 0.0
        for i, curve in enumerate(data):
            while ptr[i] < len(curve) and curve[ptr[i]][0] <= d:
                last[i] = curve[ptr[i]][1]
                ptr[i] += 1
            total += last[i]
        merged.append((d, total))
    return merged


def _direction_stats(klines_map: Dict[tuple, List[dict]],
                     preds_map: Dict[tuple, List[Dict]]) -> Dict[str, Any]:
    """按预测方向统计前瞻实际收益：次日（预测目标日）与 5 日均值/胜率"""
    buckets = {d: {"n1": [], "n5": []} for d in ("看涨", "看跌", "震荡")}
    for key, preds in preds_map.items():
        klines = klines_map.get(key)
        if not klines:
            continue
        dates = [k["date"] for k in klines]
        closes = [k["close"] for k in klines]
        for p in preds:
            d0 = (p.get("created_at") or p.get("date") or "")[:10]
            direction = p.get("direction") or ""
            if not d0 or direction not in buckets:
                continue
            eff = bisect.bisect_right(dates, d0) - 1   # 预测生效 bar（基准收盘）
            if eff < 0 or eff + 1 >= len(klines):
                continue
            r1 = closes[eff + 1] / closes[eff] - 1.0
            buckets[direction]["n1"].append(r1)
            e5 = min(eff + 5, len(klines) - 1)
            if e5 > eff:
                buckets[direction]["n5"].append(closes[e5] / closes[eff] - 1.0)

    out: Dict[str, Any] = {}
    for d, b in buckets.items():
        n1, n5 = b["n1"], b["n5"]
        out[d] = {
            "n": len(n1),
            "next1_avg_pct": round(sum(n1) / len(n1) * 100, 2) if n1 else None,
            "next1_win_pct": round(sum(1 for x in n1 if x > 0) / len(n1) * 100, 1) if n1 else None,
            "next5_avg_pct": round(sum(n5) / len(n5) * 100, 2) if n5 else None,
        }
    return out


def weighted_pool_curve(klines_map: Dict[tuple, List[dict]],
                        preds_map: Dict[tuple, List[Dict]],
                        init_cash: float = 1_000_000.0,
                        commission: float = 0.0003,
                        stamp_tax: float = 0.0005) -> Optional[Dict[str, Any]]:
    """置信度加权日频调仓组合（收盘近似口径）。

    每日收盘按「最新一条预测（≤ 前一交易日）为看涨」的标的构建持仓，权重 ∝
    置信度分（confidence_score，缺失时按 高/中/低 = 3/2/1）：
    - 组合日收益 = Σ w_i(t-1)·r_i(t) − 调仓费用（佣金双边 + 卖出印花，按权重换手计）
    - r_i(t) 为标的 t 日收盘收益；停牌沿用前值（0 收益），数据开始前不参与
    - 与单标的引擎"预测次日生效"口径一致；属近似模拟（无逐笔成交），
      与 sleeve 等权组合（逐笔全仓）互为参照
    """
    master = sorted({d for kl in klines_map.values() for k in kl for d in [k["date"]]})
    if len(master) < 2:
        return None

    series: Dict[tuple, List[Optional[float]]] = {}
    events: Dict[tuple, List[tuple]] = {}
    for key, kl in klines_map.items():
        if not kl:
            continue
        closes = {k["date"]: k["close"] for k in kl}
        arr: List[Optional[float]] = []
        last = None
        for d in master:
            if d in closes:
                last = closes[d]
            arr.append(last)
        series[key] = arr
        ev = []
        for p in preds_map.get(key) or []:
            d0 = (p.get("created_at") or p.get("date") or "")[:10]
            if not d0:
                continue
            score = p.get("confidence_score")
            if not isinstance(score, (int, float)) or score <= 0:
                score = {"高": 3.0, "中": 2.0, "低": 1.0}.get(p.get("confidence") or "", 1.0)
            ev.append((d0, p.get("direction") or "", float(score)))
        ev.sort(key=lambda x: x[0])
        events[key] = ev

    keys = list(series.keys())
    if not keys:
        return None
    ptr = {k: 0 for k in keys}
    state: Dict[tuple, tuple] = {k: ("", 1.0) for k in keys}

    def _weights(upto_date: str) -> Dict[tuple, float]:
        """推进状态到 upto_date（含），返回看涨标的的置信度归一权重"""
        scores = {}
        for k in keys:
            ev = events[k]
            while ptr[k] < len(ev) and ev[ptr[k]][0] <= upto_date:
                state[k] = (ev[ptr[k]][1], ev[ptr[k]][2])
                ptr[k] += 1
            direction, score = state[k]
            # 参与条件：最新预测看涨，且 upto_date 与下一交易日均有价（后判）
            if direction == "看涨":
                scores[k] = score
        if not scores:
            return {}
        total = sum(scores.values())
        return {k: v / total for k, v in scores.items()}

    equity = init_cash
    curve: List[Tuple[str, float]] = [(master[0], equity)]
    w_prev = _weights(master[0])
    for t in range(1, len(master)):
        w_now = _weights(master[t - 1])           # 本交易日持仓（t-1 收盘定权）
        gross = 0.0
        for k, w in w_now.items():
            c0, c1 = series[k][t - 1], series[k][t]
            if c0 and c1 and c0 > 0:
                gross += w * (c1 / c0 - 1.0)
        buys = sum(max(0.0, w_now.get(k, 0.0) - w_prev.get(k, 0.0)) for k in keys)
        sells = sum(max(0.0, w_prev.get(k, 0.0) - w_now.get(k, 0.0)) for k in keys)
        net = gross - commission * (buys + sells) - stamp_tax * sells
        equity *= (1.0 + net)
        curve.append((master[t], equity))
        w_prev = w_now

    return {"stats": _curve_stats(curve, init_cash), "equity_curve": curve}


def pred_pool_report(klines_map: Dict[tuple, List[dict]],
                     preds_map: Dict[tuple, List[Dict]],
                     init_cash: float = 1_000_000.0,
                     commission: float = 0.0003,
                     stamp_tax: float = 0.0005,
                     slippage_bps: float = 0.0,
                     min_bars: int = 30,
                     stop_loss_pct: float = 0.0,
                     include_weighted: bool = False) -> Dict[str, Any]:
    """全池三层预测跟随批量回测——回答"跟预测操作到底赚不赚钱"。

    klines_map / preds_map: {(code, market): [...]}；min_bars 以下的标的跳过。
    stop_loss_pct: 逐标的 sleeve 回测的止损百分比（0=关）。
    include_weighted: 附带置信度加权组合（近似口径，见 weighted_pool_curve）。
    - per_stock：逐标的 pred_follow 回测（复用单标的引擎，口径一致）
    - portfolio：**sleeve 等权组合**——总资金均分各标的独立跑后曲线合并，
      基准=等权买入持有（同 universe、同区间）
    - direction_stats：看涨/看跌/震荡 预测后的实际次日/5日收益
    """
    per_stock: List[Dict[str, Any]] = []
    curves: List[Tuple[str, List[Tuple[str, float]]]] = []
    bench_curves: List[Tuple[str, List[Tuple[str, float]]]] = []
    n_preds_total = 0

    for key in sorted(klines_map.keys()):
        code, market = key
        klines = klines_map[key]
        preds = preds_map.get(key) or []
        if len(klines) < min_bars or not preds:
            continue
        n_preds_total += len(preds)
        positions = pred_positions(klines, preds)
        r = backtest(klines, positions, init_cash=1.0,   # 份额化：1 元起算，合并时缩放
                     commission=commission, stamp_tax=stamp_tax, slippage_bps=slippage_bps,
                     stop_loss_pct=stop_loss_pct)
        s = r["stats"]
        per_stock.append({
            "code": code, "market": market, "bars": len(klines),
            "n_preds": len(preds),
            "n_bull": sum(1 for p in preds if (p.get("direction") or "") == "看涨"),
            "pred_return_pct": s["total_return_pct"],
            "buy_hold_pct": s["buy_hold_pct"],
            "excess_pct": s["excess_pct"],
            "max_dd_pct": s["max_drawdown_pct"],
            "n_trades": s["n_trades"], "win_rate": s["win_rate_pct"],
        })
        # sleeve 曲线按 1 元份额生成，合并后乘 sleeve_cash 即得等权组合
        curves.append((code, r["equity_curve"]))
        c0 = klines[0]["close"]
        bench_curves.append((code, [(k["date"], k["close"] / c0) for k in klines]))

    if not per_stock:
        return {"per_stock": [], "portfolio": None, "weighted": None, "direction_stats": {},
                "meta": {"n_stocks": 0, "n_preds": 0}}

    n = len(per_stock)
    sleeve_cash = init_cash / n
    portfolio_curve = _merge_curves(curves, 1.0)        # 1 元份额合并
    portfolio_curve = [(d, v * sleeve_cash) for d, v in portfolio_curve]
    bench_curve = _merge_curves(bench_curves, 1.0)
    bench_curve = [(d, v * sleeve_cash) for d, v in bench_curve]

    pstats = _curve_stats(portfolio_curve, init_cash)
    bstats = _curve_stats(bench_curve, init_cash)
    pstats["buy_hold_pct"] = bstats["total_return_pct"]
    pstats["excess_pct"] = round(pstats["total_return_pct"] - bstats["total_return_pct"], 2)

    weighted = None
    if include_weighted:
        weighted = weighted_pool_curve(klines_map, preds_map, init_cash=init_cash,
                                       commission=commission, stamp_tax=stamp_tax)

    return {
        "per_stock": per_stock,
        "portfolio": {
            "stats": pstats,
            "equity_curve": portfolio_curve,
            "bench_curve": bench_curve,
        },
        "weighted": weighted,
        "direction_stats": _direction_stats(klines_map, preds_map),
        "meta": {
            "n_stocks": n, "n_preds": n_preds_total,
            "init_cash": init_cash, "commission": commission,
            "stamp_tax": stamp_tax, "slippage_bps": slippage_bps,
            "stop_loss_pct": stop_loss_pct,
            "start": portfolio_curve[0][0], "end": portfolio_curve[-1][0],
        },
    }


def load_pool_from_db(since: str = "") -> tuple:
    """从 DB 加载全池预测与对应 K 线：返回 (klines_map, preds_map)。

    since 过滤预测（created_at >= since）与 K 线起点。predictions 表只存置信度
    标签（高/中/低），加权时按标签映射 3/2/1。
    """
    import db as D
    D.init_db()
    with D.get_conn() as conn:
        sql = ("SELECT code, market, created_at, direction, confidence FROM predictions"
               + (" WHERE created_at >= ?" if since else "")
               + " ORDER BY code, market, created_at")
        rows = D._rows(D._exec(conn, sql, (since,) if since else ()))
    preds_map: Dict[tuple, list] = {}
    for r in rows:
        preds_map.setdefault((r["code"], r["market"]), []).append(r)
    klines_map = {key: D.get_klines(key[0], key[1], start=since) for key in preds_map}
    return klines_map, preds_map


# ============================================================
# CLI：python backtest.py --code 600519.SH --strategy ma
# ============================================================

STRATEGIES = ("ma", "rsi", "pred")


def _fmt_report(result: Dict[str, Any], label: str) -> str:
    s = result["stats"]
    m = result["meta"]
    lines = [
        f"策略: {label}   区间: {m['start']} ~ {m['end']}（{m['bars']} 根）",
        f"初始资金 {m['init_cash']:,.0f} → 期末 {s['final_equity']:,.0f}",
        f"累计收益 {s['total_return_pct']:+.2f}%  | 年化 {('%+.2f%%' % s['ann_return_pct']) if s['ann_return_pct'] is not None else 'n/a'}"
        f"  | 买入持有 {s['buy_hold_pct']:+.2f}%  | 超额 {s['excess_pct']:+.2f}%",
        f"最大回撤 {s['max_drawdown_pct']:.2f}%  | 夏普 {s['sharpe'] if s['sharpe'] is not None else 'n/a'}"
        f"  | 交易 {s['n_trades']} 笔（未平仓 {s['n_open']}）"
        f"  | 胜率 {s['win_rate_pct'] if s['win_rate_pct'] is not None else 'n/a'}"
        f"  | 盈亏比 {s['profit_factor']}",
    ]
    if result["trades"]:
        reason_cn = {"stop": "止损", "signal": "信号", "open": "持仓"}
        lines.append("")
        lines.append(f"{'#':>2}  {'开仓日':<11} {'平仓日':<11} {'开仓价':>10} {'平仓价':>10} {'收益':>8} {'原因':>4}")
        for i, t in enumerate(result["trades"], 1):
            exit_d = t["exit_date"] or "（持仓中）"
            exit_p = f"{t['exit_price']:.2f}" if t["exit_price"] is not None else "—"
            reason = reason_cn.get(t.get("reason"), "")
            lines.append(
                f"{i:>2}  {t['entry_date']:<11} {exit_d:<11} {t['entry_price']:>10.2f} "
                f"{exit_p:>10} {t['ret_pct']:>7.2f}% {reason:>4}"
            )
    return "\n".join(lines)


def _fmt_pool_report(rep: Dict[str, Any]) -> str:
    m = rep["meta"]
    stop_txt = f"  止损 {m['stop_loss_pct']:g}%" if m.get("stop_loss_pct") else ""
    lines = ["==== 全池预测跟随回测（等权 sleeve 组合） ===="]
    lines.append(f"标的 {m['n_stocks']} 只  预测 {m['n_preds']} 条  区间 {m.get('start', '')} ~ {m.get('end', '')}{stop_txt}")
    if rep.get("portfolio"):
        s = rep["portfolio"]["stats"]
        ann = f"{s['ann_return_pct']:+.2f}%" if s["ann_return_pct"] is not None else "n/a"
        lines.append(f"组合: {m['init_cash']:,.0f} → {s['final_equity']:,.0f}  "
                     f"累计 {s['total_return_pct']:+.2f}%  | 年化 {ann}  | "
                     f"最大回撤 {s['max_drawdown_pct']:.2f}%  | 夏普 {s['sharpe']}")
        lines.append(f"等权买入持有基准: {s['buy_hold_pct']:+.2f}%  | 超额 {s['excess_pct']:+.2f}%")
    w = rep.get("weighted")
    if w:
        ws = w["stats"]
        w_ann = f"{ws['ann_return_pct']:+.2f}%" if ws["ann_return_pct"] is not None else "n/a"
        diff = ws["total_return_pct"] - rep["portfolio"]["stats"]["total_return_pct"]
        lines.append(f"置信度加权组合: 累计 {ws['total_return_pct']:+.2f}%  | 年化 {w_ann}  | "
                     f"最大回撤 {ws['max_drawdown_pct']:.2f}%  | 夏普 {ws['sharpe']}  | "
                     f"较等权 {diff:+.2f}%（日频近似口径）")

    ds = rep.get("direction_stats") or {}
    if ds:
        lines += ["", "分方向前瞻收益（生效bar收盘 → 次日/5日收盘）:"]
        lines.append(f"{'方向':<4} {'样本':>6} {'次日均':>9} {'次日胜率':>9} {'5日均':>9}")
        for d in ("看涨", "看跌", "震荡"):
            x = ds.get(d) or {}
            n = x.get("n", 0)
            f1 = f"{x['next1_avg_pct']:+.2f}%" if x.get("next1_avg_pct") is not None else "—"
            fw = f"{x['next1_win_pct']:.1f}%" if x.get("next1_win_pct") is not None else "—"
            f5 = f"{x['next5_avg_pct']:+.2f}%" if x.get("next5_avg_pct") is not None else "—"
            lines.append(f"{d:<4} {n:>6} {f1:>9} {fw:>9} {f5:>9}")

    if rep.get("per_stock"):
        ps = sorted(rep["per_stock"], key=lambda r: (r["excess_pct"] is None, -(r["excess_pct"] or 0)))
        lines += ["", "分标的（按超额降序）:"]
        lines.append(f"{'code':<8} {'mkt':<4} {'预测':>5} {'看涨':>5} {'策略':>9} {'买入持有':>9} {'超额':>8} {'交易':>5} {'胜率':>6}")
        for r in ps:
            wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "—"
            lines.append(
                f"{r['code']:<8} {r['market']:<4} {r['n_preds']:>5} {r['n_bull']:>5} "
                f"{r['pred_return_pct']:>+8.2f}% {r['buy_hold_pct']:>+8.2f}% "
                f"{r['excess_pct']:>+7.2f}% {r['n_trades']:>5} {wr:>6}")
    return "\n".join(lines)


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="K 线策略回测（数据来自 klines 表）")
    ap.add_argument("--code", default="", help="标的，如 600519.SH / 00700.HK（单标的模式）")
    ap.add_argument("--pool", action="store_true",
                    help="全池预测跟随批量回测（组合+分标的+分方向），需 predictions 数据")
    ap.add_argument("--strategy", default="ma", choices=STRATEGIES,
                    help="ma=双均线 rsi=均值回归 pred=三层预测跟随")
    ap.add_argument("--fast", type=int, default=5, help="ma 策略快线（默认 5）")
    ap.add_argument("--slow", type=int, default=20, help="ma 策略慢线（默认 20）")
    ap.add_argument("--rsi-period", type=int, default=14)
    ap.add_argument("--rsi-low", type=float, default=30.0)
    ap.add_argument("--rsi-high", type=float, default=70.0)
    ap.add_argument("--since", default="", help="只回测该日期之后（含）")
    ap.add_argument("--init-cash", type=float, default=1_000_000.0)
    ap.add_argument("--commission", type=float, default=0.0003, help="单边佣金，默认 万三")
    ap.add_argument("--stamp-tax", type=float, default=0.0005, help="卖出印花税，默认 万五")
    ap.add_argument("--slippage-bps", type=float, default=0.0)
    ap.add_argument("--stop-loss", type=float, default=0.0,
                    help="止损百分比：8 = 入场价下方 8%% 触发止损（0=关闭；触发后信号转空前不再入场）")
    ap.add_argument("--weighted", action="store_true",
                    help="全池模式附带置信度加权组合（日频近似口径）")
    ap.add_argument("--json", default="", help="完整报告（含资金曲线）另存 JSON")
    args = ap.parse_args()

    import db as D
    D.init_db()

    # ---------- 全池模式 ----------
    if args.pool:
        klines_map, preds_map = load_pool_from_db(args.since)
        if not preds_map:
            print("无可回测标的：predictions 表无记录，先跑几期 pipeline。")
            return 1
        rep = pred_pool_report(klines_map, preds_map, init_cash=args.init_cash,
                               commission=args.commission, stamp_tax=args.stamp_tax,
                               slippage_bps=args.slippage_bps,
                               stop_loss_pct=args.stop_loss,
                               include_weighted=args.weighted)
        if not rep["meta"]["n_stocks"]:
            print("无可回测标的：需要 predictions 记录 + 对应 klines（先跑回补与 pipeline）。")
            return 1
        print(_fmt_pool_report(rep))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=1)
            print(f"\n完整报告已写入 {args.json}")
        return 0

    # ---------- 单标的模式 ----------
    if not args.code:
        print("单标的模式需要 --code（或用 --pool 跑全池）。")
        return 1
    code, market = args.code.rsplit(".", 1)
    market = market.upper()
    klines = D.get_klines(code, market, start=args.since)
    if len(klines) < 30:
        print(f"klines 数据不足（{len(klines)} 根）：先跑 deploy/backfill_klines.py 回补。")
        return 1

    if args.strategy == "ma":
        positions = ma_cross_positions(klines, args.fast, args.slow)
        label = f"ma_cross({args.fast},{args.slow})"
    elif args.strategy == "rsi":
        positions = rsi_positions(klines, args.rsi_period, args.rsi_low, args.rsi_high)
        label = f"rsi({args.rsi_period},{args.rsi_low:g},{args.rsi_high:g})"
    else:
        with D.get_conn() as conn:
            cur = D._exec(conn, """
                SELECT p.created_at, p.direction FROM predictions p
                WHERE p.code=? AND p.market=? ORDER BY p.created_at""", (code, market))
            preds = D._rows(cur)
        if not preds:
            print(f"predictions 表无 {code}.{market} 的预测记录，pred 策略无信号。")
            return 1
        positions = pred_positions(klines, preds)
        label = f"pred_follow({len(preds)} 条预测)"

    result = backtest(klines, positions, init_cash=args.init_cash,
                      commission=args.commission, stamp_tax=args.stamp_tax,
                      slippage_bps=args.slippage_bps,
                      stop_loss_pct=args.stop_loss)
    print(_fmt_report(result, label))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({**result, "label": label, "code": args.code}, f,
                      ensure_ascii=False, indent=1)
        print(f"\n完整报告已写入 {args.json}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
