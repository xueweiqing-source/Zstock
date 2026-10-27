"""技术指标：MA / MACD / RSI / KDJ（输入为升序日线列表）"""
from __future__ import annotations

from typing import Dict, List, Optional


def _closes(klines: List[dict]) -> List[float]:
    return [k["close"] for k in klines]


def ma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ma_series(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= period:
            acc -= values[i - period]
            out.append(acc / period)
        elif i == period - 1:
            out.append(acc / period)
        else:
            out.append(None)
    return out


def macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif_list, dea_list, hist_list)，与国内口径一致（EMA12/26，DEA=EMA9(DIF)）"""
    n = len(values)
    if n < slow + signal:
        return [], [], []

    def ema_series(vals, period):
        k = 2.0 / (period + 1)
        emas = [vals[0]]
        for v in vals[1:]:
            emas.append(v * k + emas[-1] * (1 - k))
        return emas

    ema_fast = ema_series(values, fast)
    ema_slow = ema_series(values, slow)
    dif = [a - b for a, b in zip(ema_fast, ema_slow)]
    dea = ema_series(dif, signal)
    hist = [2 * (d - e) for d, e in zip(dif, dea)]
    return dif, dea, hist


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def kdj(klines: List[dict], n: int = 9, m1: int = 3, m2: int = 3):
    """返回 (K, D, J)，国内常用 RSV→SMA 平滑口径"""
    if len(klines) < n:
        return None, None, None
    k, d = 50.0, 50.0
    for i in range(n - 1, len(klines)):
        window = klines[i - n + 1:i + 1]
        hh = max(x["high"] for x in window)
        ll = min(x["low"] for x in window)
        rsv = (klines[i]["close"] - ll) / (hh - ll) * 100 if hh > ll else 50.0
        k = (m1 - 1) / m1 * k + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d + 1 / m2 * k
    j = 3 * k - 2 * d
    return round(k, 2), round(d, 2), round(j, 2)


def compute_all(klines: List[dict]) -> Dict:
    """一次性计算技术指标包"""
    if not klines:
        return {}
    closes = _closes(klines)
    price = closes[-1]
    out: Dict = {
        "price": price,
        "date": klines[-1]["date"],
        "ma5": ma(closes, 5),
        "ma20": ma(closes, 20),
        "ma60": ma(closes, 60),
        "ma120": ma(closes, 120),
        "ma250": ma(closes, 250) if len(closes) >= 250 else None,
        "rsi14": rsi(closes, 14),
    }
    dif, dea, hist = macd(closes)
    if hist:
        out["macd_dif"] = round(dif[-1], 4)
        out["macd_dea"] = round(dea[-1], 4)
        out["macd_hist"] = round(hist[-1], 4)
    else:
        out["macd_dif"] = out["macd_dea"] = out["macd_hist"] = None

    k, d, j = kdj(klines)
    out["kdj_k"], out["kdj_d"], out["kdj_j"] = k, d, j

    # 52 周（约 250 交易日）区间位置，收盘口径
    win = closes[-250:] if len(closes) >= 250 else closes
    hi, lo = max(win), min(win)
    out["high_52w"] = hi
    out["low_52w"] = lo
    out["pos_52w"] = round((price - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0

    # 量能：5 日均量 vs 20 日均量
    vols = [k["volume"] for k in klines]
    v5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
    v20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    out["vol_ratio"] = round(v5 / v20, 2) if (v5 and v20 and v20 > 0) else None

    # 近 5 / 20 日涨幅（用原始收盘价重算）
    if len(closes) >= 6:
        out["chg_5d"] = round((closes[-1] / closes[-6] - 1) * 100, 2)
    if len(closes) >= 21:
        out["chg_20d"] = round((closes[-1] / closes[-21] - 1) * 100, 2)

    return out
