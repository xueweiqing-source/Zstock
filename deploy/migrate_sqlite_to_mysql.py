#!/usr/bin/env python3
"""SQLite → MySQL 数据迁移

用法：
    python migrate_sqlite_to_mysql.py [--sqlite data/forecast.db]

从 SQLite 读出全部记录写入 MySQL（按 DB_HOST 等环境变量连接）。
可重复执行：主键冲突时跳过已存在记录。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db as D  # noqa: E402


def _migrate_table(sqlite_conn, mysql_conn, table: str, pk_cols, batch_cols=None):
    """把一张表从 SQLite 搬到 MySQL"""
    src = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    src_cols = [d[0] for d in sqlite_conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
    if not src:
        print(f"  {table}: 0 行（跳过）")
        return 0

    # 探测目标表列（容错：列名不一致时跳过该列）
    cur = mysql_conn.cursor()
    cur.execute(f"SHOW COLUMNS FROM {table}")
    dst_cols = {r["Field"] if isinstance(r, dict) else r[0] for r in cur.fetchall()}
    cols = [c for c in src_cols if c in dst_cols]
    skipped = [c for c in src_cols if c not in dst_cols]
    if skipped:
        print(f"  {table}: 跳过列 {skipped}")

    placeholders = ",".join(["%s"] * len(cols))
    # 列名一律加反引号，避免 rank 等 MySQL 保留字
    col_csv = ",".join(f"`{c}`" for c in cols)

    n = 0
    for row in src:
        row = dict(row) if not isinstance(row, dict) else row
        vals = []
        for c in cols:
            v = row.get(c)
            # SQLite 存的 JSON 字符串原样搬
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            vals.append(v)
        try:
            if D.USE_MYSQL:
                # 用 INSERT IGNORE 让迁移可重复执行
                cur.execute(
                    f"INSERT IGNORE INTO {table} ({col_csv}) VALUES ({placeholders})",
                    tuple(vals),
                )
            n += 1
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] {table} 行写入失败: {e}")
    mysql_conn.commit()
    print(f"  {table}: 迁移 {n} 行")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default="data/forecast.db", help="SQLite 文件路径")
    args = ap.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"[错误] SQLite 文件不存在: {sqlite_path}")
        sys.exit(1)

    if not D.USE_MYSQL:
        print("[错误] 未设置 DB_HOST，目标不是 MySQL。请先配置环境变量。")
        sys.exit(1)

    print(f"源: {sqlite_path}  →  目标: MySQL {D.DB_HOST}:{D.DB_PORT}/{D.DB_NAME}")
    D.init_db()

    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row

    tables = ["runs", "reports", "pool_items", "predictions", "quotes_snap", "news_items"]
    # reports 表可能旧库没有
    existing = {r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    tables = [t for t in tables if t in existing]

    total = 0
    with D.get_conn() as conn:
        cur = conn.cursor()
        for t in tables:
            total += _migrate_table(src, conn, t, None)

    src.close()
    print(f"\n完成：共迁移 {total} 行。")
    print("建议校验：docker compose exec web python -c \"import db as D; print(D.list_runs(3))\"")


if __name__ == "__main__":
    main()
