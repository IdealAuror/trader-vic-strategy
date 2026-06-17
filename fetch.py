#!/usr/bin/env python3
"""数据拉取入口 — 拉取候选池全部股票 + 沪深 300 数据

Usage:
    python fetch.py [--tickers TICKER1,TICKER2] [--start 2010-01-01] [--end 20260616]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trader_vic.config import WATCHLIST, BACKTEST_START
from trader_vic.data.providers import fetch_watchlist, fetch_index


def main():
    parser = argparse.ArgumentParser(description="Trader Vic 数据拉取")
    parser.add_argument("--tickers", type=str, default=None,
                        help="逗号分隔的股票代码列表")
    parser.add_argument("--start", type=str, default=BACKTEST_START,
                        help=f"开始日期 (默认 {BACKTEST_START})")
    parser.add_argument("--end", type=str, default=None,
                        help="结束日期 (默认最新)")
    args = parser.parse_args()

    tickers = args.tickers.split(",") if args.tickers else WATCHLIST
    cache_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(cache_dir, exist_ok=True)

    # 去重
    tickers = list(set(tickers))
    print(f"拉取 {len(tickers)} 只股票数据 ({args.start} ~ {args.end or '最新'})")

    # 拉取候选池
    data = fetch_watchlist(tickers, start=args.start, end=args.end, cache_dir=cache_dir)
    print(f"成功拉取 {len(data)} 只股票")

    # 拉取沪深 300
    print("拉取沪深 300 指数...")
    try:
        csi300 = fetch_index("sh000300", start=args.start, end=args.end)
        csi300_path = os.path.join(cache_dir, "sh000300.csv")
        csi300.to_csv(csi300_path)
        print(f"  沪深 300: {len(csi300)} 行")
    except Exception as e:
        print(f"  拉取沪深 300 失败: {e}")

    # 拉取上证指数
    print("拉取上证指数...")
    try:
        sh = fetch_index("sh000001", start=args.start, end=args.end)
        sh_path = os.path.join(cache_dir, "sh000001.csv")
        sh.to_csv(sh_path)
        print(f"  上证指数: {len(sh)} 行")
    except Exception as e:
        print(f"  拉取上证指数失败: {e}")

    print(f"数据已缓存到 {cache_dir}/")
    print("完成！")


if __name__ == "__main__":
    main()
