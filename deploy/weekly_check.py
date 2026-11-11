#!/usr/bin/env python3
"""每周策略绩效体检：全池预测跟随回测（含置信度加权）并存档 JSON

用法（项目根目录，与 pipeline 相同的环境变量；SQLite 兜底时无需 DB_*）：
    python deploy/weekly_check.py                     # 全量体检并存档
    python deploy/weekly_check.py --since 2023-01-01  # 只体检该日期以来
    python deploy/weekly_check.py --stop-loss 8       # 带 8% 止损口径
    python deploy/weekly_check.py --no-save           # 只打印不存档

cron 示例（每周一 08:00，生产）：
    0 8 * * 1 cd /var/www/stock-forecast && docker compose exec -T web \
      python deploy/weekly_check.py --weighted >> /var/log/pool-check.log 2>&1

产出：data/checks/pool_check_YYYYMMDD_HHMMSS.json（完整报告含资金曲线）
     stdout 打印摘要（组合/加权/分方向），退出码 0=成功 1=无数据
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backtest as B   # noqa: E402
import config as C     # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="全池预测跟随策略绩效体检（含加权）")
    ap.add_argument("--since", default="", help="只体检该日期以来的预测")
    ap.add_argument("--stop-loss", type=float, default=0.0,
                    help="止损百分比，8 = 入场价下方 8%% 触发（0=关闭）")
    ap.add_argument("--no-save", action="store_true", help="只打印摘要，不写 JSON 存档")
    args = ap.parse_args()

    klines_map, preds_map = B.load_pool_from_db(args.since)
    if not preds_map:
        print(f"[体检] predictions 表无记录（since={args.since or '全部'}），跳过。")
        return 1

    rep = B.pred_pool_report(klines_map, preds_map, include_weighted=True,
                             stop_loss_pct=args.stop_loss)
    if not rep["meta"]["n_stocks"]:
        print("[体检] 无可回测标的（klines 历史不足，先跑 deploy/backfill_klines.py）。")
        return 1

    print(B._fmt_pool_report(rep))

    if not args.no_save:
        out_dir = C.DATA_DIR / "checks"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"pool_check_{ts}.json"
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n[体检] 报告已存档 {out}")

    # 单行健康摘要（便于 grep / 监控）
    s = rep["portfolio"]["stats"]
    w = rep.get("weighted") or {}
    ws = w.get("stats") or {}
    print(f"[体检摘要] 标的{rep['meta']['n_stocks']} 预测{rep['meta']['n_preds']} "
          f"等权{s['total_return_pct']:+.1f}% 加权{ws.get('total_return_pct', 'n/a')} "
          f"基准{s['buy_hold_pct']:+.1f}% 超额{s['excess_pct']:+.1f}% "
          f"回撤{s['max_drawdown_pct']:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
