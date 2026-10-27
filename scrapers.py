"""数据抓取层：热股池 / 行情 / K线 / 财务 / 消息面 / 指数广度

所有函数返回 dict，并带 source / fetched_at 字段，保证可追溯。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

import config as C

log = logging.getLogger("scrapers")

_session = requests.Session()
_session.headers.update({
    "User-Agent": C.USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
})


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get(url: str, **kwargs) -> Any:
    """带重试与礼貌限速的 GET"""
    last_err = None
    for i in range(C.HTTP_RETRIES):
        try:
            time.sleep(C.REQUEST_INTERVAL)
            resp = _session.get(url, timeout=C.HTTP_TIMEOUT, **kwargs)
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype or resp.text[:1] in "{[":
                return resp.json()
            return resp.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(C.HTTP_BACKOFF * (i + 1))
    log.warning("GET 失败 %s: %s", url, last_err)
    return None


def _post_json(url: str, payload: dict, **kwargs) -> Any:
    last_err = None
    for i in range(C.HTTP_RETRIES):
        try:
            time.sleep(C.REQUEST_INTERVAL)
            resp = _session.post(url, json=payload, timeout=C.HTTP_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(C.HTTP_BACKOFF * (i + 1))
    log.warning("POST 失败 %s: %s", url, last_err)
    return None


# ============================================================
# 1. 热股池
# ============================================================

def fetch_em_popularity(market: str = "", page_size: int = 100) -> List[dict]:
    """东方财富人气榜（沪深）。返回 [{code, rank, source}]"""
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    data = _post_json(url, {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": market,
        "pageNo": 1,
        "pageSize": page_size,
    })
    out = []
    if not data or data.get("code") != 0:
        return out
    for item in data.get("data") or []:
        sc = (item.get("sc") or "").upper()  # 形如 SH600487 / SZ002085
        if len(sc) < 3:
            continue
        prefix, code = sc[:2], sc[2:]
        mkt = "SH" if prefix == "SH" else "SZ"
        out.append({
            "code": code,
            "market": mkt,
            "rank": item.get("rk"),
            "source": C.SRC_EASTMONEY,
            "source_detail": "人气榜",
        })
    return out


def fetch_ths_hot(stock_type: str = "a", page_size: int = 100) -> List[dict]:
    """同花顺热股榜。stock_type: a / hk(可能不可用)"""
    url = (
        "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock"
        f"?stock_type={stock_type}&type=hour&list_type=normal"
        f"&page_size={page_size}&page_num=1"
    )
    data = _get(url)
    out = []
    if not isinstance(data, dict) or data.get("status_code") != 0:
        return out
    for item in (data.get("data") or {}).get("stock_list") or []:
        code = str(item.get("code") or "").zfill(6)
        mkt_code = item.get("market")
        # 同花顺 market: 17=沪, 33=深；港股另行处理
        mkt = "SH" if mkt_code == 17 else "SZ" if mkt_code == 33 else "HK"
        if stock_type == "hk":
            mkt = "HK"
        out.append({
            "code": code,
            "market": mkt,
            "rank": item.get("order"),
            "name": item.get("name"),
            "source": C.SRC_THS,
            "source_detail": "热股榜",
            "tags": (item.get("tag") or {}).get("concept_tag") or [],
            "popularity": item.get("popularity_tag"),
            "heat": item.get("rate"),
        })
    return out


def fetch_em_hk_by_amount(page_size: int = 100) -> List[dict]:
    """港股热点代理：东财港股成交额榜（人气榜接口不覆盖港股，如实标注代理口径）"""
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f6"
        "&fs=m:116+t:3,m:116+t:4&fields=f2,f3,f5,f6,f12,f14"
    ).format(pz=page_size)
    data = _get(url)
    out = []
    if not data or not (data.get("data") or {}).get("diff"):
        return out
    for i, item in enumerate(data["data"]["diff"], 1):
        out.append({
            "code": str(item.get("f12") or "").zfill(5),
            "market": "HK",
            "rank": i,
            "name": item.get("f14"),
            "source": C.SRC_EASTMONEY,
            "source_detail": "成交额榜（热度代理）",
            "amount": item.get("f6"),
        })
    return out


def fetch_em_hk_by_change(page_size: int = 50) -> List[dict]:
    """港股热点代理补充：涨幅榜"""
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz={pz}&po=1&np=1&fltt=2&invt=2&fid=f3"
        "&fs=m:116+t:3,m:116+t:4&fields=f2,f3,f6,f12,f14"
    ).format(pz=page_size)
    data = _get(url)
    out = []
    if not data or not (data.get("data") or {}).get("diff"):
        return out
    for i, item in enumerate(data["data"]["diff"], 1):
        out.append({
            "code": str(item.get("f12") or "").zfill(5),
            "market": "HK",
            "rank": i,
            "name": item.get("f14"),
            "source": C.SRC_EASTMONEY,
            "source_detail": "涨幅榜（热度代理）",
        })
    return out


def build_stock_pool() -> Dict[str, Any]:
    """合并 A 股 + 港股热股，去重，标注来源与抓取时间。

    规则：
    - A 股：东财人气榜 TOP100 ∪ 同花顺热股 TOP100
    - 港股：东财成交额榜 TOP100 ∪ 涨幅榜 TOP50（人气榜不覆盖港股，如实标注为热度代理）
    - 去重：同一市场内按代码去重，保留排名靠前/来源更多的记录，合并来源
    """
    fetched_at = _now_iso()
    a_em = fetch_em_popularity("", C.TOP_N_A)
    a_ths = fetch_ths_hot("a", C.TOP_N_A)
    hk_amt = fetch_em_hk_by_amount(C.TOP_N_HK)
    hk_chg = fetch_em_hk_by_change(50)

    def _merge(lists: List[List[dict]], market: str) -> List[dict]:
        merged: Dict[str, dict] = {}
        for lst in lists:
            for item in lst:
                key = item["code"]
                # 保留标的自身的精确市场（SH/SZ/HK），分组标签只作兜底
                item_mkt = item.get("market") or market
                if key in merged:
                    # 合并来源
                    base = merged[key]
                    src_tag = f"{item['source_detail']}"
                    if src_tag not in base["sources_detail"]:
                        base["sources_detail"].append(src_tag)
                    if item.get("source") not in base["sources"]:
                        base["sources"].append(item["source"])
                    # 取更优排名
                    if item.get("rank") and (base.get("rank") is None or item["rank"] < base["rank"]):
                        base["rank"] = item["rank"]
                    # 补名称
                    if not base.get("name") and item.get("name"):
                        base["name"] = item["name"]
                    if item.get("tags") and not base.get("tags"):
                        base["tags"] = item["tags"]
                    if item.get("popularity") and not base.get("popularity"):
                        base["popularity"] = item["popularity"]
                else:
                    merged[key] = {
                        "code": item["code"],
                        "market": item_mkt,
                        "name": item.get("name"),
                        "rank": item.get("rank"),
                        "sources": [item["source"]],
                        "sources_detail": [item["source_detail"]],
                        "tags": item.get("tags") or [],
                        "popularity": item.get("popularity"),
                        "heat": item.get("heat"),
                    }
        result = list(merged.values())
        result.sort(key=lambda x: (x.get("rank") or 9999))
        return result

    pool_a = _merge([a_em, a_ths], "A")
    pool_hk = _merge([hk_amt, hk_chg], "HK")

    return {
        "fetched_at": fetched_at,
        "pool_a": pool_a,
        "pool_hk": pool_hk,
        "pool": pool_a + pool_hk,
        "stats": {
            "a_em": len(a_em), "a_ths": len(a_ths),
            "hk_amt": len(hk_amt), "hk_chg": len(hk_chg),
            "merged_a": len(pool_a), "merged_hk": len(pool_hk),
            "total": len(pool_a) + len(pool_hk),
        },
        "notes": [
            "A股池 = 东方财富人气榜 TOP100 ∪ 同花顺热股榜 TOP100，按代码去重合并来源",
            "港股池 = 东方财富成交额榜 TOP100 ∪ 涨幅榜 TOP50（东方财富人气榜接口不覆盖港股，"
            "同花顺港股热股接口当前返回 Param Error，故采用成交额/涨幅作为热点代理口径，已在表中标注）",
        ],
    }


# ============================================================
# 2. 行情快照（腾讯批量，A+港）
# ============================================================

def _infer_a_market(code: str) -> str:
    """按代码段推断沪深：6/9 开头→SH，其余（00/30/12…）→SZ"""
    return "SH" if code[:1] in ("6", "9") else "SZ"


def _to_tencent_symbol(market: str, code: str) -> str:
    m = (market or "").upper()
    if m == "HK":
        return f"hk{code}"
    if m == "SH":
        return f"sh{code}"
    if m == "SZ":
        return f"sz{code}"
    # 兜底：A / CN / 空 → 按代码段推断
    return ("sh" if _infer_a_market(code) == "SH" else "sz") + code


def parse_tencent_quote(raw_line: str) -> Optional[dict]:
    """解析腾讯 qt.gtimg.cn 单行行情。字段索引 A/港略有差异，做防御式提取。"""
    if "=" not in raw_line:
        return None
    body = raw_line.split("=", 1)[1].strip().strip(";").strip('"')
    if not body:
        return None
    f = body.split("~")
    if len(f) < 50:
        return None
    try:
        name = f[1]
        code = f[2]
        price = float(f[3]) if f[3] not in ("", "-") else None
        prev = float(f[4]) if f[4] not in ("", "-") else None
        # A 股字段：38=换手 39=PE 46=PB 44=流通市值 45=总市值
        # 港股字段布局不同，按数值合理性判断
        def _ff(idx):
            try:
                v = f[idx]
                return float(v) if v not in ("", "-", "--") else None
            except (ValueError, IndexError):
                return None

        pe = _ff(39)
        pb = _ff(46)
        if pe is not None and (pe < -500 or pe > 2000):
            pe = None
        if pb is not None and (pb < -50 or pb > 200):
            pb = None
        pct = _ff(32)
        chg = _ff(31)
        high = _ff(33)
        low = _ff(34)
        amount_wan = _ff(37)          # 成交额（万元）
        turnover = _ff(38)
        mcap_yi = _ff(45)             # 总市值（亿）
        return {
            "name": name, "code": code, "price": price, "prev_close": prev,
            "change_pct": pct, "change": chg, "high": high, "low": low,
            "amount_wan": amount_wan, "turnover": turnover,
            "pe_ttm": pe, "pb": pb, "mcap_yi": mcap_yi,
        }
    except (ValueError, IndexError):
        return None


def fetch_quotes_batch(pairs: List[tuple]) -> Dict[str, dict]:
    """批量行情。pairs: [(market, code), ...]，返回 {code: quote_dict}"""
    result: Dict[str, dict] = {}
    batch_size = 50
    for i in range(0, len(pairs), batch_size):
        chunk = pairs[i:i + batch_size]
        symbols = ",".join(_to_tencent_symbol(m, c) for m, c in chunk)
        url = f"https://qt.gtimg.cn/q={symbols}"
        text = _get(url)
        if not isinstance(text, str):
            continue
        # 腾讯返回 GBK；requests 可能已按 apparent encoding 转过
        if isinstance(text, bytes):
            text = text.decode("gbk", errors="replace")
        for line in text.splitlines():
            q = parse_tencent_quote(line)
            if q:
                result[q["code"]] = q
    return result


# ============================================================
# 3. K 线
# ============================================================

def fetch_kline(market: str, code: str, days: int = C.KLINE_DAYS) -> List[dict]:
    """日线（前复权）。返回 [{date, open, close, high, low, volume}, ...] 升序"""
    if market == "HK":
        symbol = f"hk{code}"
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get"
            f"?param={symbol},day,,,{days},qfq"
        )
        data = _get(url)
        if not isinstance(data, dict):
            return []
        node = (data.get("data") or {}).get(symbol) or {}
        rows = node.get("qfqday") or node.get("day") or []
    else:
        symbol = _to_tencent_symbol(market, code)
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={symbol},day,,,{days},qfq"
        )
        data = _get(url)
        if not isinstance(data, dict):
            return []
        node = (data.get("data") or {}).get(symbol) or {}
        rows = node.get("qfqday") or node.get("day") or []

    out = []
    for r in rows:
        try:
            out.append({
                "date": r[0],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 and r[5] not in ("", None) else 0.0,
            })
        except (ValueError, IndexError, TypeError):
            continue
    return out


# ============================================================
# 4. 财务（东财 F10）
# ============================================================

def _em_secucode(market: str, code: str) -> str:
    m = (market or "").upper()
    if m == "HK":
        return f"{code}.HK"
    if m == "SH":
        return f"{code}.SH"
    if m == "SZ":
        return f"{code}.SZ"
    return f"{code}.{_infer_a_market(code)}"


def fetch_fundamentals(market: str, code: str) -> Dict[str, Any]:
    """主要财务指标（最近报告期）。数据缺失返回 None，不填充。"""
    secucode = _em_secucode(market, code)
    url = (
        "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
        f"&filter=(SECUCODE%3D%22{secucode}%22)"
        "&pageNumber=1&pageSize=2&sortColumns=REPORT_DATE&sortTypes=-1"
        "&source=HSF10&client=PC"
    )
    data = _get(url, headers={"User-Agent": C.USER_AGENT})
    if not isinstance(data, dict):
        return {}
    rows = ((data.get("result") or {}).get("data")) or []
    if not rows:
        return {}
    r = rows[0]
    def _num(key):
        v = r.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    return {
        "report_date": (r.get("REPORT_DATE") or "")[:10],
        "report_type": r.get("REPORT_TYPE"),
        "roe": _num("ROEJQ"),                 # ROE 加权 %
        "gross_margin": _num("XSMLL"),        # 销售毛利率 %
        "net_margin": _num("XSJLL"),          # 销售净利率 %
        "debt_ratio": _num("ZCFZL"),          # 资产负债率 %
        "revenue_yoy": _num("TOTALOPERATEREVETZ"),   # 营收同比 %
        "profit_yoy": _num("PARENTNETPROFITTZ"),     # 归母净利同比 %
        "cf_to_revenue": _num("JYXJLYYSR"),  # 经营现金流/营收
        "eps": _num("EPSJB"),
        "bps": _num("BPS"),
        "source": C.SRC_EASTMONEY,
        "source_detail": "F10 主要财务指标",
    }


# ============================================================
# 5. 消息面（东财 7x24）
# ============================================================

def fetch_news(hours_back: int = 48, page_size: int = 100) -> List[dict]:
    """7x24 快讯，按时间窗过滤。"""
    url = (
        "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
        "?client=web&biz=web_724&column=350&order=1&needInteractData=0"
        f"&page_index=1&page_size={page_size}&req_trace={int(time.time())}"
    )
    data = _get(url, headers={"User-Agent": C.USER_AGENT})
    if not isinstance(data, dict):
        return []
    items = ((data.get("data") or {}).get("list")) or []
    cutoff = datetime.now() - timedelta(hours=hours_back)
    out = []
    for it in items:
        show = it.get("showTime") or ""
        try:
            dt = datetime.strptime(show, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if dt < cutoff:
            continue
        out.append({
            "time": show,
            "title": (it.get("title") or it.get("summary") or "")[:200],
            "summary": (it.get("summary") or "")[:400],
            "url": it.get("uniqueUrl") or "",
            "source": C.SRC_EM_NEWS,
        })
    return out


# ============================================================
# 6. 指数与市场广度
# ============================================================

INDEX_SECMAP = {
    "上证指数": ("1.000001", "SH"),
    "深证成指": ("0.399001", "SZ"),
    "创业板指": ("0.399006", "SZ"),
    "沪深300": ("1.000300", "SH"),
}


def fetch_indices() -> Dict[str, Any]:
    """沪深主要指数 + 恒生指数（腾讯快照）"""
    secids = ",".join(v[0] for v in INDEX_SECMAP.values())
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f13,f14,f104,f105,f106"
    )
    data = _get(url, headers={"User-Agent": C.USER_AGENT, "Referer": "https://quote.eastmoney.com/"})
    out: Dict[str, Any] = {"fetched_at": _now_iso(), "indices": {}, "breadth": {}}
    if isinstance(data, dict):
        for item in ((data.get("data") or {}).get("diff")) or []:
            name = item.get("f14")
            out["indices"][name] = {
                "price": item.get("f2"),
                "change_pct": item.get("f3"),
                "change": item.get("f4"),
                "code": item.get("f12"),
                "source": C.SRC_EASTMONEY,
            }
            if item.get("f104") is not None:
                out["breadth"][name] = {
                    "up": item.get("f104"),
                    "down": item.get("f105"),
                    "flat": item.get("f106"),
                }

    # 恒生 / 恒生科技（腾讯）
    text = _get("https://qt.gtimg.cn/q=hkHSI,hkHSTECH")
    if isinstance(text, str):
        for line in text.splitlines():
            q = parse_tencent_quote(line)
            if q:
                key = "恒生指数" if "HSI" in line.split("=")[0] and "TECH" not in line.split("=")[0] else "恒生科技指数"
                out["indices"][key] = {
                    "price": q["price"], "change_pct": q["change_pct"],
                    "change": q["change"], "code": q["code"],
                    "source": C.SRC_TENCENT,
                }
    return out


def fetch_index_kline(market: str = "SH", code: str = "000001", days: int = 120) -> List[dict]:
    """指数日线，用于趋势判断"""
    return fetch_kline(market, code, days)
