#!/usr/bin/env python3
"""历史 K 线回补：把后复权日线批量写入 klines 表，为量化回测积累数据底座

用法（项目根目录执行；SQLite 兜底时无需 DB_* 环境变量，生产与 pipeline 用同一套环境变量）：
    python deploy/backfill_klines.py --list                 # 查看当前覆盖情况
    python deploy/backfill_klines.py                        # 回补 pool_items 出现过的全部标的
    python deploy/backfill_klines.py --since 2023-01-01     # 只补指定日期以来
    python deploy/backfill_klines.py --codes 600519.SH,00700.HK   # 指定标的（code.market）
    python deploy/backfill_klines.py --market HK --since 2024-01-01  # 只补港股
    python deploy/backfill_klines.py --limit 5              # 只跑前 5 只（冒烟测试）

口径：默认 fq=hfq（后复权）——历史值不随新增除权事件变动，适合长期落库；
与 run_pipeline 每日增量落库同口径，可重复执行（幂等覆盖）。
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db as D          # noqa: E402
import scrapers as S    # noqa: E402

BARS_CAP = 640             # 腾讯接口单次返回上限（实测 640/641 根封顶）


def load_pool_codes(market_filter: str = "") -> list:
    """从 pool_items 取历史出现过的全部标的（回测必须用'当时在池'的标的，这里做全量积累）"""
    with D.get_conn() as conn:
        cur = D._exec(conn, "SELECT DISTINCT code, market FROM pool_items ORDER BY market, code")
        rows = D._rows(cur)
    out = [(r["code"], r["market"]) for r in rows]
    if market_filter:
        out = [x for x in out if x[1].upper() == market_filter.upper()]
    return out


def parse_codes_arg(codes_arg: str, market_filter: str = "") -> list:
    """解析 --codes 600519.SH,00700.HK；无市场后缀时需 --market 配合"""
    out = []
    for item in codes_arg.split(","):
        item = item.strip()
        if not item:
            continue
        if "." in item:
            code, mkt = item.rsplit(".", 1)
            out.append((code.strip(), mkt.strip().upper()))
        elif market_filter:
            out.append((item, market_filter.upper()))
        else:
            print(f"  [跳过] {item}：缺市场后缀（写成 600519.SH / 00700.HK）且未给 --market")
    return out


def backfill_one(code: str, market: str, since: str, fq: str) -> int:
    """以 end 为游标向前翻页抓取并 upsert，返回累计写入行数。

    实测接口行为：A 股 fqkline 认 start/end 区间，港股 hkfqkline 只认 end+count
    （忽略 start）。统一按 end 翻页：每次取到 end 为止最近 BARS_CAP 根，
    再把 end 拨到已取最旧一日之前继续，直到覆盖 since 或取不到数据。
    多取到 since 之前的行会一并落库（幂等且更早历史是加分项）。
    """
    since_d = datetime.strptime(since, "%Y-%m-%d")
    end = datetime.now()
    total = 0
    prev_oldest = ""
    while end >= since_d:
        rows = S.fetch_kline(market, code, days=BARS_CAP, fq=fq,
                             end=end.strftime("%Y-%m-%d"))
        if not rows:
            break
        total += D.upsert_klines(code, market, rows, fq_type=fq)
        oldest = rows[0]["date"]          # 返回为日期升序，首行即最旧
        if oldest <= since:
            break
        if oldest == prev_oldest:         # 无进展保护，防接口异常死循环
            break
        prev_oldest = oldest
        end = datetime.strptime(oldest, "%Y-%m-%d") - timedelta(days=1)
    return total


def show_coverage() -> None:
    rows = D.kline_coverage()
    if not rows:
        print("klines 表为空——先跑一次回补或每日 pipeline。")
        return
    print(f"{'code':<10} {'market':<7} {'起':<12} {'止':<12} {'bars':>6}  最后写入")
    total = 0
    for r in rows:
        print(f"{r['code']:<10} {r['market']:<7} {str(r['min_date']):<12} "
              f"{str(r['max_date']):<12} {r['bars']:>6}  {r['last_write'] or '-'}")
        total += r["bars"]
    print(f"合计 {len(rows)} 个标的，{total} 行。")


def main() -> int:
    ap = argparse.ArgumentParser(description="历史 K 线回补（后复权，幂等）")
    ap.add_argument("--since", default="2020-01-01", help="回补起始日 YYYY-MM-DD，默认 2020-01-01")
    ap.add_argument("--codes", default="", help="指定标的，逗号分隔，如 600519.SH,00700.HK")
    ap.add_argument("--market", default="", help="市场过滤 SH/SZ/HK")
    ap.add_argument("--fq", default="hfq", choices=["hfq", "qfq", ""],
                    help="复权口径，默认 hfq（后复权，量化口径）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 只（冒烟测试用），0=不限")
    ap.add_argument("--list", action="store_true", help="只查看覆盖情况，不抓取")
    args = ap.parse_args()

    D.init_db()
    if args.list:
        show_coverage()
        return 0

    targets = (parse_codes_arg(args.codes, args.market) if args.codes
               else load_pool_codes(args.market))
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        print("无标的可补：pool_items 为空且未指定 --codes。")
        return 1

    print(f"回补 {len(targets)} 个标的，自 {args.since} 起，口径 fq={args.fq or 'raw'}")
    t0 = time.time()
    ok = fail = 0
    written = 0
    for i, (code, market) in enumerate(targets, 1):
        try:
            n = backfill_one(code, market, args.since, args.fq)
            written += n
            ok += 1
            print(f"  [{i}/{len(targets)}] {code}.{market}: +{n} 行")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  [{i}/{len(targets)}] {code}.{market}: 失败 {type(e).__name__}: {e}")
    print(f"完成：成功 {ok}，失败 {fail}，累计写入 {written} 行，"
          f"耗时 {time.time() - t0:.0f}s。覆盖情况：--list 查看。")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
